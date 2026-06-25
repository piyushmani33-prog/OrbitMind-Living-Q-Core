"""Phase 4B.1 transactional observation-planning orchestration tests."""

from __future__ import annotations

import builtins
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import orbitmind.observation_planning.orchestration as orchestration
import orbitmind.persistence.observation_planning_repository as op_repo_module
from orbitmind.core.errors import IdempotencyConflictError, ValidationError
from orbitmind.observation_planning import (
    ObservationPlanningRequest,
    ObservationPlanningSourceMode,
    PersistedObservationPlanningExecution,
    PlanningHorizon,
    PlanningResultStatus,
    execute_observation_planning,
)
from orbitmind.optimization.models import (
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    TimeWindow,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_planning_models import (
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
    ObservationPlanRow,
)
from orbitmind.persistence.observation_planning_repository import (
    SqlAlchemyObservationPlanningRepository,
    scientific_identity_checksum,
)


def _db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'planning-orchestration.db').as_posix()}")
    db.create_all()
    return db


def _session(tmp_path: Path) -> Session:
    return _db(tmp_path).session()


def _horizon() -> PlanningHorizon:
    return PlanningHorizon(
        start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
    )


def _request(
    *,
    name: str = "declared orchestration request",
    owner: str = "owner-a",
    idempotency_key: str | None = "idem-a",
) -> ObservationPlanningRequest:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationPlanningRequest(
        name=name,
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
    idempotency_key: str | None = "invalid-ref",
) -> ObservationPlanningRequest:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationPlanningRequest(
        name="declared request with invalid satellite reference",
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


def _count(session: Session, row_type: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(row_type)) or 0)


def test_execute_observation_planning_persists_request_run_and_plan(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        execution = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(),
        )

        assert isinstance(execution, PersistedObservationPlanningExecution)
        assert execution.owner_id == "owner-a"
        assert execution.request_created is True
        assert execution.run_created is True
        assert execution.plan_created is True
        assert execution.plan_id is not None
        assert execution.final_status == PlanningResultStatus.VERIFIED_FEASIBLE
        assert execution.feasible is True
        assert execution.request_checksum == execution.result.request_checksum
        assert execution.problem_checksum == execution.result.problem_checksum
        assert execution.scientific_identity_checksum == scientific_identity_checksum(
            execution.result.scientific_identity
        )
        assert _count(session, ObservationPlanningRequestRow) == 1
        assert _count(session, ObservationPlanningRunRow) == 1
        assert _count(session, ObservationPlanRow) == 1


def test_same_owner_same_key_same_request_reuses_request_run_and_plan(
    tmp_path: Path,
) -> None:
    request = _request()
    with _session(tmp_path) as session:
        first = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=request,
        )
        second = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=request,
        )

        assert first.request_id == second.request_id
        assert first.run_id == second.run_id
        assert first.plan_id == second.plan_id
        assert second.request_created is False
        assert second.run_created is False
        assert second.plan_created is False
        assert _count(session, ObservationPlanningRequestRow) == 1
        assert _count(session, ObservationPlanningRunRow) == 1
        assert _count(session, ObservationPlanRow) == 1


def test_same_owner_same_key_different_request_conflicts_before_solver(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def forbidden_planner(request: ObservationPlanningRequest) -> Any:
        calls.append(request.name)
        raise AssertionError("planner should not run after idempotency conflict")

    with _session(tmp_path) as session:
        execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(),
        )
        monkeypatch.setattr(orchestration, "plan_observation_request", forbidden_planner)

        with pytest.raises(IdempotencyConflictError, match="different request"):
            execute_observation_planning(
                session=session,
                owner_id="owner-a",
                request=_request(name="different scientific request"),
            )

        assert calls == []
        assert _count(session, ObservationPlanningRequestRow) == 1
        assert _count(session, ObservationPlanningRunRow) == 1
        assert _count(session, ObservationPlanRow) == 1


