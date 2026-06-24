"""Phase 4B.1 observation-planning persistence envelope tests."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import orbitmind.persistence.observation_planning_repository as op_repo_module
from orbitmind.core.errors import IdempotencyConflictError, NotFoundError, ValidationError
from orbitmind.observation_planning import (
    ObservationPlanningRequest,
    ObservationPlanningResult,
    ObservationPlanningScientificIdentity,
    ObservationPlanningSourceMode,
    PlanningHorizon,
    PlanningResultStatus,
    plan_observation_request,
)
from orbitmind.optimization.evaluation import Evaluator
from orbitmind.optimization.models import (
    ConstraintSet,
    ExperimentStatus,
    ObservationOpportunity,
    ObservationTarget,
    OptimalityStatus,
    SatelliteResource,
    SchedulingProblem,
    SchedulingProblemLimits,
    SolverConfiguration,
    SolverKind,
    SolverResult,
    TimeWindow,
)
from orbitmind.optimization.solvers.base import build_result
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
    db = Database(f"sqlite:///{(tmp_path / 'observation-planning.db').as_posix()}")
    db.create_all()
    return db


def _session(tmp_path: Path) -> Session:
    return _db(tmp_path).session()


def _horizon() -> PlanningHorizon:
    return PlanningHorizon(
        start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
    )


def _sat(sid: str = "SAT-A", *, energy: float = 10.0, storage: float = 10.0) -> SatelliteResource:
    return SatelliteResource(id=sid, energy_capacity=energy, storage_capacity=storage)


def _target(tid: str = "T1") -> ObservationTarget:
    return ObservationTarget(id=tid)


def _opp(
    oid: str,
    *,
    start_min: int = 0,
    end_min: int = 30,
    value: float = 5.0,
    energy: float = 1.0,
    storage: float = 1.0,
) -> ObservationOpportunity:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationOpportunity(
        id=oid,
        satellite_id="SAT-A",
        target_id="T1",
        window=TimeWindow(
            start=base + dt.timedelta(minutes=start_min),
            end=base + dt.timedelta(minutes=end_min),
        ),
        mission_value=value,
        duration_seconds=(end_min - start_min) * 60.0,
        energy_cost=energy,
        storage_cost=storage,
    )


def _fixture_request(*, idempotency_key: str | None = None) -> ObservationPlanningRequest:
    return ObservationPlanningRequest(
        name="fixture planning",
        horizon=_horizon(),
        fixture_name="default",
        requested_by="owner-a",
        idempotency_key=idempotency_key,
    )


def _declared_request(
    *,
    idempotency_key: str | None = None,
    opportunities: tuple[ObservationOpportunity, ...] | None = None,
    constraints: ConstraintSet | None = None,
    limits: SchedulingProblemLimits | None = None,
) -> ObservationPlanningRequest:
    return ObservationPlanningRequest(
        name="declared planning",
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=opportunities or (_opp("OPP-A"),),
        satellites=(_sat(),),
        targets=(_target(),),
        constraints=constraints or ConstraintSet(),
        limits=limits or SchedulingProblemLimits(),
        requested_by="owner-a",
        idempotency_key=idempotency_key,
    )


def _timeout_exact(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator | None = None,
) -> SolverResult:
    ev = (evaluator or Evaluator(problem)).evaluate(set())
    return build_result(
        solver_kind=SolverKind.EXACT,
        solver_name="fake-exact-timeout",
        solver_version="test",
        problem_checksum=problem.checksum,
        config=config,
        evaluation=ev,
        status=ExperimentStatus.TIMED_OUT,
        optimality=OptimalityStatus.UNKNOWN,
        known_optimum=None,
        runtime_seconds=0.0,
        evaluated_candidates=1,
        limitations="timeout",
    )


def _selecting_infeasible_exact(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator | None = None,
) -> SolverResult:
    ev = (evaluator or Evaluator(problem)).evaluate({"OPP-A", "OPP-B"})
    return build_result(
        solver_kind=SolverKind.EXACT,
        solver_name="fake-exact-infeasible",
        solver_version="test",
        problem_checksum=problem.checksum,
        config=config,
        evaluation=ev,
        status=ExperimentStatus.COMPLETED,
        optimality=OptimalityStatus.UNKNOWN,
        known_optimum=None,
        runtime_seconds=0.0,
        evaluated_candidates=1,
        limitations="infeasible",
    )


def _persist_request_and_result(
    session: Session,
    request: ObservationPlanningRequest,
) -> tuple[SqlAlchemyObservationPlanningRepository, str, str]:
    repo = SqlAlchemyObservationPlanningRepository(session)
    stored_request = repo.create_planning_request(request, owner_id=request.requested_by)
    result = plan_observation_request(request)
    stored_run = repo.persist_planning_result(
        request_id=stored_request.id,
        owner_id=stored_request.owner_id,
        result=result,
    )
    return repo, stored_request.id, stored_run.id


def _count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def test_persist_and_retrieve_fixture_request(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(
            _fixture_request(idempotency_key="same"), owner_id="owner-a"
        )
        session.commit()

        fetched = repo.get_planning_request(stored.id, owner_id="owner-a")

    assert fetched is not None
    assert fetched.request == stored.request
    assert fetched.request_checksum == stored.request_checksum
    assert fetched.source_mode == ObservationPlanningSourceMode.FIXTURE.value


def test_persist_and_retrieve_declared_request(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(_declared_request(), owner_id="owner-a")

        fetched = repo.get_planning_request(stored.id, owner_id="owner-a")

    assert fetched is not None
    assert fetched.request.source_mode == ObservationPlanningSourceMode.DECLARED
    assert fetched.request_checksum == stored.request_checksum


def test_request_idempotency_is_owner_scoped(tmp_path: Path) -> None:
    request = _fixture_request(idempotency_key="idem-1")
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        first = repo.create_planning_request(request, owner_id="owner-a")
        second = repo.create_planning_request(request, owner_id="owner-a")
        other_owner = repo.create_planning_request(request, owner_id="owner-b")

    assert first.id == second.id
    assert first.id != other_owner.id
    assert other_owner.owner_id == "owner-b"


def test_idempotency_key_conflicts_on_different_request(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        repo.create_planning_request(_fixture_request(idempotency_key="idem-2"), owner_id="owner-a")
        changed = _fixture_request(idempotency_key="idem-2").model_copy(
            update={"name": "changed scientific request"}
        )

        with pytest.raises(IdempotencyConflictError, match="different request"):
            repo.create_planning_request(changed, owner_id="owner-a")


def test_cross_owner_request_retrieval_is_not_found(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(_fixture_request(), owner_id="owner-a")

        assert repo.get_planning_request(stored.id, owner_id="owner-b") is None


def test_persist_verified_exact_result_creates_plan(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        run = repo.get_planning_run(run_id, owner_id="owner-a")
        plan = repo.get_observation_plan_for_run(run_id, owner_id="owner-a")

    assert run is not None
    assert run.result.status == PlanningResultStatus.VERIFIED_FEASIBLE
    assert run.plan_id is not None
    assert plan is not None
    assert plan.selected_opportunity_ids == ("OPP-A",)
    assert plan.evaluation.feasible is True


def test_persist_verified_greedy_result_creates_heuristic_plan(tmp_path: Path) -> None:
    request = _declared_request(
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30, value=5.0),
            _opp("OPP-B", start_min=40, end_min=70, value=6.0),
        ),
        limits=SchedulingProblemLimits(max_variables=2, exact_max_variables=1),
    )
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id="owner-a")
        result = plan_observation_request(request)
        run = repo.persist_planning_result(
            request_id=stored.id, owner_id=stored.owner_id, result=result
        )
        plan = repo.get_observation_plan_for_run(run.id, owner_id=stored.owner_id)

    assert run.result.optimality_label.value == "heuristic"
    assert plan is not None
    assert plan.selected_opportunity_ids == tuple(result.schedule.selected_opportunity_ids)


def test_non_success_runs_do_not_create_plans(tmp_path: Path) -> None:
    infeasible_request = _declared_request(
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30),
            _opp("OPP-B", start_min=10, end_min=40),
        ),
        constraints=ConstraintSet(mandatory=("OPP-A", "OPP-B")),
    )
    timeout_request = _declared_request(idempotency_key="timeout")
    infeasible = plan_observation_request(
        infeasible_request, exact_solver=_selecting_infeasible_exact
    )
    timed_out = plan_observation_request(
        timeout_request,
        exact_solver=_timeout_exact,
        allow_greedy_fallback=False,
    )

    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        infeasible_req = repo.create_planning_request(infeasible_request, owner_id="owner-a")
        timeout_req = repo.create_planning_request(timeout_request, owner_id="owner-a")
        infeasible_run = repo.persist_planning_result(
            request_id=infeasible_req.id,
            owner_id=infeasible_req.owner_id,
            result=infeasible,
        )
        timeout_run = repo.persist_planning_result(
            request_id=timeout_req.id,
            owner_id=timeout_req.owner_id,
            result=timed_out,
        )

        assert repo.get_observation_plan_for_run(infeasible_run.id, owner_id="owner-a") is None
        assert repo.get_observation_plan_for_run(timeout_run.id, owner_id="owner-a") is None
        assert _count(session, ObservationPlanRow) == 0


def test_result_request_and_problem_checksum_mismatches_are_rejected(tmp_path: Path) -> None:
    request = _declared_request()
    result = plan_observation_request(request)
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id="owner-a")

        with pytest.raises(ValidationError, match="request checksum"):
            repo.persist_planning_result(
                request_id=stored.id,
                owner_id=stored.owner_id,
                result=result.model_copy(update={"request_checksum": "0" * 64}),
            )

        with pytest.raises(ValidationError, match="problem checksum"):
            repo.persist_planning_result(
                request_id=stored.id,
                owner_id=stored.owner_id,
                result=result.model_copy(update={"problem_checksum": "1" * 64}),
            )


def test_duplicate_run_insertion_returns_existing_run(tmp_path: Path) -> None:
    request = _declared_request()
    result = plan_observation_request(request)
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id="owner-a")
        first = repo.persist_planning_result(
            request_id=stored.id, owner_id=stored.owner_id, result=result
        )
        second = repo.persist_planning_result(
            request_id=stored.id, owner_id=stored.owner_id, result=result
        )

    assert first.id == second.id
    assert first.plan_id == second.plan_id


def test_request_snapshot_tampering_is_detected(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(_fixture_request(), owner_id="owner-a")
        snapshot = dict(stored.request.model_dump(mode="json"))
        snapshot["name"] = "tampered"
        session.execute(
            update(ObservationPlanningRequestRow)
            .where(ObservationPlanningRequestRow.id == stored.id)
            .values(request_json=snapshot)
        )
        session.flush()

        with pytest.raises(ValidationError, match="checksum mismatch"):
            repo.get_planning_request(stored.id, owner_id="owner-a")


def test_request_schema_version_tampering_is_rejected_by_database(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(_fixture_request(), owner_id="owner-a")

        with pytest.raises(IntegrityError):
            session.execute(
                update(ObservationPlanningRequestRow)
                .where(ObservationPlanningRequestRow.id == stored.id)
                .values(request_schema_version="future")
            )
            session.flush()
        session.rollback()
        assert repo.get_planning_request(stored.id, owner_id="owner-a") is not None


def test_run_and_plan_scientific_identity_tampering_is_detected(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        run_row = session.get(ObservationPlanningRunRow, run_id)
        assert run_row is not None
        tampered_run_identity = dict(run_row.scientific_identity_json)
        tampered_run_identity["selected_opportunity_ids"] = []
        session.execute(
            update(ObservationPlanningRunRow)
            .where(ObservationPlanningRunRow.id == run_id)
            .values(scientific_identity_json=tampered_run_identity)
        )
        session.flush()

        with pytest.raises(ValidationError, match="scientific identity"):
            repo.get_planning_run(run_id, owner_id="owner-a")


def test_plan_snapshot_tampering_is_detected(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        plan = repo.get_observation_plan_for_run(run_id, owner_id="owner-a")
        assert plan is not None
        session.execute(
            update(ObservationPlanRow)
            .where(ObservationPlanRow.id == plan.id)
            .values(selected_opportunity_ids_json=["OPP-Z"])
        )
        session.flush()

        with pytest.raises(ValidationError, match="selected IDs"):
            repo.get_observation_plan(plan.id, owner_id="owner-a")


def test_scientific_identity_checksum_is_deterministic(tmp_path: Path) -> None:
    request = _declared_request()
    result = plan_observation_request(request)
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id="owner-a")
        run = repo.persist_planning_result(
            request_id=stored.id,
            owner_id=stored.owner_id,
            result=result,
        )

    assert run.scientific_identity_checksum == scientific_identity_checksum(
        result.scientific_identity
    )


def test_transaction_rollback_leaves_no_partial_run_or_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_plan_row(*args: object, **kwargs: object) -> ObservationPlanRow:
        raise ValidationError("forced plan persistence failure")

    request = _declared_request()
    result = plan_observation_request(request)
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(request, owner_id="owner-a")
        monkeypatch.setattr(op_repo_module, "_plan_row", broken_plan_row)

        with pytest.raises(ValidationError, match="forced"):
            repo.persist_planning_result(
                request_id=stored.id,
                owner_id=stored.owner_id,
                result=result,
            )

        assert _count(session, ObservationPlanningRunRow) == 0
        assert _count(session, ObservationPlanRow) == 0


def test_missing_request_is_rejected(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)

        with pytest.raises(NotFoundError):
            repo.persist_planning_result(
                request_id="missing",
                owner_id="owner-a",
                result=plan_observation_request(_declared_request()),
            )


def test_owner_id_must_be_non_empty_and_unpadded(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)

        with pytest.raises(ValidationError, match="owner_id"):
            op_repo_module._owner("")
        with pytest.raises(ValidationError, match="owner_id"):
            repo.get_planning_request("missing", owner_id=" padded ")


def test_request_source_mode_mismatch_is_detected_without_database_flush(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        repo = SqlAlchemyObservationPlanningRepository(session)
        stored = repo.create_planning_request(_fixture_request(), owner_id="owner-a")
        row = session.get(ObservationPlanningRequestRow, stored.id)
        assert row is not None
        row.source_mode = ObservationPlanningSourceMode.DECLARED.value

        with pytest.raises(ValidationError, match="source-mode"):
            repo._row_to_request(row)


def test_run_schema_and_identity_checksum_tampering_are_detected(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())

        session.execute(
            update(ObservationPlanningRunRow)
            .where(ObservationPlanningRunRow.id == run_id)
            .values(result_schema_version="future")
        )
        session.flush()
        with pytest.raises(ValidationError, match="result schema"):
            repo.get_planning_run(run_id, owner_id="owner-a")

        session.rollback()
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        session.execute(
            update(ObservationPlanningRunRow)
            .where(ObservationPlanningRunRow.id == run_id)
            .values(scientific_identity_checksum="2" * 64)
        )
        session.flush()
        with pytest.raises(ValidationError, match="identity checksum"):
            repo.get_planning_run(run_id, owner_id="owner-a")


def test_plan_schema_and_identity_checksum_tampering_are_detected(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        plan = repo.get_observation_plan_for_run(run_id, owner_id="owner-a")
        assert plan is not None
        row = session.get(ObservationPlanRow, plan.id)
        assert row is not None
        row.plan_schema_version = "future"

        with pytest.raises(ValidationError, match="plan schema"):
            repo._row_to_plan(row)

        row.plan_schema_version = "observation-plan-v1"
        row.scientific_identity_checksum = "3" * 64
        with pytest.raises(ValidationError, match="identity checksum"):
            repo._row_to_plan(row)


def test_plan_identity_selected_ids_and_problem_mismatches_are_detected(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        plan = repo.get_observation_plan_for_run(run_id, owner_id="owner-a")
        assert plan is not None
        row = session.get(ObservationPlanRow, plan.id)
        assert row is not None
        identity_payload = dict(row.scientific_identity_json)
        identity_payload["selected_opportunity_ids"] = []
        identity = ObservationPlanningScientificIdentity.model_validate(identity_payload)
        row.scientific_identity_json = identity.model_dump(mode="json")
        row.scientific_identity_checksum = scientific_identity_checksum(identity)

        with pytest.raises(ValidationError, match="selected IDs"):
            repo._row_to_plan(row)

        identity_payload = dict(plan.scientific_identity.model_dump(mode="json"))
        identity_payload["problem_checksum"] = "4" * 64
        problem_identity = ObservationPlanningScientificIdentity.model_validate(identity_payload)
        row.selected_opportunity_ids_json = list(plan.selected_opportunity_ids)
        row.scientific_identity_json = problem_identity.model_dump(mode="json")
        row.scientific_identity_checksum = scientific_identity_checksum(problem_identity)
        with pytest.raises(ValidationError, match="problem checksum"):
            repo._row_to_plan(row)


@pytest.mark.parametrize(
    ("field_name", "value", "message"),
    [
        ("request_checksum", "5" * 64, "request checksum"),
        ("problem_checksum", "6" * 64, "problem checksum"),
        ("planning_status", "failed", "status mismatch"),
        ("authoritative_solver", "greedy", "solver mismatch"),
        ("solver_execution_status", "timed-out", "solver status"),
        ("optimality_label", "heuristic", "optimality"),
        ("verification_label", None, "verification-label"),
        ("source_mode", "fixture", "source-mode"),
        ("feasible", False, "feasible flag"),
        ("objective_value", 999.0, "objective mismatch"),
    ],
)
def test_run_scalar_mismatches_are_detected_without_database_flush(
    tmp_path: Path,
    field_name: str,
    value: object,
    message: str,
) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        stored = repo.get_planning_run(run_id, owner_id="owner-a")
        assert stored is not None
        row = session.get(ObservationPlanningRunRow, run_id)
        assert row is not None
        setattr(row, field_name, value)

        with pytest.raises(ValidationError, match=message):
            op_repo_module._assert_row_matches_result(row, stored.result)


def test_run_objective_null_mismatches_are_detected_without_database_flush(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        repo, _, run_id = _persist_request_and_result(session, _declared_request())
        stored = repo.get_planning_run(run_id, owner_id="owner-a")
        assert stored is not None
        row = session.get(ObservationPlanningRunRow, run_id)
        assert row is not None
        row.objective_value = None
        with pytest.raises(ValidationError, match="objective mismatch"):
            op_repo_module._assert_row_matches_result(row, stored.result)

        row.objective_value = stored.result.objective_value
        result_without_objective = stored.result.model_copy(update={"objective_value": None})
        with pytest.raises(ValidationError, match="objective mismatch"):
            op_repo_module._assert_row_matches_result(row, result_without_objective)


def test_plan_row_requires_schedule_and_evaluation(tmp_path: Path) -> None:
    result = plan_observation_request(_declared_request())
    broken = result.model_copy(update={"schedule": None})

    with pytest.raises(ValidationError, match="persisted plan"):
        op_repo_module._plan_row(
            "run",
            "owner-a",
            broken,
            scientific_identity_checksum(result.scientific_identity),
        )


def test_result_model_rejects_verified_feasible_unknown_or_infeasible_optimality() -> None:
    result = plan_observation_request(_declared_request())
    for bad_label in ("unknown", "infeasible"):
        payload = result.model_dump(mode="python")
        payload["optimality_label"] = bad_label
        with pytest.raises(Exception, match="verified-feasible"):
            ObservationPlanningResult.model_validate(payload)
