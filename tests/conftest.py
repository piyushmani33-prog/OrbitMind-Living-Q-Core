"""Shared pytest fixtures. All tests are fully offline and use temp dirs/DBs."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.mission.models import MissionRequest, OutputType
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.models import ScientificResult
from orbitmind.space.propagation import PropagationService

_TEST_START = dt.datetime(2019, 12, 9, 17, 0, 0, tzinfo=dt.UTC)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at a temporary SQLite DB and artifacts directory."""
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        env="test",
    )


@pytest.fixture
def container(settings: Settings) -> AppContainer:
    """A fully wired application container backed by the temp database."""
    c = AppContainer(settings=settings)
    c.init_storage()
    return c


@pytest.fixture
def client(container: AppContainer) -> Iterator[TestClient]:
    """A TestClient bound to an app using the temp container."""
    with TestClient(create_app(container)) as test_client:
        yield test_client


@pytest.fixture
def iss_request() -> dict[str, object]:
    """A valid, deterministic orbit-propagation request near the TLE epoch."""
    return {
        "satellite_id": "ISS",
        "start_time": "2019-12-09T17:00:00Z",
        "end_time": "2019-12-09T18:00:00Z",
        "step_seconds": 120,
    }


@pytest.fixture
def mission_request() -> MissionRequest:
    """A valid domain MissionRequest near the TLE epoch (31 samples)."""
    return MissionRequest(
        satellite_id="ISS",
        start_time=_TEST_START,
        end_time=_TEST_START + dt.timedelta(hours=1),
        step_seconds=120,
        output_types=list(OutputType),
    )


@pytest.fixture
def scientific_result(mission_request: MissionRequest) -> ScientificResult:
    """A real deterministic propagation result for the bundled ISS fixture."""
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PropagationService().propagate(
        mission_id="00000000-0000-0000-0000-000000000000",
        request=mission_request,
        source=source,
        tle_line1=line1,
        tle_line2=line2,
    )
