"""Persistence tests for Phase 4C observation-geometry requests and runs."""

from __future__ import annotations

import ast
import copy
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError

import orbitmind.persistence.observation_geometry_models  # noqa: F401 - register metadata
from orbitmind.core.errors import IdempotencyConflictError, ValidationError
from orbitmind.observation_geometry import persistence_service
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GeometrySampleStatus,
    GeometryVerificationResult,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_geometry.service import compute_observation_geometry
from orbitmind.persistence.database import Base, Database
from orbitmind.persistence.observation_geometry_models import (
    ObservationGeometryRequestRow,
    ObservationGeometryRunRow,
)
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
    StoredObservationGeometryRun,
)
from orbitmind.sources.registry import SourceRegistry

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC)


@pytest.fixture()
def sqlite_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'geometry.db').as_posix()}")

    @event.listens_for(db.engine, "connect")
    def _enable_fk(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(db.engine)
    return db


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _site(site_id: str = "SITE-001") -> GroundObservationSite:
    return GroundObservationSite(
        site_id=site_id,
        name="Equator test site",
        position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
    )


def _request(
    *,
    site_id: str = "SITE-001",
    start: dt.datetime = START,
    end: dt.datetime = START + dt.timedelta(minutes=25),
    step_seconds: int = 300,
    minimum_elevation_deg: float = 0.0,
) -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=_site(site_id),
        start=start,
        end=end,
        step_seconds=step_seconds,
        minimum_elevation_deg=minimum_elevation_deg,
    )


def _persist_run(
    db: Database,
    request: GeometryComputationRequest | None = None,
    *,
    owner_id: str = "owner-a",
) -> tuple[str, str, GeometryComputationResult]:
    geometry_request = request or _request()
    result = compute_observation_geometry(geometry_request)
    with db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        request_write = repository.create_geometry_request(geometry_request, owner_id=owner_id)
        run_write = repository.persist_geometry_result(
            request_id=request_write.request.id,
            owner_id=owner_id,
            result=result,
        )
        session.commit()
        return request_write.request.id, run_write.run.id, result


def _row_counts(db: Database) -> tuple[int, int]:
    with db.session() as session:
        request_count = session.scalar(
            select(func.count()).select_from(ObservationGeometryRequestRow)
        )
        run_count = session.scalar(select(func.count()).select_from(ObservationGeometryRunRow))
    return int(request_count or 0), int(run_count or 0)


def test_request_and_completed_run_persistence_round_trip(sqlite_db: Database) -> None:
    geometry_request = _request()
    result = compute_observation_geometry(geometry_request)
    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        request_write = repository.create_geometry_request(
            geometry_request,
            owner_id="owner-a",
            idempotency_key="geometry-key",
        )
        run_write = repository.persist_geometry_result(
            request_id=request_write.request.id,
            owner_id="owner-a",
            result=result,
        )
        session.commit()
        request_id = request_write.request.id
        run_id = run_write.run.id

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        stored_request = repository.get_geometry_request(request_id, owner_id="owner-a")
        stored_run = repository.get_geometry_run(run_id, owner_id="owner-a")
        row = session.get(ObservationGeometryRunRow, run_id)

    assert stored_request is not None
    assert stored_request.request == geometry_request
    assert stored_request.request_checksum == geometry_request.request_checksum
    assert stored_request.idempotency_key == "geometry-key"
    assert isinstance(stored_run, StoredObservationGeometryRun)
    assert stored_run.result == result
    assert row is not None
    assert "samples" in row.result_json
    assert "intervals" in row.result_json
    assert row.sample_count == len(row.result_json["samples"])
    assert row.interval_count == len(row.result_json["intervals"])
    with pytest.raises(PydanticValidationError):
        stored_run.id = "changed"  # type: ignore[misc]


