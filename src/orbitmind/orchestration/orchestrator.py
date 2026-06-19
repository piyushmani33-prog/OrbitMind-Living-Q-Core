"""Prime Orchestrator — drives one orbital mission across the system spine.

Mission Intake → Validation → Source Resolution → Workflow → Propagation →
Verification → Provenance → Visual Output → Persistence → Audit. Each lifecycle
transition is recorded; a failed mission is persisted (never silently dropped,
SR-08 / NFR-08/09). The source (bundled sample or CelesTrak) is resolved behind a
single interface; there is no silent fallback from external to sample data.
"""

from __future__ import annotations

from typing import Any

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.config import Settings
from orbitmind.core.errors import OrbitMindError, PropagationError
from orbitmind.core.logging import get_logger
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.governance.provenance import ProvenanceRecord
from orbitmind.mission.models import Mission, MissionRequest, MissionSource, MissionStatus
from orbitmind.mission.validation import validate_mission_request
from orbitmind.orchestration.source_resolver import ResolvedOrbit, SourceResolver
from orbitmind.orchestration.workflow import InProcessWorkflowEngine, WorkflowEngine
from orbitmind.persistence.database import Database
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.sources.errors import NetworkDisabledError, SourceError, SourceSchemaError
from orbitmind.sources.models import FetchOutcome, FreshnessState, SourceHealth
from orbitmind.sources.policies import CELESTRAK_SOURCE_ID, SourceCatalog
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.propagation import PropagationService
from orbitmind.verification.checks import VerificationService
from orbitmind.verification.models import FindingStatus, Severity
from orbitmind.visualization.charts import VisualizationService

_log = get_logger("orchestration.orchestrator")

WORKFLOW_NAME = "orbit_propagation"


