"""Repository interface + SQLAlchemy implementation (ADR-0003).

Domain code depends on the :class:`MissionRepository` Protocol, not on SQLAlchemy.
All methods accept/return domain models; row<->domain mapping is internal.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbitmind.core.ids import new_id
from orbitmind.governance.audit import AuditEvent
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.governance.provenance import EvidenceReference, ProvenanceRecord
from orbitmind.mission.models import Mission, MissionRequest, MissionStatus
from orbitmind.orchestration.models import WorkflowRun, WorkflowStep
from orbitmind.persistence.models import (
    ArtifactRow,
    AuditEventRow,
    MissionRow,
    OrbitalSampleRow,
    ProvenanceRow,
    VerificationFindingRow,
    WorkflowRunRow,
)
from orbitmind.space.models import OrbitalStateSample, SampleStatus, Vector3
from orbitmind.verification.models import FindingStatus, Severity, VerificationFinding
from orbitmind.visualization.models import ArtifactRecord


class MissionRepository(Protocol):
    """Persistence boundary for missions and their related records."""

    def add_mission(self, mission: Mission) -> None: ...
    def set_mission_status(
        self,
        mission_id: str,
        status: MissionStatus,
        completed_at: datetime | None = None,
        epistemic_status: EpistemicStatus | None = None,
    ) -> None: ...
    def add_workflow_run(self, run: WorkflowRun) -> None: ...
    def add_samples(self, mission_id: str, samples: list[OrbitalStateSample]) -> None: ...
    def add_findings(self, mission_id: str, findings: list[VerificationFinding]) -> None: ...
    def add_provenance(self, mission_id: str, records: list[ProvenanceRecord]) -> None: ...
    def add_artifacts(self, records: list[ArtifactRecord]) -> None: ...
    def add_audit_event(self, event: AuditEvent) -> None: ...

    def get_mission(self, mission_id: str) -> Mission | None: ...
    def list_missions(self, limit: int, offset: int) -> list[Mission]: ...
    def count_missions(self) -> int: ...
    def get_samples(self, mission_id: str) -> list[OrbitalStateSample]: ...
    def get_findings(self, mission_id: str) -> list[VerificationFinding]: ...
    def get_provenance(self, mission_id: str) -> list[ProvenanceRecord]: ...
    def get_artifacts(self, mission_id: str) -> list[ArtifactRecord]: ...
    def get_audit_events(self, mission_id: str) -> list[AuditEvent]: ...
    def get_workflow_run(self, mission_id: str) -> WorkflowRun | None: ...


class SqlAlchemyMissionRepository:
    """SQLAlchemy-backed :class:`MissionRepository`."""

    def __init__(self, session: Session) -> None:
        self._s = session

    # ---- write side --------------------------------------------------------
    def add_mission(self, mission: Mission) -> None:
        self._s.add(
            MissionRow(
                id=mission.id,
                satellite_id=mission.satellite_id,
                status=mission.status.value,
                raw_request=mission.raw_request,
                normalized_request=mission.normalized_request.model_dump(mode="json"),
                epistemic_status=mission.epistemic_status.value,
                created_at=mission.created_at,
                completed_at=mission.completed_at,
            )
        )

    def set_mission_status(
        self,
        mission_id: str,
        status: MissionStatus,
        completed_at: datetime | None = None,
        epistemic_status: EpistemicStatus | None = None,
    ) -> None:
        row = self._s.get(MissionRow, mission_id)
        if row is None:
            return
        row.status = status.value
        if completed_at is not None:
            row.completed_at = completed_at
        if epistemic_status is not None:
            row.epistemic_status = epistemic_status.value

    def add_workflow_run(self, run: WorkflowRun) -> None:
        self._s.add(
            WorkflowRunRow(
                id=run.id,
                mission_id=run.mission_id,
                workflow_name=run.workflow_name,
                status=run.status.value,
                steps=[s.model_dump(mode="json") for s in run.steps],
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
        )

    def add_samples(self, mission_id: str, samples: list[OrbitalStateSample]) -> None:
        for s in samples:
            pos = s.position_km
            vel = s.velocity_kmps
            self._s.add(
                OrbitalSampleRow(
                    id=new_id(),
                    mission_id=mission_id,
                    ts=s.timestamp,
                    pos_x_km=pos.x if pos else None,
                    pos_y_km=pos.y if pos else None,
                    pos_z_km=pos.z if pos else None,
                    vel_x_kmps=vel.x if vel else None,
                    vel_y_kmps=vel.y if vel else None,
                    vel_z_kmps=vel.z if vel else None,
                    lat_deg=s.latitude_deg,
                    lon_deg=s.longitude_deg,
                    alt_km=s.altitude_km,
                    status=s.status.value,
                    error=s.error,
                )
            )

    def add_findings(self, mission_id: str, findings: list[VerificationFinding]) -> None:
        for f in findings:
            self._s.add(
                VerificationFindingRow(
                    id=new_id(),
                    mission_id=mission_id,
                    check_id=f.check_id,
                    severity=f.severity.value,
                    status=f.status.value,
                    explanation=f.explanation,
                    values=f.values,
                )
            )

    def add_provenance(self, mission_id: str, records: list[ProvenanceRecord]) -> None:
        for p in records:
            self._s.add(
                ProvenanceRow(
                    id=new_id(),
                    mission_id=mission_id,
                    subject_ref=p.subject_ref,
                    source_ref=p.source_ref,
                    method=p.method,
                    inputs_hash=p.inputs_hash,
                    generated_at=p.generated_at,
                    evidence=[e.model_dump(mode="json") for e in p.evidence],
                )
            )

    def add_artifacts(self, records: list[ArtifactRecord]) -> None:
        for a in records:
            self._s.add(
                ArtifactRow(
                    id=a.id,
                    mission_id=a.mission_id,
                    type=a.type.value,
                    path=a.path,
                    sidecar_path=a.sidecar_path,
                    checksum=a.checksum,
                    created_at=a.created_at,
                )
            )

    def add_audit_event(self, event: AuditEvent) -> None:
        self._s.add(
            AuditEventRow(
                id=event.id,
                mission_id=event.mission_id,
                action=event.action.value,
                actor=event.actor,
                detail=event.detail,
                at=event.at,
            )
        )

    # ---- read side ---------------------------------------------------------
    def get_mission(self, mission_id: str) -> Mission | None:
        row = self._s.get(MissionRow, mission_id)
        return _row_to_mission(row) if row is not None else None

    def list_missions(self, limit: int, offset: int) -> list[Mission]:
        stmt = select(MissionRow).order_by(MissionRow.created_at.desc()).limit(limit).offset(offset)
        return [_row_to_mission(r) for r in self._s.execute(stmt).scalars().all()]

    def count_missions(self) -> int:
        result = self._s.execute(select(func.count()).select_from(MissionRow)).scalar_one()
        return int(result)

    def get_samples(self, mission_id: str) -> list[OrbitalStateSample]:
        stmt = (
            select(OrbitalSampleRow)
            .where(OrbitalSampleRow.mission_id == mission_id)
            .order_by(OrbitalSampleRow.ts)
        )
        return [_row_to_sample(r) for r in self._s.execute(stmt).scalars().all()]

    def get_findings(self, mission_id: str) -> list[VerificationFinding]:
        stmt = select(VerificationFindingRow).where(VerificationFindingRow.mission_id == mission_id)
        return [
            VerificationFinding(
                check_id=r.check_id,
                severity=Severity(r.severity),
                status=FindingStatus(r.status),
                explanation=r.explanation,
                values=r.values,
            )
            for r in self._s.execute(stmt).scalars().all()
        ]

    def get_provenance(self, mission_id: str) -> list[ProvenanceRecord]:
        stmt = select(ProvenanceRow).where(ProvenanceRow.mission_id == mission_id)
        return [
            ProvenanceRecord(
                subject_ref=r.subject_ref,
                source_ref=r.source_ref,
                method=r.method,
                inputs_hash=r.inputs_hash,
                generated_at=r.generated_at,
                evidence=[EvidenceReference(**e) for e in r.evidence],
            )
            for r in self._s.execute(stmt).scalars().all()
        ]

    def get_artifacts(self, mission_id: str) -> list[ArtifactRecord]:
        from orbitmind.mission.models import OutputType

        stmt = select(ArtifactRow).where(ArtifactRow.mission_id == mission_id)
        return [
            ArtifactRecord(
                id=r.id,
                mission_id=r.mission_id,
                type=OutputType(r.type),
                path=r.path,
                sidecar_path=r.sidecar_path,
                checksum=r.checksum,
                created_at=r.created_at,
            )
            for r in self._s.execute(stmt).scalars().all()
        ]

    def get_audit_events(self, mission_id: str) -> list[AuditEvent]:
        from orbitmind.governance.audit import AuditAction

        stmt = (
            select(AuditEventRow)
            .where(AuditEventRow.mission_id == mission_id)
            .order_by(AuditEventRow.at)
        )
        return [
            AuditEvent(
                id=r.id,
                mission_id=r.mission_id,
                action=AuditAction(r.action),
                actor=r.actor,
                detail=r.detail,
                at=r.at,
            )
            for r in self._s.execute(stmt).scalars().all()
        ]

    def get_workflow_run(self, mission_id: str) -> WorkflowRun | None:
        from orbitmind.orchestration.models import WorkflowStatus

        stmt = select(WorkflowRunRow).where(WorkflowRunRow.mission_id == mission_id)
        row = self._s.execute(stmt).scalars().first()
        if row is None:
            return None
        return WorkflowRun(
            id=row.id,
            mission_id=row.mission_id,
            workflow_name=row.workflow_name,
            status=WorkflowStatus(row.status),
            steps=[WorkflowStep(**s) for s in row.steps],
            started_at=row.started_at,
            finished_at=row.finished_at,
        )


def _row_to_mission(row: MissionRow) -> Mission:
    return Mission(
        id=row.id,
        satellite_id=row.satellite_id,
        status=MissionStatus(row.status),
        raw_request=row.raw_request,
        normalized_request=MissionRequest.model_validate(row.normalized_request),
        epistemic_status=EpistemicStatus(row.epistemic_status),
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _vec(x: float | None, y: float | None, z: float | None) -> Vector3 | None:
    if x is None or y is None or z is None:
        return None
    return Vector3(x=x, y=y, z=z)


def _row_to_sample(row: OrbitalSampleRow) -> OrbitalStateSample:
    return OrbitalStateSample(
        timestamp=row.ts,
        position_km=_vec(row.pos_x_km, row.pos_y_km, row.pos_z_km),
        velocity_kmps=_vec(row.vel_x_kmps, row.vel_y_kmps, row.vel_z_kmps),
        latitude_deg=row.lat_deg,
        longitude_deg=row.lon_deg,
        altitude_km=row.alt_km,
        status=SampleStatus(row.status),
        error=row.error,
    )