def test_failed_samples_are_preserved_in_result_json(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_all(*_args: object, **_kwargs: object) -> tuple[int, None]:
        return (6, None)

    monkeypatch.setattr("orbitmind.observation_geometry.service._sgp4_position_km", fail_all)
    geometry_request = _request(end=START + dt.timedelta(minutes=5))
    result = compute_observation_geometry(geometry_request)
    assert result.failed_sample_count == result.sample_count
    request_id, run_id, _ = _persist_run(sqlite_db, geometry_request)

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        stored = repository.get_geometry_run(run_id, owner_id="owner-a")
        row = session.get(ObservationGeometryRunRow, run_id)

    assert stored is not None
    assert stored.request_id == request_id
    assert row is not None
    assert row.result_json["samples"][0]["status"] == GeometrySampleStatus.ERROR.value
    assert row.result_json["samples"][0]["safe_error_code"] == "sgp4_status_6"


def test_execute_replays_without_recomputation(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry_request = _request()
    with sqlite_db.session() as session:
        first = execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=geometry_request,
            idempotency_key="same-request",
        )

    def fail_if_called(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise AssertionError("geometry should not be recomputed on exact replay")

    monkeypatch.setattr(persistence_service, "compute_observation_geometry", fail_if_called)
    with sqlite_db.session() as session:
        second = execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=geometry_request,
            idempotency_key="same-request",
        )

    assert first.request_id == second.request_id
    assert first.run_id == second.run_id
    assert second.request_created is False
    assert second.run_created is False


def test_idempotency_conflict_happens_before_computation(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with sqlite_db.session() as session:
        execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=_request(),
            idempotency_key="conflict-key",
        )
    called = False

    def mark_called(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        nonlocal called
        called = True
        raise AssertionError("conflict should be detected before computation")

    monkeypatch.setattr(persistence_service, "compute_observation_geometry", mark_called)
    with sqlite_db.session() as session, pytest.raises(IdempotencyConflictError):
        execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=_request(site_id="SITE-002"),
            idempotency_key="conflict-key",
        )
    assert called is False
    assert _row_counts(sqlite_db) == (1, 1)


def test_owner_isolation_and_same_checksum_for_different_owners(sqlite_db: Database) -> None:
    geometry_request = _request()
    with sqlite_db.session() as session:
        first = execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=geometry_request,
        )
    with sqlite_db.session() as session:
        second = execute_and_persist_geometry(
            session=session,
            owner_id="owner-b",
            request=geometry_request,
        )
    assert first.request_checksum == second.request_checksum
    assert first.request_id != second.request_id
    assert first.run_id != second.run_id

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        assert repository.get_geometry_request(first.request_id, owner_id="owner-b") is None
        owner_b = repository.get_geometry_request_by_checksum(
            owner_id="owner-b",
            request_checksum=geometry_request.request_checksum,
        )
    assert owner_b is not None
    assert owner_b.id == second.request_id


