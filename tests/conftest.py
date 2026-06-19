"""Shared pytest fixtures. All tests are fully offline and use temp dirs/DBs."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sgp4 import exporter
from sgp4.api import Satrec

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.mission.models import MissionRequest, OutputType
from orbitmind.persistence.database import Database
from orbitmind.sources.cache import SourceCacheStore
from orbitmind.sources.policies import SourceCatalog
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.models import ScientificResult
from orbitmind.space.propagation import PropagationService

_TEST_START = dt.datetime(2019, 12, 9, 17, 0, 0, tzinfo=dt.UTC)

# Reference ISS TLE used to synthesize realistic CelesTrak OMM/GP records in tests.
_ISS_L1 = "1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991"
_ISS_L2 = "2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482"
_CELESTRAK_KEYS = {
    "OBJECT_NAME",
    "OBJECT_ID",
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "EPHEMERIS_TYPE",
    "CLASSIFICATION_TYPE",
    "NORAD_CAT_ID",
    "ELEMENT_SET_NO",
    "REV_AT_EPOCH",
    "BSTAR",
    "MEAN_MOTION_DOT",
    "MEAN_MOTION_DDOT",
}


@pytest.fixture(autouse=True)
def _block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if any test performs a REAL outbound network request.

    TestClient (ASGI) and injected MockTransport are unaffected; only the real
    httpx transports are blocked.
    """

    def _blocked(self: Any, request: httpx.Request, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(f"real network access blocked in tests: {request.url}")

    monkeypatch.setattr("httpx.HTTPTransport.handle_request", _blocked)
    monkeypatch.setattr("httpx.AsyncHTTPTransport.handle_async_request", _blocked)


def build_celestrak_omm(epoch_iso: str = "2026-06-19T12:00:00.000000") -> dict[str, Any]:
    """A realistic CelesTrak GP/OMM JSON record (ISS) with a chosen EPOCH."""
    full = dict(exporter.export_omm(Satrec.twoline2rv(_ISS_L1, _ISS_L2), "ISS (ZARYA)"))
    omm = {k: v for k, v in full.items() if k in _CELESTRAK_KEYS}
    omm["EPOCH"] = epoch_iso
    return omm


def make_transport(
    *,
    records: list[dict[str, Any]] | None = None,
    status_code: int = 200,
    content_type: str = "application/json",
    raw_body: bytes | None = None,
    exc: type[Exception] | None = None,
) -> httpx.MockTransport:
    """Build a MockTransport returning a canned CelesTrak-style response."""

    def handler(request: httpx.Request) -> httpx.Response:
        if exc is not None:
            raise exc("synthetic transport error")
        headers = {"content-type": content_type}
        if raw_body is not None:
            return httpx.Response(status_code, content=raw_body, headers=headers)
        return httpx.Response(status_code, json=records or [], headers=headers)

    return httpx.MockTransport(handler)


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
def celestrak_settings(tmp_path: Path) -> Settings:
    """Settings with network + CelesTrak enabled (for connector/mission tests)."""
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'ct.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        network_enabled=True,
        celestrak_enabled=True,
        env="test",
    )


@pytest.fixture
def celestrak_client_factory(
    celestrak_settings: Settings,
) -> Callable[[httpx.MockTransport], TestClient]:
    """Factory: a TestClient whose CelesTrak connector uses the given transport."""

    def build(transport: httpx.MockTransport) -> TestClient:
        container = AppContainer(
            celestrak_settings, celestrak_transport=transport, celestrak_sleep=lambda _: None
        )
        return TestClient(create_app(container))

    return build


@pytest.fixture
def celestrak_db(celestrak_settings: Settings) -> Database:
    db = Database(celestrak_settings.database_url)
    db.create_all()
    return db


@pytest.fixture
def celestrak_store(celestrak_settings: Settings) -> SourceCacheStore:
    return SourceCacheStore(celestrak_settings.resolved_cache_dir())


@pytest.fixture
def celestrak_catalog(celestrak_settings: Settings) -> SourceCatalog:
    return SourceCatalog(celestrak_settings)


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
