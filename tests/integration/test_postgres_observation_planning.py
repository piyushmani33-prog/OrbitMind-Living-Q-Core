"""Live PostgreSQL tests for Phase 4B observation-planning persistence.

These tests rely on an already Alembic-migrated disposable PostgreSQL database. They do not call
``create_all()`` so migration defects cannot be hidden by ORM metadata.
"""

from __future__ import annotations

import datetime as dt
import os

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import IntegrityError

from orbitmind.core.errors import IdempotencyConflictError, NotFoundError, ValidationError
from orbitmind.observation_planning import (
    AuthoritativePlanningSolver,
    ObservationPlanningRequest,
    ObservationPlanningSourceMode,
    PlanningHorizon,
    PlanningResultStatus,
    execute_observation_planning,
    get_observation_planning_request,
    list_observation_planning_requests,
    list_observation_planning_runs,
    list_observation_plans,
    plan_observation_request,
)
from orbitmind.observation_planning.provenance import (
    EligibilityDeclarationMode,
    EligibilityWindow,
    EligibilityWindowSet,
    InputRightsDeclaration,
    InputRightsPermission,
    InputRightsStatus,
    InputSourceIdentity,
    PinnedInputArtifact,
    PinnedInputProvenance,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
    eligibility_window_set_checksum,
)
from orbitmind.optimization.models import (
    ConstraintSet,
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    TimeWindow,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowSetRow,
    ObservationInputProvenanceRow,
    ObservationPlanningRequestRow,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
)
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
    "observation_eligibility_windows",
    "observation_eligibility_window_sets",
    "observation_input_provenance_parents",
    "observation_input_provenance",
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


def _infeasible_request(
    *,
    owner: str = "owner-a",
    idempotency_key: str | None = "pg-infeasible",
) -> ObservationPlanningRequest:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationPlanningRequest(
        name="postgres infeasible observation planning",
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
            ObservationOpportunity(
                id="OPP-B",
                satellite_id="SAT-A",
                target_id="T1",
                window=TimeWindow(
                    start=base + dt.timedelta(minutes=10),
                    end=base + dt.timedelta(minutes=40),
                ),
                mission_value=6.0,
                duration_seconds=1800.0,
                energy_cost=1.0,
                storage_cost=1.0,
            ),
        ),
        satellites=(SatelliteResource(id="SAT-A", energy_capacity=10.0, storage_capacity=10.0),),
        targets=(ObservationTarget(id="T1"),),
        constraints=ConstraintSet(mandatory=("OPP-A", "OPP-B")),
        requested_by=owner,
        idempotency_key=idempotency_key,
    )


def _persist_result(db: Database) -> tuple[str, str, str]:
    request = _request(idempotency_key="pg-idempotent")
    result = plan_observation_request(request)
    with db.session() as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id=request.requested_by)
        run = repo.persist_planning_result(
            request_id=stored.id,
            owner_id=stored.owner_id,
            result=result,
        )
        session.commit()
        assert run.plan_id is not None
        return stored.id, run.id, run.plan_id


def _sha(label: str) -> str:
    import hashlib

    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _rights() -> InputRightsDeclaration:
    return InputRightsDeclaration(
        rights_status=InputRightsStatus.DECLARED,
        redistribution=InputRightsPermission.UNKNOWN,
        commercial_use=InputRightsPermission.UNKNOWN,
        user_responsibility="caller retains responsibility for declared input rights",
        limitations=("recorded declaration only",),
    )


def _fixture_input(label: str = "pg-fixture") -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=PinnedInputSourceType.FIXTURE,
            source_mode=PinnedInputSourceMode.FIXTURE_BACKED,
            publisher="OrbitMind",
            dataset_name="postgres-fixture-eligibility",
            dataset_version="v1",
        ),
        artifact=PinnedInputArtifact(
            artifact_id=f"{label}-artifact",
            content_checksum=_sha(label),
            media_type="application/json",
            record_count=1,
        ),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        rights=_rights(),
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _declared_input(label: str = "pg-declared") -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=PinnedInputSourceType.USER_DECLARED,
            source_mode=PinnedInputSourceMode.USER_DECLARED,
        ),
        artifact=PinnedInputArtifact(
            artifact_id=f"{label}-artifact",
            content_checksum=_sha(label),
            media_type="application/json",
            record_count=1,
        ),
        declared_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        rights=_rights(),
        verification_status=ScientificInputVerificationStatus.USER_DECLARED,
    )


