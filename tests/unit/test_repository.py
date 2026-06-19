"""Unit tests for the SQLAlchemy mission repository (round-trip behavior)."""

from __future__ import annotations

from orbitmind.api.container import AppContainer
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.mission.models import Mission, MissionRequest, MissionStatus
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.space.models import ScientificResult
from orbitmind.verification.checks import VerificationService


def _make_mission(request: MissionRequest) -> Mission:
    return Mission(
        satellite_id=request.satellite_id,
        raw_request={"satellite_id": request.satellite_id},
        normalized_request=request,
    )


def test_mission_round_trip(container: AppContainer, mission_request: MissionRequest) -> None:
    mission = _make_mission(mission_request)
    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        repo.add_mission(mission)
        repo.add_audit_event(
            AuditEvent(mission_id=mission.id, action=AuditAction.MISSION_SUBMITTED)
        )
        session.commit()

    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        loaded = repo.get_mission(mission.id)
        assert loaded is not None
        assert loaded.satellite_id == "ISS"
        assert loaded.status is MissionStatus.RECEIVED
        assert loaded.normalized_request.step_seconds == mission_request.step_seconds
        assert len(repo.get_audit_events(mission.id)) == 1


def test_status_and_epistemic_update(
    container: AppContainer, mission_request: MissionRequest
) -> None:
    mission = _make_mission(mission_request)
    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        repo.add_mission(mission)
        repo.set_mission_status(
            mission.id,
            MissionStatus.COMPLETED,
            epistemic_status=EpistemicStatus.DETERMINISTIC_CALCULATION,
        )
        session.commit()

    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        loaded = repo.get_mission(mission.id)
        assert loaded is not None
        assert loaded.status is MissionStatus.COMPLETED
        assert loaded.epistemic_status is EpistemicStatus.DETERMINISTIC_CALCULATION


def test_samples_and_findings_persist(
    container: AppContainer,
    mission_request: MissionRequest,
    scientific_result: ScientificResult,
) -> None:
    mission = _make_mission(mission_request)
    findings = VerificationService().verify(scientific_result, mission_request)
    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        repo.add_mission(mission)
        repo.add_samples(mission.id, scientific_result.samples)
        repo.add_findings(mission.id, findings)
        session.commit()

    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        samples = repo.get_samples(mission.id)
        assert len(samples) == len(scientific_result.samples)
        assert samples[0].timestamp.tzinfo is not None  # UTC preserved
        assert len(repo.get_findings(mission.id)) == len(findings)


def test_list_and_count(container: AppContainer, mission_request: MissionRequest) -> None:
    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        for _ in range(3):
            repo.add_mission(_make_mission(mission_request))
        session.commit()

    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        assert repo.count_missions() == 3
        assert len(repo.list_missions(limit=2, offset=0)) == 2
