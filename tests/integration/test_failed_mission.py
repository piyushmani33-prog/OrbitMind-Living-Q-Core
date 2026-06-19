"""Integration test: a failed mission is persisted, not silently dropped (NFR-08)."""

from __future__ import annotations

from typing import Any

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.core.errors import PropagationError
from orbitmind.mission.models import MissionRequest, MissionStatus
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.space.propagation import PropagationService
from orbitmind.verification.checks import VerificationService
from orbitmind.visualization.charts import VisualizationService

pytestmark = pytest.mark.integration


class _BoomPropagation(PropagationService):
    """A propagation service that always fails (fault injection)."""

    def propagate(self, **kwargs: Any) -> Any:
        raise PropagationError("synthetic propagation failure")


def test_failed_mission_persisted_with_audit(
    container: AppContainer, mission_request: MissionRequest
) -> None:
    orchestrator = PrimeOrchestrator(
        settings=container.settings,
        database=container.database,
        registry=container.registry,
        propagation=_BoomPropagation(),
        verification=VerificationService(),
        visualization=VisualizationService(container.settings.resolved_artifacts_dir()),
    )

    with pytest.raises(PropagationError):
        orchestrator.run_orbit_mission(raw_request={"satellite_id": "ISS"}, request=mission_request)

    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        missions = repo.list_missions(limit=10, offset=0)
        assert len(missions) == 1
        mission = missions[0]
        assert mission.status is MissionStatus.FAILED

        actions = [event.action.value for event in repo.get_audit_events(mission.id)]
        assert "mission.submitted" in actions
        assert "propagation.failed" in actions
        assert "mission.failed" in actions
        # No artifacts were produced for the failed mission.
        assert repo.get_artifacts(mission.id) == []