def _derived_input(parent: PinnedInputProvenance) -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id="pg-derived-source",
            source_type=PinnedInputSourceType.DERIVED,
            source_mode=PinnedInputSourceMode.DERIVED_FROM_DECLARED_INPUT,
            dataset_name="pg-derived-eligibility",
            dataset_version="v1",
        ),
        artifact=PinnedInputArtifact(
            artifact_id="pg-derived-artifact",
            content_checksum=_sha("pg-derived"),
            media_type="application/json",
            record_count=1,
        ),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 5, tzinfo=dt.UTC),
        rights=_rights(),
        verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
        parent_provenance_checksums=(parent.checksum,),
    )


def _eligibility_window(
    provenance: PinnedInputProvenance,
    *,
    window_id: str = "PG-W1",
    asset_id: str = "SAT-A",
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> EligibilityWindow:
    return EligibilityWindow(
        id=window_id,
        asset_id=asset_id,
        target_id="T1",
        start=start or dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC),
        end=end or dt.datetime(2026, 6, 21, 10, 30, tzinfo=dt.UTC),
        source_provenance_checksum=provenance.checksum,
        declaration_mode=EligibilityDeclarationMode.FIXTURE_BACKED,
        eligibility_reason="postgres-fixture-candidate",
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def test_postgres_schema_is_at_head_and_tables_exist(pg_db: Database) -> None:
    head = _exec(pg_db, "SELECT version_num FROM alembic_version")[0][0]
    assert head == "j6e7f8a9b0c1"
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


def test_postgres_provenance_replay_and_owner_isolation(pg_db: Database) -> None:
    provenance = _fixture_input()
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        first = repo.create_provenance(provenance, owner_id="owner-a")
        replay = repo.create_provenance(provenance, owner_id="owner-a")
        other = repo.create_provenance(provenance, owner_id="owner-b")
        session.commit()

    assert first.id == replay.id
    assert first.id != other.id
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        assert repo.get_provenance(first.id, owner_id="owner-b") is None


def test_postgres_derived_parent_composite_fk_and_owner_scope(pg_db: Database) -> None:
    parent = _declared_input()
    derived = _derived_input(parent)
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        parent_stored = repo.create_provenance(parent, owner_id="owner-a")
        child = repo.create_provenance(derived, owner_id="owner-a")
        with pytest.raises(NotFoundError):
            repo.create_provenance(derived, owner_id="owner-b")
        session.commit()

    rows = _exec(
        pg_db,
        "SELECT parent_provenance_id FROM observation_input_provenance_parents "
        "WHERE child_provenance_id=:child_id",
        {"child_id": child.id},
    )
    assert rows == [(parent_stored.id,)]


def test_postgres_eligibility_set_persistence_and_window_uniqueness(pg_db: Database) -> None:
    provenance = _fixture_input()
    window_set = EligibilityWindowSet(
        source_provenance=provenance,
        windows=(_eligibility_window(provenance),),
    )
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        stored = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        replay = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        fetched = repo.get_eligibility_window_set(stored.id, owner_id="owner-a")
        session.commit()

    assert replay.id == stored.id
    assert fetched is not None
    assert fetched.window_set == window_set
    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO observation_eligibility_windows "
                    "(id, set_id, owner_id, window_id, asset_id, target_id, start_at, end_at, "
                    "source_provenance_checksum, declaration_mode, verification_status, "
                    "window_json, created_at) "
                    "SELECT 'duplicate-window-id', set_id, owner_id, window_id, asset_id, "
                    "target_id, start_at, end_at, source_provenance_checksum, declaration_mode, "
                    "verification_status, window_json, created_at "
                    "FROM observation_eligibility_windows WHERE set_id=:set_id"
                ),
                {"set_id": stored.id},
            )
        trans.rollback()


