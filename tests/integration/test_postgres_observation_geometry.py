"""Live PostgreSQL tests for Phase 4C observation-geometry persistence."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.core.config import Settings
from orbitmind.core.errors import IdempotencyConflictError, ValidationError
from orbitmind.observation_geometry import persistence_service
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_geometry.service import compute_observation_geometry
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_geometry_models import (
    ObservationGeometryRequestRow,
    ObservationGeometryRunRow,
)
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
)
from orbitmind.sources.registry import SourceRegistry

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC)
_TABLES = ("observation_geometry_runs", "observation_geometry_requests")
BASE = "/api/v1/observation-geometry"


@pytest.fixture()
def pg_db() -> Database:
    assert _PG_URL is not None
    db = Database(_PG_URL)
    assert db.is_postgres
    with db.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield db
    db.engine.dispose()


@pytest.fixture()
def pg_container(tmp_path: Path) -> AppContainer:
    assert _PG_URL is not None
    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
    )
    container = AppContainer(settings=settings)
    container.init_storage = lambda: None  # type: ignore[method-assign]
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield container
    container.database.engine.dispose()


def _client(
    container: AppContainer,
    owner_id: str = "owner-a",
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _request(site_id: str = "SITE-PG") -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=START,
        end=START + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _counts(db: Database) -> tuple[int, int]:
    with db.session() as session:
        request_count = session.scalar(
            select(func.count()).select_from(ObservationGeometryRequestRow)
        )
        run_count = session.scalar(select(func.count()).select_from(ObservationGeometryRunRow))
    return int(request_count or 0), int(run_count or 0)


def _persist_api_fixture(
    container: AppContainer,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-PG",
) -> tuple[str, str, str, str]:
    request = _request(site_id)
    with container.database.session() as session:
        execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=request,
            idempotency_key=f"{owner_id}-{site_id}",
        )
    return (
        execution.request_id,
        execution.run_id,
        execution.request_checksum,
        execution.geometry_checksum,
    )


def test_postgres_geometry_execution_replay_owner_isolation_and_tamper(
    pg_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    with pg_db.session() as session:
        first = execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=request,
            idempotency_key="pg-geometry-replay",
        )
    with pg_db.session() as session:
        independent = execute_and_persist_geometry(
            session=session,
            owner_id="owner-b",
            request=request,
            idempotency_key="pg-geometry-replay",
        )

    def fail_if_recomputed(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise AssertionError("PostgreSQL exact replay should not recompute geometry")

    monkeypatch.setattr(persistence_service, "compute_observation_geometry", fail_if_recomputed)
    with pg_db.session() as session:
        replay = execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=request,
            idempotency_key="pg-geometry-replay",
        )

    assert replay.request_id == first.request_id
    assert replay.run_id == first.run_id
    assert replay.run_created is False
    assert independent.request_id != first.request_id
    assert independent.geometry_checksum == first.geometry_checksum

    with pg_db.session() as session:
        session.execute(
            update(ObservationGeometryRunRow)
            .where(ObservationGeometryRunRow.id == first.run_id)
            .values(geometry_checksum="0" * 64)
        )
        session.commit()

    with pg_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        with pytest.raises(ValidationError, match="checksum"):
            repository.get_geometry_run(first.run_id, owner_id="owner-a")


def test_postgres_geometry_idempotency_conflict_before_compute(
    pg_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pg_db.session() as session:
        execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=_request("SITE-PG-A"),
            idempotency_key="pg-conflict",
        )
    called = False

    def mark_called(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        nonlocal called
        called = True
        raise AssertionError("conflict should stop before computation")

    monkeypatch.setattr(persistence_service, "compute_observation_geometry", mark_called)
    with pg_db.session() as session, pytest.raises(IdempotencyConflictError):
        execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=_request("SITE-PG-B"),
            idempotency_key="pg-conflict",
        )

    assert called is False
    assert _counts(pg_db) == (1, 1)


def test_postgres_geometry_owner_fk_and_delete_restrictions(pg_db: Database) -> None:
    request = _request()
    result = compute_observation_geometry(request)
    with pg_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        stored = repository.create_geometry_request(request, owner_id="owner-a")
        session.commit()

    with pg_db.session() as session:
        bad_run = ObservationGeometryRunRow(
            id="pg-bad-run",
            owner_id="owner-b",
            request_id=stored.request.id,
            request_checksum=result.request_checksum,
            geometry_checksum=result.geometry_checksum,
            element_checksum=result.element_checksum,
            source_identity_checksum=result.source_identity_checksum,
            result_schema_version=result.schema_version,
            computation_version=result.computation_version,
            run_status="completed",
            epistemic_status=result.epistemic_status.value,
            sample_count=result.sample_count,
            failed_sample_count=result.failed_sample_count,
            interval_count=len(result.intervals),
            limitations_json=list(result.limitations),
            result_json=result.model_dump(mode="json"),
            created_at=dt.datetime.now(UTC),
            completed_at=dt.datetime.now(UTC),
        )
        session.add(bad_run)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    with pg_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        run = repository.persist_geometry_result(
            request_id=stored.request.id,
            owner_id="owner-a",
            result=result,
        )
        session.commit()

    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("DELETE FROM observation_geometry_requests WHERE id=:request_id"),
                {"request_id": stored.request.id},
            )
        trans.rollback()

    with pg_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        assert repository.get_geometry_request(stored.request.id, owner_id="owner-a") is not None
        assert repository.get_geometry_run(run.run.id, owner_id="owner-a") is not None


def test_postgres_geometry_request_race_recovery(
    pg_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    with pg_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        existing = repository.create_geometry_request(
            request,
            owner_id="owner-a",
            idempotency_key="pg-race",
        )
        session.commit()

    with pg_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        original_find = repository._find_request_by_idempotency
        original_find_checksum = repository._find_request_by_checksum
        original_flush = session.flush
        calls = {"find": 0, "find_checksum": 0, "flush": 0}

        def fake_find(owner_id: str, idempotency_key: str) -> ObservationGeometryRequestRow | None:
            if calls["find"] == 0:
                calls["find"] += 1
                return None
            return original_find(owner_id, idempotency_key)

        def fake_find_checksum(
            owner_id: str, checksum: str
        ) -> ObservationGeometryRequestRow | None:
            if calls["find_checksum"] == 0:
                calls["find_checksum"] += 1
                return None
            return original_find_checksum(owner_id, checksum)

        def fake_flush(*args: object, **kwargs: object) -> None:
            inserting_request = any(
                isinstance(obj, ObservationGeometryRequestRow) for obj in session.new
            )
            if calls["flush"] == 0 and inserting_request:
                calls["flush"] += 1
                raise IntegrityError("insert", {}, RuntimeError("simulated unique race"))
            original_flush(*args, **kwargs)

        monkeypatch.setattr(repository, "_find_request_by_idempotency", fake_find)
        monkeypatch.setattr(repository, "_find_request_by_checksum", fake_find_checksum)
        monkeypatch.setattr(session, "flush", fake_flush)
        recovered = repository.create_geometry_request(
            request,
            owner_id="owner-a",
            idempotency_key="pg-race",
        )
        session.commit()

    assert recovered.request.id == existing.request.id
    assert recovered.created is False
    assert _counts(pg_db) == (1, 0)


def test_postgres_geometry_rollback_on_compute_failure(
    pg_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_compute(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise ValidationError("postgres geometry computation failed")

    monkeypatch.setattr(persistence_service, "compute_observation_geometry", fail_compute)
    with pg_db.session() as session, pytest.raises(ValidationError):
        execute_and_persist_geometry(session=session, owner_id="owner-a", request=_request())

    assert _counts(pg_db) == (0, 0)


def test_postgres_geometry_api_lists_details_and_preserves_owner_isolation(
    pg_container: AppContainer,
) -> None:
    request_id, run_id, request_checksum, _geometry_checksum = _persist_api_fixture(
        pg_container,
        owner_id="owner-a",
        site_id="SITE-PG-A",
    )
    _persist_api_fixture(pg_container, owner_id="owner-a", site_id="SITE-PG-B")
    _persist_api_fixture(pg_container, owner_id="owner-b", site_id="SITE-PG-C")

    with _client(pg_container, "owner-a") as client:
        requests_page = client.get(f"{BASE}/requests", params={"limit": "1"})
        assert requests_page.status_code == 200
        assert requests_page.json()["total"] == 2
        assert requests_page.json()["has_next"] is True

        request_detail = client.get(f"{BASE}/requests/{request_id}")
        assert request_detail.status_code == 200
        assert request_detail.json()["request_checksum"] == request_checksum
        assert "request_json" not in request_detail.json()

        run_page = client.get(f"{BASE}/runs", params={"request_id": request_id})
        assert run_page.status_code == 200
        assert run_page.json()["total"] == 1
        assert run_page.json()["items"][0]["id"] == run_id

        run_detail = client.get(f"{BASE}/runs/{run_id}")
        assert run_detail.status_code == 200
        run_body = run_detail.json()
        assert run_body["id"] == run_id
        assert run_body["sample_count"] > 0
        assert "result_json" not in run_body
        assert "samples" not in run_body
        assert "intervals" not in run_body

        samples_page = client.get(
            f"{BASE}/runs/{run_id}/samples",
            params={"limit": "2", "offset": "1"},
        )
        assert samples_page.status_code == 200
        assert samples_page.json()["total"] == run_body["sample_count"]
        assert samples_page.json()["has_next"] is True
        assert [item["sequence_index"] for item in samples_page.json()["items"]] == [1, 2]
        assert "result_json" not in samples_page.text
        assert "tle_line1" not in samples_page.text

        intervals_page = client.get(f"{BASE}/runs/{run_id}/intervals")
        assert intervals_page.status_code == 200
        assert intervals_page.json()["total"] == run_body["interval_count"]
        assert intervals_page.json()["items"][0]["sequence_index"] == 0
        assert intervals_page.json()["items"][0]["refinement_status"] in {
            "refined",
            "sampled",
            "clipped",
            "refinement_failed",
        }
        assert "result_json" not in intervals_page.text

    with _client(pg_container, "owner-b") as client:
        request_response = client.get(f"{BASE}/requests/{request_id}")
        run_response = client.get(f"{BASE}/runs/{run_id}")
        samples_response = client.get(f"{BASE}/runs/{run_id}/samples")
        intervals_response = client.get(f"{BASE}/runs/{run_id}/intervals")
        assert request_response.status_code == 404
        assert run_response.status_code == 404
        assert samples_response.status_code == 404
        assert intervals_response.status_code == 404
        assert request_checksum not in request_response.text
        assert request_checksum not in run_response.text
        assert request_checksum not in samples_response.text
        assert request_checksum not in intervals_response.text


def test_postgres_geometry_api_tamper_maps_to_safe_error(
    pg_container: AppContainer,
) -> None:
    _request_id, run_id, _request_checksum, _geometry_checksum = _persist_api_fixture(pg_container)
    with pg_container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, run_id)
        assert row is not None
        row.geometry_checksum = "0" * 64
        session.commit()

    with _client(pg_container, "owner-a", raise_server_exceptions=False) as client:
        response = client.get(f"{BASE}/runs/{run_id}")
        samples_response = client.get(f"{BASE}/runs/{run_id}/samples")
        intervals_response = client.get(f"{BASE}/runs/{run_id}/intervals")
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert samples_response.status_code == 422
    assert samples_response.json()["code"] == "validation_error"
    assert intervals_response.status_code == 422
    assert intervals_response.json()["code"] == "validation_error"
    text = response.text.lower()
    for forbidden in ("select ", "constraint", "postgres", "traceback", "result_json"):
        assert forbidden not in text
        assert forbidden not in samples_response.text.lower()
        assert forbidden not in intervals_response.text.lower()
