"""Live PostgreSQL tests for Phase 4B observation-planning persistence.

These tests rely on an already Alembic-migrated disposable PostgreSQL database. They do not call
``create_all()`` so migration defects cannot be hidden by ORM metadata.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from orbitmind.core.errors import ValidationError
from orbitmind.observation_planning import (
    ObservationPlanningRequest,
    ObservationPlanningSourceMode,
    PlanningHorizon,
    execute_observation_planning,
    plan_observation_request,
)
from orbitmind.optimization.models import (
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    TimeWindow,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_planning_repository import (
    SqlAlchemyObservationPlanningRepository,
)

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

_TABLES = (
    "observation_plans",
    "observation_planning_runs",
    "observation_planning_requests",
)


@pytest.fixture
def pg_db() -> Database:
    """A migrated PostgreSQL DB. Do not call create_all()."""

    assert _PG_URL is not None
    db = Database(_PG_URL)
    assert db.is_postgres
    with db.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield db
    db.engine.dispose()


def _exec(db: Database, sql: str, params: dict[str, object] | None = None) -> list:
    with db.engine.connect() as conn:
        return list(conn.execute(text(sql), params or {}))


def _horizon() -> PlanningHorizon:
    return PlanningHorizon(
        start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
    )


def _request(
    *,
    owner: str = "owner-a",
    idempotency_key: str | None = None,
) -> ObservationPlanningRequest:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationPlanningRequest(
        name="postgres declared observation planning",
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=(
            ObservationOpportunity(
                id="OPP-A",
                satellite_id="SAT-A",
                target_id="T1",
                window=TimeWindow(start=base, end=base + dt.timedelta(minutes=30)),
                mission_value=5.0,
                duration_seconds=1800.0,
                energy_cost=1.0,
                storage_cost=1.0,
            ),
        ),
        satellites=(SatelliteResource(id="SAT-A", energy_capacity=10.0, storage_capacity=10.0),),
        targets=(ObservationTarget(id="T1"),),
        requested_by=owner,
        idempotency_key=idempotency_key,
    )


def _invalid_reference_request(
    *,
    owner: str = "owner-a",
    idempotency_key: str | None = "pg-invalid",
) -> ObservationPlanningRequest:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationPlanningRequest(
        name="postgres invalid reference request",
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=(
            ObservationOpportunity(
                id="OPP-BAD",
                satellite_id="SAT-MISSING",
                target_id="T1",
                window=TimeWindow(start=base, end=base + dt.timedelta(minutes=30)),
                mission_value=5.0,
                duration_seconds=1800.0,
                energy_cost=1.0,
                storage_cost=1.0,
            ),
        ),
        satellites=(SatelliteResource(id="SAT-A", energy_capacity=10.0, storage_capacity=10.0),),
        targets=(ObservationTarget(id="T1"),),
        requested_by=owner,
        idempotency_key=idempotency_key,
    )


def _persist_result(db: Database) -> tuple[str, str, str]:
    request = _request(idempotency_key="pg-idempotent")
    result = plan_observation_request(request)
    with db.session() as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request)
        run = repo.persist_planning_result(
            request_id=stored.id,
            owner_id=stored.owner_id,
            result=result,
        )
        session.commit()
        assert run.plan_id is not None
        return stored.id, run.id, run.plan_id


def test_postgres_schema_is_at_head_and_tables_exist(pg_db: Database) -> None:
    head = _exec(pg_db, "SELECT version_num FROM alembic_version")[0][0]
    assert head == "i5d6e7f8a9b0"
    present = {
        r[0]
        for r in _exec(
            pg_db,
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
        )
    }
    assert set(_TABLES) <= present


def test_postgres_observation_planning_constraints_are_named(pg_db: Database) -> None:
    constraints = {
        r[0]
        for r in _exec(
            pg_db,
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_schema='public' AND table_name IN "
            "('observation_planning_requests','observation_planning_runs','observation_plans')",
        )
    }
    assert "uq_observation_planning_request_idempotency" in constraints
    assert "fk_op_runs_request_owner" in constraints
    assert "fk_observation_plans_run_owner" in constraints
    assert "ck_op_runs_authoritative_solver" in constraints
    assert "ck_op_runs_status_feasible" in constraints


def test_postgres_owner_scoped_idempotency(pg_db: Database) -> None:
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        first = repo.create_planning_request(_request(owner="owner-a", idempotency_key="shared"))
        same = repo.create_planning_request(_request(owner="owner-a", idempotency_key="shared"))
        other = repo.create_planning_request(_request(owner="owner-b", idempotency_key="shared"))
        session.commit()

    assert first.id == same.id
    assert first.id != other.id


def test_postgres_orchestration_reuses_request_and_run(pg_db: Database) -> None:
    with pg_db.session() as session:
        first = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(idempotency_key="orchestrated"),
        )
        second = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(idempotency_key="orchestrated"),
        )
        session.commit()

    assert first.request_created is True
    assert first.run_created is True
    assert first.plan_created is True
    assert second.request_id == first.request_id
    assert second.run_id == first.run_id
    assert second.plan_id == first.plan_id
    assert second.request_created is False
    assert second.run_created is False
    assert second.plan_created is False


def test_postgres_orchestration_invalid_result_rolls_back_new_request(pg_db: Database) -> None:
    with pg_db.session() as session:
        with pytest.raises(ValidationError, match="not persistable"):
            execute_observation_planning(
                session=session,
                owner_id="owner-a",
                request=_invalid_reference_request(),
            )
        session.commit()

    assert _exec(pg_db, "SELECT count(*) FROM observation_planning_requests")[0][0] == 0
    assert _exec(pg_db, "SELECT count(*) FROM observation_planning_runs")[0][0] == 0
    assert _exec(pg_db, "SELECT count(*) FROM observation_plans")[0][0] == 0


def test_postgres_repository_idempotency_integrity_race_recovers(
    pg_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(idempotency_key="pg-race")
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        existing = repo.create_planning_request(request)
        original_find = repo._find_request_by_idempotency
        calls = 0

        def racing_find(owner_id: str, idempotency_key: str) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return original_find(owner_id, idempotency_key)

        monkeypatch.setattr(repo, "_find_request_by_idempotency", racing_find)
        raced = repo.create_planning_request(request)
        session.commit()

    assert raced.id == existing.id
    assert calls >= 2
    rows = _exec(
        pg_db,
        "SELECT id FROM observation_planning_requests "
        "WHERE owner_id='owner-a' AND idempotency_key='pg-race'",
    )
    assert rows == [(existing.id,)]


def test_postgres_deleting_request_with_dependent_run_is_restricted(pg_db: Database) -> None:
    request_id, run_id, plan_id = _persist_result(pg_db)
    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("DELETE FROM observation_planning_requests WHERE id=:request_id"),
                {"request_id": request_id},
            )
        trans.rollback()

    assert (
        _exec(
            pg_db,
            "SELECT count(*) FROM observation_planning_requests WHERE id=:request_id",
            {"request_id": request_id},
        )[0][0]
        == 1
    )
    assert (
        _exec(
            pg_db,
            "SELECT count(*) FROM observation_planning_runs WHERE id=:run_id",
            {"run_id": run_id},
        )[0][0]
        == 1
    )
    assert (
        _exec(
            pg_db,
            "SELECT count(*) FROM observation_plans WHERE id=:plan_id",
            {"plan_id": plan_id},
        )[0][0]
        == 1
    )


def test_postgres_owner_composite_fk_rejects_run_reassignment(pg_db: Database) -> None:
    _, run_id, _ = _persist_result(pg_db)
    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("UPDATE observation_planning_runs SET owner_id='owner-b' WHERE id=:run_id"),
                {"run_id": run_id},
            )
        trans.rollback()
    assert _exec(pg_db, "SELECT 1")[0][0] == 1


def test_postgres_owner_composite_fk_rejects_plan_reassignment(pg_db: Database) -> None:
    _, _, plan_id = _persist_result(pg_db)
    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("UPDATE observation_plans SET owner_id='owner-b' WHERE id=:plan_id"),
                {"plan_id": plan_id},
            )
        trans.rollback()
    assert _exec(pg_db, "SELECT 1")[0][0] == 1


@pytest.mark.parametrize("bad_solver", ["quantum-qaoa", "bogus", "", "EXACT"])
def test_postgres_rejects_non_classical_authoritative_solver(
    pg_db: Database, bad_solver: str
) -> None:
    _, run_id, _ = _persist_result(pg_db)
    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "UPDATE observation_planning_runs "
                    "SET authoritative_solver=:solver WHERE id=:run_id"
                ),
                {"solver": bad_solver, "run_id": run_id},
            )
        trans.rollback()
    assert _exec(pg_db, "SELECT 1")[0][0] == 1


def test_postgres_rejects_duplicate_request_idempotency_row(pg_db: Database) -> None:
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(_request(idempotency_key="duplicate-key"))
        session.commit()
    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO observation_planning_requests "
                    "(id, owner_id, request_checksum, source_mode, request_schema_version, "
                    "request_json, idempotency_key, created_at) "
                    "SELECT 'duplicate-request-id', owner_id, request_checksum, source_mode, "
                    "request_schema_version, request_json, idempotency_key, created_at "
                    "FROM observation_planning_requests WHERE id=:request_id"
                ),
                {"request_id": stored.id},
            )
        trans.rollback()
    assert _exec(pg_db, "SELECT 1")[0][0] == 1
