"""Small-body service: coordinate JPL fetch → verify → persist → audit → artifacts.

Reuses the Phase 2 source repository (fetch/cache) and the audit_events table. No
network on construction; no silent fallback. Small bodies are NEVER sent to SGP4.
"""

from __future__ import annotations

from pydantic import BaseModel

from orbitmind.core.config import Settings
from orbitmind.core.errors import OrbitMindError
from orbitmind.core.logging import get_logger
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.persistence.database import Database
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.smallbody_repository import SqlAlchemySmallBodyRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.smallbody.models import CloseApproachResultSet, SmallBodyRecord
from orbitmind.smallbody.query import CadQueryFilter, SbdbQueryFilter, SmallBodyQueryResultSet
from orbitmind.smallbody.verification import SmallBodyVerificationService, overall_status
from orbitmind.sources.errors import SourceSchemaError
from orbitmind.sources.jpl.cad_connector import CadConnector
from orbitmind.sources.jpl.common import canonical_cache_key
from orbitmind.sources.jpl.query_connector import SbdbQueryConnector
from orbitmind.sources.jpl.sbdb_connector import SbdbConnector
from orbitmind.verification.models import VerificationFinding
from orbitmind.visualization.smallbody_charts import SmallBodyVisualizationService

_log = get_logger("smallbody.service")


class LookupOutcome(BaseModel):
    record: SmallBodyRecord
    findings: list[VerificationFinding]
    from_cache: bool
    artifacts: list[dict[str, str]] = []


class CadOutcome(BaseModel):
    result: CloseApproachResultSet
    findings: list[VerificationFinding]
    artifacts: list[dict[str, str]] = []


class SmallBodyService:
    """Coordinates small-body lookups, queries, and close-approach intelligence."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        sbdb: SbdbConnector,
        query: SbdbQueryConnector,
        cad: CadConnector,
        verification: SmallBodyVerificationService,
        visualization: SmallBodyVisualizationService,
    ) -> None:
        self._settings = settings
        self._db = database
        self._sbdb = sbdb
        self._query = query
        self._cad = cad
        self._verify = verification
        self._viz = visualization

    def lookup(
        self, identifier: str, *, force_refresh: bool = False, generate_artifacts: bool = False
    ) -> LookupOutcome:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            source_repo = SqlAlchemySourceRepository(session)
            sb_repo = SqlAlchemySmallBodyRepository(session)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.SMALL_BODY_LOOKUP_REQUESTED, detail={"id": identifier}
                )
            )
            try:
                result = self._sbdb.lookup(identifier, source_repo, force_refresh=force_refresh)
            except OrbitMindError as exc:
                session.rollback()
                self._record_failure(exc, identifier=identifier)
                raise

            findings = self._verify.verify(result.record)
            record = result.record.model_copy(
                update={"verification_status": overall_status(findings)}
            )
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.SMALL_BODY_NORMALIZED,
                    detail={
                        "object": record.identity.canonical_name,
                        "kind": record.identity.kind.value,
                    },
                )
            )
            artifacts: list[dict[str, str]] = []
            if generate_artifacts:
                summary = self._viz.render_orbit_summary(record)
                artifacts.append(summary.as_dict())
                illustration = self._viz.render_orbit_illustration(record)
                if illustration is not None:
                    artifacts.append(illustration.as_dict())
                for art in artifacts:
                    audit.add_audit_event(
                        AuditEvent(
                            action=AuditAction.SMALL_BODY_ARTIFACT_GENERATED,
                            detail={"type": art["type"]},
                        )
                    )
            sb_repo.save_small_body(record)
            audit.add_audit_event(
                AuditEvent(action=AuditAction.OBJECT_PERSISTED, detail={"object_id": record.id})
            )
            session.commit()
        _log.info("smallbody.lookup", object=record.identity.canonical_name)
        return LookupOutcome(
            record=record, findings=findings, from_cache=result.from_cache, artifacts=artifacts
        )

    def query(self, query_filter: SbdbQueryFilter) -> SmallBodyQueryResultSet:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            source_repo = SqlAlchemySourceRepository(session)
            sb_repo = SqlAlchemySmallBodyRepository(session)
            audit.add_audit_event(AuditEvent(action=AuditAction.SBDB_QUERY_REQUESTED))
            try:
                result = self._query.query(query_filter, source_repo)
            except OrbitMindError as exc:
                session.rollback()
                self._record_failure(exc, identifier="sbdb-query")
                raise
            sb_repo.save_query_run(
                source_id=result.source.source_id,
                run_type="sbdb-query",
                params_key=result.source.requested_identifier,
                total=result.total_reported,
                returned=result.returned,
                truncated=result.truncated,
                freshness_state=result.freshness.state.value,
                checksum=result.source.checksum,
                fetched_at=result.source.fetched_at,
            )
            if result.truncated:
                audit.add_audit_event(
                    AuditEvent(
                        action=AuditAction.RESULT_SET_TRUNCATED,
                        detail={"returned": result.returned, "total": result.total_reported},
                    )
                )
            audit.add_audit_event(AuditEvent(action=AuditAction.JPL_REQUEST_COMPLETED))
            session.commit()
        return result

    def close_approaches(
        self, query_filter: CadQueryFilter, *, generate_artifacts: bool = False
    ) -> CadOutcome:
        from orbitmind.core.ids import new_id

        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            source_repo = SqlAlchemySourceRepository(session)
            sb_repo = SqlAlchemySmallBodyRepository(session)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.CAD_QUERY_REQUESTED, detail={"body": query_filter.body}
                )
            )
            try:
                result = self._cad.close_approaches(query_filter, source_repo)
            except OrbitMindError as exc:
                session.rollback()
                self._record_failure(exc, identifier="cad")
                raise
            findings = self._verify.verify_close_approaches(result.records)
            params_key = canonical_cache_key(
                result.source.source_id, {"q": result.source.requested_identifier}
            )
            sb_repo.save_close_approaches(result, run_type="cad", params_key=params_key)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.CLOSE_APPROACHES_PERSISTED,
                    detail={"returned": result.returned},
                )
            )
            artifacts: list[dict[str, str]] = []
            if generate_artifacts and result.records:
                art = self._viz.render_close_approaches(
                    new_id(), result.records, label=query_filter.body
                )
                artifacts.append(art.as_dict())
                audit.add_audit_event(
                    AuditEvent(
                        action=AuditAction.SMALL_BODY_ARTIFACT_GENERATED, detail={"type": art.type}
                    )
                )
            if result.truncated:
                audit.add_audit_event(
                    AuditEvent(
                        action=AuditAction.RESULT_SET_TRUNCATED,
                        detail={"returned": result.returned, "total": result.total_reported},
                    )
                )
            session.commit()
        return CadOutcome(result=result, findings=findings, artifacts=artifacts)

    def _record_failure(self, exc: OrbitMindError, *, identifier: str) -> None:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.JPL_REQUEST_FAILED,
                    detail={"id": identifier, "code": exc.code, "reason": exc.message},
                )
            )
            if isinstance(exc, SourceSchemaError):
                audit.add_audit_event(
                    AuditEvent(action=AuditAction.SMALL_BODY_REJECTED, detail={"id": identifier})
                )
            session.commit()
        _log.warning("smallbody.failed", id=identifier, code=exc.code)