def test_postgres_eligibility_retrieval_uses_domain_canonical_order(pg_db: Database) -> None:
    provenance = _fixture_input("pg-ordering")
    sat_a_later = _eligibility_window(
        provenance,
        window_id="PG-SAT-A-LATE",
        asset_id="SAT-A",
        start=dt.datetime(2026, 6, 21, 11, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 6, 21, 11, 30, tzinfo=dt.UTC),
    )
    sat_b_earlier = _eligibility_window(
        provenance,
        window_id="PG-SAT-B-EARLY",
        asset_id="SAT-B",
        start=dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 6, 21, 10, 30, tzinfo=dt.UTC),
    )
    window_set = EligibilityWindowSet(
        source_provenance=provenance,
        windows=(sat_b_earlier, sat_a_later),
    )
    assert window_set.windows == (sat_a_later, sat_b_earlier)

    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        stored = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        fetched = repo.get_eligibility_window_set(stored.id, owner_id="owner-a")
        replay = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        session.commit()

    assert fetched is not None
    assert fetched.window_set == window_set
    assert fetched.eligibility_set_checksum == eligibility_window_set_checksum(window_set)
    assert fetched.window_set.windows == (sat_a_later, sat_b_earlier)
    assert replay.id == stored.id
    assert (
        _exec(
            pg_db,
            "SELECT count(*) FROM observation_eligibility_windows WHERE set_id=:set_id",
            {"set_id": stored.id},
        )[0][0]
        == 2
    )


def test_postgres_eligibility_set_rejects_cross_owner_provenance(pg_db: Database) -> None:
    provenance = _fixture_input()
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        with pytest.raises(NotFoundError):
            repo.create_eligibility_window_set(
                EligibilityWindowSet(
                    source_provenance=provenance,
                    windows=(_eligibility_window(provenance),),
                ),
                owner_id="owner-b",
            )


def test_postgres_provenance_and_eligibility_tamper_detection(pg_db: Database) -> None:
    provenance = _fixture_input()
    window_set = EligibilityWindowSet(
        source_provenance=provenance,
        windows=(_eligibility_window(provenance),),
    )
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        stored_provenance = repo.create_provenance(provenance, owner_id="owner-a")
        stored_set = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        session.commit()

    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        session.execute(
            update(ObservationInputProvenanceRow)
            .where(ObservationInputProvenanceRow.id == stored_provenance.id)
            .values(artifact_checksum=_sha("wrong"))
        )
        session.flush()
        with pytest.raises(ValidationError, match="artifact checksum"):
            repo.get_provenance(stored_provenance.id, owner_id="owner-a")
        session.rollback()

    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        session.execute(
            update(ObservationEligibilityWindowSetRow)
            .where(ObservationEligibilityWindowSetRow.id == stored_set.id)
            .values(window_count=0)
        )
        session.flush()
        with pytest.raises(ValidationError, match="window count"):
            repo.get_eligibility_window_set(stored_set.id, owner_id="owner-a")


def test_postgres_provenance_delete_restrictions(pg_db: Database) -> None:
    provenance = _fixture_input()
    window_set = EligibilityWindowSet(
        source_provenance=provenance,
        windows=(_eligibility_window(provenance),),
    )
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        stored_provenance = repo.create_provenance(provenance, owner_id="owner-a")
        stored_set = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        session.commit()

    with pg_db.engine.connect() as conn:
        trans = conn.begin()
        with pytest.raises(IntegrityError):
            conn.execute(
                text("DELETE FROM observation_input_provenance WHERE id=:id"),
                {"id": stored_provenance.id},
            )
        trans.rollback()

    assert (
        _exec(
            pg_db,
            "SELECT count(*) FROM observation_input_provenance WHERE id=:id",
            {"id": stored_provenance.id},
        )[0][0]
        == 1
    )
    assert (
        _exec(
            pg_db,
            "SELECT count(*) FROM observation_eligibility_window_sets WHERE id=:id",
            {"id": stored_set.id},
        )[0][0]
        == 1
    )


def test_postgres_owner_scoped_idempotency(pg_db: Database) -> None:
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        first = repo.create_planning_request(
            _request(owner="owner-a", idempotency_key="shared"), owner_id="owner-a"
        )
        same = repo.create_planning_request(
            _request(owner="owner-a", idempotency_key="shared"), owner_id="owner-a"
        )
        other = repo.create_planning_request(
            _request(owner="owner-b", idempotency_key="shared"), owner_id="owner-b"
        )
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
        existing = repo.create_planning_request(request, owner_id="owner-a")
        original_find = repo._find_request_by_idempotency
        calls = 0

        def racing_find(owner_id: str, idempotency_key: str) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return original_find(owner_id, idempotency_key)

        monkeypatch.setattr(repo, "_find_request_by_idempotency", racing_find)
        raced = repo.create_planning_request(request, owner_id="owner-a")
        session.commit()

    assert raced.id == existing.id
    assert calls >= 2
    rows = _exec(
        pg_db,
        "SELECT id FROM observation_planning_requests "
        "WHERE owner_id='owner-a' AND idempotency_key='pg-race'",
    )
    assert rows == [(existing.id,)]