class PrimeOrchestrator:
    """Coordinates the deterministic orbital mission workflow."""

    def __init__(
        self,
        *,
        settings: Settings,
        database: Database,
        registry: SourceRegistry,
        propagation: PropagationService,
        verification: VerificationService,
        visualization: VisualizationService,
        engine: WorkflowEngine | None = None,
        resolver: SourceResolver | None = None,
    ) -> None:
        self._settings = settings
        self._db = database
        self._registry = registry
        self._propagation = propagation
        self._verification = verification
        self._visualization = visualization
        self._engine: WorkflowEngine = engine or InProcessWorkflowEngine()
        # Default resolver is sample-only (no CelesTrak) to preserve offline behavior.
        self._resolver = resolver or SourceResolver(registry, SourceCatalog(settings), None)

    def run_orbit_mission(self, *, raw_request: dict[str, Any], request: MissionRequest) -> str:
        """Execute a full mission; return its id. Failures are persisted then raised."""
        mission = Mission(
            satellite_id=request.satellite_id,
            raw_request=raw_request,
            normalized_request=request,
        )
        self._persist_received(mission)
        try:
            self._execute(mission, request)
        except OrbitMindError as exc:
            self._persist_failure(mission, exc)
            raise
        return mission.id

    # ---- internal stages ---------------------------------------------------
    def _persist_received(self, mission: Mission) -> None:
        with self._db.session() as session:
            repo = SqlAlchemyMissionRepository(session)
            repo.add_mission(mission)
            repo.add_audit_event(
                AuditEvent(
                    mission_id=mission.id,
                    action=AuditAction.MISSION_SUBMITTED,
                    detail={
                        "satellite_id": mission.satellite_id,
                        "source": mission.normalized_request.source.value,
                    },
                )
            )
            session.commit()
        _log.info("mission.submitted", mission_id=mission.id, satellite_id=mission.satellite_id)

    def _execute(self, mission: Mission, request: MissionRequest) -> None:
        mission_id = mission.id
        with self._db.session() as session:
            repo = SqlAlchemyMissionRepository(session)
            source_repo = SqlAlchemySourceRepository(session)

            # --- validation ---
            validate_mission_request(request, self._settings, self._resolver.sample_satellite_ids())
            repo.set_mission_status(mission_id, MissionStatus.VALIDATED)
            repo.add_audit_event(
                AuditEvent(mission_id=mission_id, action=AuditAction.MISSION_VALIDATED)
            )

            ctx = self._engine.start(mission_id=mission_id, name=WORKFLOW_NAME)
            repo.set_mission_status(mission_id, MissionStatus.RUNNING)
            repo.add_audit_event(
                AuditEvent(mission_id=mission_id, action=AuditAction.WORKFLOW_STARTED)
            )

            # --- source resolution (sample or CelesTrak, one interface) ---
            if request.source is MissionSource.CELESTRAK:
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id,
                        action=AuditAction.SOURCE_ACCESS_REQUESTED,
                        detail={"source": request.source.value, "id": request.satellite_id},
                    )
                )
            with ctx.step("load_source") as detail:
                resolved = self._resolver.resolve(request, source_repo)
                detail["source"] = resolved.source_id
                detail["freshness"] = resolved.element_record.freshness.state.value
            self._emit_source_audit(repo, mission_id, request, resolved)
            source_repo.add_element_record(
                resolved.element_record, mission_id, resolved.policy_version
            )

            # --- propagate (unchanged deterministic SGP4 path) ---
            with ctx.step("propagate") as detail:
                result = self._propagation.propagate(
                    mission_id=mission_id,
                    request=request,
                    source=resolved.source_record,
                    tle_line1=resolved.tle_line1,
                    tle_line2=resolved.tle_line2,
                )
                detail["samples"] = len(result.samples)

            repo.add_samples(mission_id, result.samples)
            repo.add_audit_event(
                AuditEvent(
                    mission_id=mission_id,
                    action=AuditAction.PROPAGATION_COMPLETED,
                    detail=result.summary,
                )
            )

            # --- provenance ---
            inputs_hash = sha256_canonical_json(request.model_dump(mode="json"))
            evidence = list(resolved.evidence)
            repo.add_provenance(
                mission_id,
                [
                    ProvenanceRecord(
                        subject_ref="scientific_result",
                        source_ref=(
                            f"{resolved.source_record.source_name} "
                            f"[{resolved.source_id}:{request.satellite_id}]"
                        ),
                        method="sgp4-propagation",
                        inputs_hash=inputs_hash,
                        evidence=evidence,
                    )
                ],
            )

            # --- verification ---
            with ctx.step("verify") as detail:
                findings = self._verification.verify(result, request)
                detail["findings"] = len(findings)
            repo.add_findings(mission_id, findings)
            critical_failures = [
                f
                for f in findings
                if f.status is FindingStatus.FAILED
                and f.severity in (Severity.ERROR, Severity.CRITICAL)
            ]
            verification_passed = not critical_failures
            repo.add_audit_event(
                AuditEvent(
                    mission_id=mission_id,
                    action=AuditAction.VERIFICATION_COMPLETED,
                    detail={
                        "checks": len(findings),
                        "passed": verification_passed,
                        "critical_failures": len(critical_failures),
                    },
                )
            )

            # --- visualization ---
            with ctx.step("visualize") as detail:
                artifacts = self._visualization.render(
                    mission_id=mission_id,
                    result=result,
                    output_types=request.output_types,
                    verification_passed=verification_passed,
                )
                detail["artifacts"] = [a.type.value for a in artifacts]
            repo.add_artifacts(artifacts)
            for artifact in artifacts:
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id,
                        action=AuditAction.ARTIFACT_GENERATED,
                        detail={"type": artifact.type.value, "path": artifact.path},
                    )
                )

            # --- complete ---
            run = ctx.complete()
            repo.add_workflow_run(run)
            repo.set_mission_status(
                mission_id,
                MissionStatus.COMPLETED,
                completed_at=utcnow(),
                epistemic_status=result.epistemic_status,
            )
            repo.add_audit_event(
                AuditEvent(mission_id=mission_id, action=AuditAction.MISSION_COMPLETED)
            )
            if request.source is MissionSource.CELESTRAK and not resolved.used_fallback:
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id,
                        action=AuditAction.EXTERNAL_MISSION_COMPLETED,
                        detail={"freshness": resolved.element_record.freshness.state.value},
                    )
                )
            session.commit()
        _log.info("mission.completed", mission_id=mission_id, source=resolved.source_id)

    @staticmethod
    def _emit_source_audit(
        repo: SqlAlchemyMissionRepository,
        mission_id: str,
        request: MissionRequest,
        resolved: ResolvedOrbit,
    ) -> None:
        if request.source is not MissionSource.CELESTRAK:
            return
        if resolved.used_fallback:
            repo.add_audit_event(
                AuditEvent(
                    mission_id=mission_id,
                    action=AuditAction.SOURCE_REQUEST_FAILED,
                    detail={"fallback_to": "sample", "note": "explicit sample fallback used"},
                )
            )
            return
        fetch = resolved.fetch
        if fetch is None:
            return
        freshness = resolved.element_record.freshness
        if fetch.outcome is FetchOutcome.FETCHED:
            for action in (
                AuditAction.CACHE_MISS,
                AuditAction.SOURCE_REQUEST_STARTED,
                AuditAction.SOURCE_REQUEST_COMPLETED,
                AuditAction.RECORD_NORMALIZED,
            ):
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id, action=action, detail={"checksum": fetch.checksum}
                    )
                )
        elif fetch.outcome is FetchOutcome.CACHED:
            repo.add_audit_event(
                AuditEvent(
                    mission_id=mission_id,
                    action=AuditAction.CACHE_HIT,
                    detail={"cache_key": fetch.cache_key},
                )
            )
        elif fetch.outcome is FetchOutcome.SUPPRESSED:
            repo.add_audit_event(
                AuditEvent(mission_id=mission_id, action=AuditAction.REFRESH_SUPPRESSED)
            )
        if freshness.state in (FreshnessState.STALE, FreshnessState.EXPIRED):
            repo.add_audit_event(
                AuditEvent(
                    mission_id=mission_id,
                    action=AuditAction.STALE_RECORD_USED,
                    detail={"freshness": freshness.state.value},
                )
            )

    def _persist_failure(self, mission: Mission, exc: OrbitMindError) -> None:
        mission_id = mission.id
        is_external = mission.normalized_request.source is MissionSource.CELESTRAK
        with self._db.session() as session:
            repo = SqlAlchemyMissionRepository(session)
            source_repo = SqlAlchemySourceRepository(session)
            if isinstance(exc, PropagationError):
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id,
                        action=AuditAction.PROPAGATION_FAILED,
                        detail={"reason": exc.message},
                    )
                )
            if isinstance(exc, NetworkDisabledError):
                repo.add_audit_event(
                    AuditEvent(mission_id=mission_id, action=AuditAction.NETWORK_REJECTED)
                )
            elif isinstance(exc, SourceSchemaError):
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id,
                        action=AuditAction.SOURCE_SCHEMA_REJECTED,
                        detail={"reason": exc.message},
                    )
                )
            elif isinstance(exc, SourceError):
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id,
                        action=AuditAction.SOURCE_REQUEST_FAILED,
                        detail={"reason": exc.message},
                    )
                )
            if isinstance(exc, SourceError) and is_external:
                source_repo.add_health_event(
                    CELESTRAK_SOURCE_ID, SourceHealth.DEGRADED, exc.message
                )

            repo.set_mission_status(
                mission_id,
                MissionStatus.FAILED,
                completed_at=utcnow(),
                epistemic_status=EpistemicStatus.REJECTED,
            )
            repo.add_audit_event(
                AuditEvent(
                    mission_id=mission_id,
                    action=AuditAction.MISSION_FAILED,
                    detail={"reason": exc.message, "code": exc.code},
                )
            )
            if is_external:
                repo.add_audit_event(
                    AuditEvent(mission_id=mission_id, action=AuditAction.EXTERNAL_MISSION_FAILED)
                )
            session.commit()
        _log.warning("mission.failed", mission_id=mission_id, code=exc.code, reason=exc.message)


__all__ = ["WORKFLOW_NAME", "PrimeOrchestrator"]