def test_different_owner_same_key_is_independent(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        first = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(owner="owner-a"),
        )
        second = execute_observation_planning(
            session=session,
            owner_id="owner-b",
            request=_request(owner="owner-b"),
        )

        assert first.request_id != second.request_id
        assert first.run_id != second.run_id
        assert second.request_created is True
        assert second.run_created is True
        assert _count(session, ObservationPlanningRequestRow) == 2


def test_explicit_idempotency_key_is_applied_without_changing_checksum(
    tmp_path: Path,
) -> None:
    request = _request(idempotency_key=None)
    with _session(tmp_path) as session:
        execution = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=request,
            idempotency_key="explicit-key",
        )
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.get_planning_request(execution.request_id, owner_id="owner-a")

    assert stored is not None
    assert stored.idempotency_key == "explicit-key"
    assert (
        execution.request_checksum
        == orchestration.plan_observation_request(
            request.model_copy(update={"idempotency_key": "explicit-key"})
        ).request_checksum
    )


def test_conflicting_explicit_idempotency_key_is_rejected_before_persistence(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        with pytest.raises(ValidationError, match="conflicting"):
            execute_observation_planning(
                session=session,
                owner_id="owner-a",
                request=_request(idempotency_key="inside"),
                idempotency_key="outside",
            )
        assert _count(session, ObservationPlanningRequestRow) == 0


@pytest.mark.parametrize("owner_id", ["", "   ", " padded "])
def test_invalid_owner_is_rejected_before_planning(tmp_path: Path, owner_id: str) -> None:
    with _session(tmp_path) as session:
        with pytest.raises(ValidationError, match="owner_id"):
            execute_observation_planning(
                session=session,
                owner_id=owner_id,
                request=_request(),
            )
        assert _count(session, ObservationPlanningRequestRow) == 0


def test_owner_id_is_database_authority_not_request_provenance(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        execution = execute_observation_planning(
            session=session,
            owner_id="owner-db",
            request=_request(owner="owner-provenance"),
        )

        assert execution.owner_id == "owner-db"
        assert _count(session, ObservationPlanningRequestRow) == 1
        stored = session.get(ObservationPlanningRequestRow, execution.request_id)
        assert stored is not None
        assert stored.owner_id == "owner-db"


def test_invalid_translation_result_is_typed_rejected_and_rolls_back_new_request(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        with pytest.raises(ValidationError, match="not persistable"):
            execute_observation_planning(
                session=session,
                owner_id="owner-a",
                request=_invalid_reference_request(),
            )

        assert _count(session, ObservationPlanningRequestRow) == 0
        assert _count(session, ObservationPlanningRunRow) == 0
        assert _count(session, ObservationPlanRow) == 0
        assert int(session.scalar(select(1)) or 0) == 1


def test_preexisting_idempotent_request_survives_later_invalid_execution(
    tmp_path: Path,
) -> None:
    request = _invalid_reference_request(idempotency_key="invalid-reuse")
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id="owner-a")
        session.commit()

        with pytest.raises(ValidationError, match="not persistable"):
            execute_observation_planning(
                session=session,
                owner_id="owner-a",
                request=request,
            )

        assert repo.get_planning_request(stored.id, owner_id="owner-a") is not None
        assert _count(session, ObservationPlanningRequestRow) == 1
        assert _count(session, ObservationPlanningRunRow) == 0
        assert _count(session, ObservationPlanRow) == 0


def test_direct_repository_rejects_invalid_and_empty_problem_checksum_before_insert(
    tmp_path: Path,
) -> None:
    request = _invalid_reference_request(idempotency_key="direct-invalid")
    invalid_result = orchestration.plan_observation_request(request)
    empty_checksum_result = invalid_result.model_copy(
        update={"status": PlanningResultStatus.FAILED}
    )
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id="owner-a")

        with pytest.raises(ValidationError, match="not persistable"):
            repo.persist_planning_result(
                request_id=stored.id,
                owner_id=stored.owner_id,
                result=invalid_result,
            )
        with pytest.raises(ValidationError, match="problem checksum"):
            repo.persist_planning_result(
                request_id=stored.id,
                owner_id=stored.owner_id,
                result=empty_checksum_result,
            )

        assert _count(session, ObservationPlanningRunRow) == 0
        assert _count(session, ObservationPlanRow) == 0
        assert int(session.scalar(select(1)) or 0) == 1


def test_repository_idempotency_race_requeries_existing_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(idempotency_key="race-key")
    with _session(tmp_path) as session:
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

        assert raced.id == existing.id
        assert calls >= 2
        assert _count(session, ObservationPlanningRequestRow) == 1


def test_repository_idempotency_race_rejects_different_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = _request(idempotency_key="race-conflict")
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        repo.create_planning_request(request, owner_id="owner-a")
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
                _request(name="different race request", idempotency_key="race-conflict"),
                owner_id="owner-a",
            )

        assert calls >= 2
        assert _count(session, ObservationPlanningRequestRow) == 1