def test_postgres_repository_idempotency_integrity_race_conflicts(
    pg_db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(idempotency_key="pg-race-conflict")
    with pg_db.session() as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        existing = repo.create_planning_request(request, owner_id="owner-a")
        original_find = repo._find_request_by_idempotency
        calls = 0

        def racing_find(owner_id: str, idempotency_key: str) -> object:
            nonlocal calls
            calls += 1
            if calls == 1:
                return None
            return original_find(owner_id, idempotency_key)

        monkeypatch.setattr(repo, "_find_request_by_idempotency", racing_find)
        with pytest.raises(IdempotencyConflictError, match="different request"):
            repo.create_planning_request(
                request.model_copy(update={"name": "different race request"}),
                owner_id="owner-a",
            )
        session.commit()

    assert calls >= 2
    rows = _exec(
        pg_db,
        "SELECT id FROM observation_planning_requests "
        "WHERE owner_id='owner-a' AND idempotency_key='pg-race-conflict'",
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


def test_postgres_query_owner_isolation_ordering_and_pagination(pg_db: Database) -> None:
    with pg_db.session() as session:
        first = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(idempotency_key="query-a1"),
        )
        execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(idempotency_key="query-a2"),
        )
        execute_observation_planning(
            session=session,
            owner_id="owner-b",
            request=_request(owner="owner-b", idempotency_key="query-b1"),
        )
        page = list_observation_planning_requests(session, owner_id="owner-a", limit=1)
        second_page = list_observation_planning_requests(
            session, owner_id="owner-a", limit=1, offset=1
        )
        runs = list_observation_planning_runs(session, owner_id="owner-a")
        plans = list_observation_plans(session, owner_id="owner-a")
        session.commit()

    assert page.total == 2
    assert page.has_next is True
    assert page.items[0].owner_id == "owner-a"
    assert second_page.items[0].id != page.items[0].id
    assert {item.owner_id for item in runs.items} == {"owner-a"}
    assert {item.owner_id for item in plans.items} == {"owner-a"}
    assert first.request_id in {page.items[0].id, second_page.items[0].id}


def test_postgres_query_filters_and_non_success_runs(pg_db: Database) -> None:
    infeasible_request = _infeasible_request()
    infeasible = plan_observation_request(infeasible_request)
    with pg_db.session() as session:
        execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(idempotency_key="query-success"),
        )
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(infeasible_request, owner_id="owner-a")
        repo.persist_planning_result(
            request_id=stored.id,
            owner_id=stored.owner_id,
            result=infeasible,
        )
        successful = list_observation_planning_runs(session, owner_id="owner-a", feasible_only=True)
        non_success = list_observation_planning_runs(
            session,
            owner_id="owner-a",
            status=PlanningResultStatus.INFEASIBLE,
        )
        exact = list_observation_planning_runs(
            session,
            owner_id="owner-a",
            authoritative_solver=AuthoritativePlanningSolver.EXACT,
        )
        declared = list_observation_planning_requests(
            session,
            owner_id="owner-a",
            source_mode=ObservationPlanningSourceMode.DECLARED,
        )
        plans = list_observation_plans(session, owner_id="owner-a")
        session.commit()

    assert len(successful.items) == 1
    assert len(non_success.items) == 1
    assert non_success.items[0].plan_id is None
    assert len(exact.items) == 2
    assert len(declared.items) == 2
    assert len(plans.items) == 1


def test_postgres_query_tamper_detection(pg_db: Database) -> None:
    with pg_db.session() as session:
        execution = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(idempotency_key="query-tamper"),
        )
        row = session.get(ObservationPlanningRequestRow, execution.request_id)
        assert row is not None
        tampered = dict(row.request_json)
        tampered["name"] = "tampered"
        session.execute(
            update(ObservationPlanningRequestRow)
            .where(ObservationPlanningRequestRow.id == execution.request_id)
            .values(request_json=tampered)
        )
        session.flush()

        with pytest.raises(ValidationError, match="checksum"):
            get_observation_planning_request(
                session, owner_id="owner-a", request_id=execution.request_id
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
        stored = repo.create_planning_request(
            _request(idempotency_key="duplicate-key"), owner_id="owner-a"
        )
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