def test_cross_owner_composite_fk_rejects_run(sqlite_db: Database) -> None:
    geometry_request = _request()
    result = compute_observation_geometry(geometry_request)
    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        request_write = repository.create_geometry_request(geometry_request, owner_id="owner-a")
        bad_run = ObservationGeometryRunRow(
            id="bad-run",
            owner_id="owner-b",
            request_id=request_write.request.id,
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


@pytest.mark.parametrize(
    "mutation",
    [
        "request_snapshot",
        "request_checksum",
        "request_schema",
        "element_checksum",
        "source_checksum",
        "site_id",
        "start_at",
        "step_seconds",
        "minimum_elevation",
    ],
)
def test_request_tamper_detection(sqlite_db: Database, mutation: str) -> None:
    request_id, _run_id, _result = _persist_run(sqlite_db)
    with sqlite_db.session() as session:
        row = session.get(ObservationGeometryRequestRow, request_id)
        assert row is not None
        if mutation == "request_snapshot":
            payload = copy.deepcopy(row.request_json)
            payload["site"]["site_id"] = "TAMPERED"
            row.request_json = payload
        elif mutation == "request_checksum":
            row.request_checksum = "0" * 64
        elif mutation == "request_schema":
            payload = copy.deepcopy(row.request_json)
            payload["schema_version"] = "2"
            row.request_json = payload
        elif mutation == "element_checksum":
            row.element_checksum = "0" * 64
        elif mutation == "source_checksum":
            row.source_identity_checksum = "0" * 64
        elif mutation == "site_id":
            row.site_id = "TAMPERED"
        elif mutation == "start_at":
            row.start_at = row.start_at + dt.timedelta(seconds=1)
        elif mutation == "step_seconds":
            row.step_seconds = row.step_seconds + 1
        elif mutation == "minimum_elevation":
            row.minimum_elevation_deg = row.minimum_elevation_deg + 1.0
        session.commit()

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        with pytest.raises(ValidationError):
            repository.get_geometry_request(request_id, owner_id="owner-a")


@pytest.mark.parametrize(
    "mutation",
    [
        "sample_content",
        "interval_content",
        "geometry_checksum",
        "request_checksum",
        "element_checksum",
        "source_checksum",
        "sample_count",
        "failed_sample_count",
        "interval_count",
        "schema_version",
        "computation_version",
        "epistemic_status",
        "limitations",
    ],
)
def test_run_tamper_detection(sqlite_db: Database, mutation: str) -> None:
    _request_id, run_id, _result = _persist_run(sqlite_db)
    with sqlite_db.session() as session:
        row = session.get(ObservationGeometryRunRow, run_id)
        assert row is not None
        if mutation == "sample_content":
            payload = copy.deepcopy(row.result_json)
            payload["samples"][0]["azimuth_deg"] = 42.123456
            row.result_json = payload
        elif mutation == "interval_content":
            payload = copy.deepcopy(row.result_json)
            payload["intervals"][0]["peak_elevation_deg"] = -1.0
            row.result_json = payload
        elif mutation == "geometry_checksum":
            row.geometry_checksum = "0" * 64
        elif mutation == "request_checksum":
            row.request_checksum = "0" * 64
        elif mutation == "element_checksum":
            row.element_checksum = "0" * 64
        elif mutation == "source_checksum":
            row.source_identity_checksum = "0" * 64
        elif mutation == "sample_count":
            row.sample_count = row.sample_count + 1
        elif mutation == "failed_sample_count":
            row.failed_sample_count = row.failed_sample_count + 1
        elif mutation == "interval_count":
            row.interval_count = row.interval_count + 1
        elif mutation == "schema_version":
            payload = copy.deepcopy(row.result_json)
            payload["schema_version"] = "2"
            row.result_json = payload
        elif mutation == "computation_version":
            payload = copy.deepcopy(row.result_json)
            payload["computation_version"] = "tampered"
            row.result_json = payload
        elif mutation == "epistemic_status":
            payload = copy.deepcopy(row.result_json)
            payload["epistemic_status"] = "assumption"
            row.result_json = payload
        elif mutation == "limitations":
            row.limitations_json = ["tampered limitation"]
        session.commit()

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        with pytest.raises(ValidationError):
            repository.get_geometry_run(run_id, owner_id="owner-a")


def test_relationship_tamper_detection(sqlite_db: Database) -> None:
    first_request = _request()
    second_request = _request(site_id="SITE-002")
    request_id, run_id, _result = _persist_run(sqlite_db, first_request)
    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        other = repository.create_geometry_request(second_request, owner_id="owner-a")
        row = session.get(ObservationGeometryRunRow, run_id)
        assert row is not None
        assert request_id != other.request.id
        row.request_id = other.request.id
        session.commit()

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        with pytest.raises(ValidationError):
            repository.get_geometry_run(run_id, owner_id="owner-a")


def test_request_race_recovery_returns_existing_matching_request(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry_request = _request()
    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        existing = repository.create_geometry_request(
            geometry_request,
            owner_id="owner-a",
            idempotency_key="race-key",
        )
        session.commit()

    with sqlite_db.session() as session:
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

        def fake_flush(*args: Any, **kwargs: Any) -> None:
            inserting_request = any(
                isinstance(obj, ObservationGeometryRequestRow) for obj in session.new
            )
            if calls["flush"] == 0 and inserting_request:
                calls["flush"] += 1
                raise IntegrityError("insert", {}, Exception("unique"))
            original_flush(*args, **kwargs)

        monkeypatch.setattr(repository, "_find_request_by_idempotency", fake_find)
        monkeypatch.setattr(repository, "_find_request_by_checksum", fake_find_checksum)
        monkeypatch.setattr(session, "flush", fake_flush)
        recovered = repository.create_geometry_request(
            geometry_request,
            owner_id="owner-a",
            idempotency_key="race-key",
        )

    assert recovered.request.id == existing.request.id
    assert recovered.created is False


def test_unexpected_request_integrity_error_propagates(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        monkeypatch.setattr(
            session,
            "flush",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                IntegrityError("insert", {}, Exception("not idempotency"))
            ),
        )
        with pytest.raises(IntegrityError):
            repository.create_geometry_request(_request(), owner_id="owner-a")


def test_application_rolls_back_on_computation_failure(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_compute(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise ValidationError("bounded geometry computation failed")

    monkeypatch.setattr(persistence_service, "compute_observation_geometry", fail_compute)
    with sqlite_db.session() as session, pytest.raises(ValidationError):
        execute_and_persist_geometry(session=session, owner_id="owner-a", request=_request())
    assert _row_counts(sqlite_db) == (0, 0)


def test_application_rolls_back_on_verification_failure(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_verify(*_args: object, **_kwargs: object) -> GeometryVerificationResult:
        return GeometryVerificationResult(passed=False, checks=(), recomputed_checksum=None)

    monkeypatch.setattr(persistence_service, "verify_geometry_result", fail_verify)
    with sqlite_db.session() as session, pytest.raises(ValidationError):
        execute_and_persist_geometry(session=session, owner_id="owner-a", request=_request())
    assert _row_counts(sqlite_db) == (0, 0)


def test_application_rolls_back_on_run_insertion_failure(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_persist(*_args: object, **_kwargs: object) -> object:
        raise ValidationError("run insertion failed")

    monkeypatch.setattr(
        SqlAlchemyObservationGeometryRepository,
        "persist_geometry_result",
        fail_persist,
    )
    with sqlite_db.session() as session, pytest.raises(ValidationError):
        execute_and_persist_geometry(session=session, owner_id="owner-a", request=_request())
    assert _row_counts(sqlite_db) == (0, 0)


def test_restrictive_deletion(sqlite_db: Database) -> None:
    request_id, run_id, _result = _persist_run(sqlite_db)
    with sqlite_db.session() as session:
        request_row = session.get(ObservationGeometryRequestRow, request_id)
        assert request_row is not None
        session.delete(request_row)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        assert repository.get_geometry_request(request_id, owner_id="owner-a") is not None
        assert repository.get_geometry_run(run_id, owner_id="owner-a") is not None


def test_service_rejects_non_fresh_session(sqlite_db: Database) -> None:
    with sqlite_db.session() as session:
        session.execute(select(func.count()).select_from(ObservationGeometryRequestRow))
        with pytest.raises(ValidationError, match="fresh session"):
            execute_and_persist_geometry(session=session, owner_id="owner-a", request=_request())


def test_no_forbidden_architecture_imports() -> None:
    files = (
        Path("src/orbitmind/observation_geometry/persistence_service.py"),
        Path("src/orbitmind/persistence/observation_geometry_models.py"),
        Path("src/orbitmind/persistence/observation_geometry_repository.py"),
    )
    forbidden_prefixes = (
        "orbitmind.api",
        "orbitmind.observation_planning",
        "orbitmind.quantum",
        "httpx",
        "requests",
    )
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = _imported_module(node)
            if module is not None:
                assert not module.startswith(forbidden_prefixes), (path, module)


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None