def test_unexpected_request_integrity_error_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        existing = repo.create_planning_request(_request(idempotency_key=None), owner_id="owner-a")
        session.commit()
        monkeypatch.setattr(op_repo_module, "new_id", lambda: existing.id)

        with pytest.raises(IntegrityError):
            repo.create_planning_request(
                _request(name="duplicate id", idempotency_key=None), owner_id="owner-a"
            )

        session.rollback()
        assert _count(session, ObservationPlanningRequestRow) == 1


def test_active_transaction_is_rejected(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        transaction = session.begin()
        try:
            with pytest.raises(ValidationError, match="fresh session"):
                execute_observation_planning(
                    session=session,
                    owner_id="owner-a",
                    request=_request(),
                )
        finally:
            transaction.rollback()


def test_planning_exception_rolls_back_new_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_planner(request: ObservationPlanningRequest) -> Any:
        raise RuntimeError("planner failed")

    with _session(tmp_path) as session:
        monkeypatch.setattr(orchestration, "plan_observation_request", failing_planner)
        with pytest.raises(RuntimeError, match="planner failed"):
            execute_observation_planning(
                session=session,
                owner_id="owner-a",
                request=_request(),
            )

        assert _count(session, ObservationPlanningRequestRow) == 0
        assert _count(session, ObservationPlanningRunRow) == 0
        assert _count(session, ObservationPlanRow) == 0


def test_persistence_exception_rolls_back_new_request_and_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_persist(
        self: SqlAlchemyObservationPlanningRepository,
        *,
        request_id: str,
        owner_id: str,
        result: object,
        use_savepoint: bool = True,
    ) -> Any:
        raise RuntimeError("persistence failed")

    with _session(tmp_path) as session:
        monkeypatch.setattr(
            SqlAlchemyObservationPlanningRepository,
            "persist_planning_result",
            failing_persist,
        )
        with pytest.raises(RuntimeError, match="persistence failed"):
            execute_observation_planning(
                session=session,
                owner_id="owner-a",
                request=_request(),
            )

        assert _count(session, ObservationPlanningRequestRow) == 0
        assert _count(session, ObservationPlanningRunRow) == 0
        assert _count(session, ObservationPlanRow) == 0


def test_execution_uses_no_quantum_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name.startswith("orbitmind.quantum") or name.startswith(
            "orbitmind.optimization.quantum"
        ):
            raise AssertionError(f"quantum import attempted: {name}")
        return original_import(name, globals, locals, fromlist, level)

    with _session(tmp_path) as session:
        monkeypatch.setattr(builtins, "__import__", guarded_import)
        execution = execute_observation_planning(
            session=session,
            owner_id="owner-a",
            request=_request(),
        )

    assert execution.final_status == PlanningResultStatus.VERIFIED_FEASIBLE
