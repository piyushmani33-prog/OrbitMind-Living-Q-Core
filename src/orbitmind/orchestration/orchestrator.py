"""Prime Orchestrator — drives one orbital mission across the system spine.

Mission Intake → Validation → Workflow → Propagation → Verification → Provenance →
Visual Output → Persistence → Audit. Each lifecycle transition is recorded; a
failed mission is persisted (never silently dropped, SR-08 / NFR-08/09).
"""

from __future__ import annotations

from typing import Any

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.config import Settings
from orbitmind.core.errors import OrbitMindError, PropagationError, ValidationError
from orbitmind.core.logging import get_logger
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.governance.provenance import ProvenanceRecord
from orbitmind.mission.models import Mission, MissionRequest, MissionStatus
from orbitmind.mission.validation import validate_mission_request
from orbitmind.orchestration.workflow import InProcessWorkflowEngine, WorkflowEngine
from orbitmind.persistence.database import Database
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
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
    ) -> None:
        self._settings = settings
        self._db = database
        self._registry = registry
        self._propagation = propagation
        self._verification = verification
        self._visualization = visualization
        self._engine: WorkflowEngine = engine or InProcessWorkflowEngine()

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
            self._persist_failure(mission.id, exc)
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
                    detail={"satellite_id": mission.satellite_id},
                )
            )
            session.commit()
        _log.info("mission.submitted", mission_id=mission.id, satellite_id=mission.satellite_id)

    def _execute(self, mission: Mission, request: MissionRequest) -> None:
        mission_id = mission.id
        with self._db.session() as session:
            repo = SqlAlchemyMissionRepository(session)

            # --- validation ---
            validate_mission_request(
                request, self._settings, self._registry.supported_satellite_ids()
            )
            repo.set_mission_status(mission_id, MissionStatus.VALIDATED)
            repo.add_audit_event(
                AuditEvent(mission_id=mission_id, action=AuditAction.MISSION_VALIDATED)
            )

            ctx = self._engine.start(mission_id=mission_id, name=WORKFLOW_NAME)
            repo.set_mission_status(mission_id, MissionStatus.RUNNING)
            repo.add_audit_event(
                AuditEvent(mission_id=mission_id, action=AuditAction.WORKFLOW_STARTED)
            )

            # --- load source + propagate ---
            with ctx.step("load_source") as detail:
                source = self._registry.get_source_record(request.satellite_id)
                line1, line2 = self._registry.get_tle(request.satellite_id)
                detail["source"] = source.source_name

            with ctx.step("propagate") as detail:
                result = self._propagation.propagate(
                    mission_id=mission_id,
                    request=request,
                    source=source,
                    tle_line1=line1,
                    tle_line2=line2,
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
            repo.add_provenance(
                mission_id,
                [
                    ProvenanceRecord(
                        subject_ref="scientific_result",
                        source_ref=f"{source.source_name} [{source.satellite_id}]",
                        method="sgp4-propagation",
                        inputs_hash=inputs_hash,
                        evidence=[self._registry.evidence_reference(request.satellite_id)],
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
            session.commit()
        _log.info("mission.completed", mission_id=mission_id)

    def _persist_failure(self, mission_id: str, exc: OrbitMindError) -> None:
        is_propagation = isinstance(exc, PropagationError)
        with self._db.session() as session:
            repo = SqlAlchemyMissionRepository(session)
            if is_propagation:
                repo.add_audit_event(
                    AuditEvent(
                        mission_id=mission_id,
                        action=AuditAction.PROPAGATION_FAILED,
                        detail={"reason": exc.message},
                    )
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
            session.commit()
        _log.warning("mission.failed", mission_id=mission_id, code=exc.code, reason=exc.message)


# Re-export for callers that construct fault scenarios in tests.
__all__ = ["WORKFLOW_NAME", "PrimeOrchestrator", "ValidationError"]
