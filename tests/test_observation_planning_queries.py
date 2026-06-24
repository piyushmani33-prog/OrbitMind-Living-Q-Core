"""Typed observation-planning query-layer tests."""

from __future__ import annotations

import builtins
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_planning import (
    AuthoritativePlanningSolver,
    ObservationPlanningPage,
    ObservationPlanningRequest,
    ObservationPlanningRequestDetails,
    ObservationPlanningRunDetails,
    ObservationPlanningSourceMode,
    PlanningHorizon,
    PlanningResultStatus,
    execute_observation_planning,
    get_observation_plan,
    get_observation_planning_execution,
    get_observation_planning_request,
    get_observation_planning_run,
    list_observation_planning_requests,
    list_observation_planning_runs,
    list_observation_plans,
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
)


def _db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'planning-queries.db').as_posix()}")
    db.create_all()
    return db


def _session(tmp_path: Path) -> Session:
    return _db(tmp_path).session()


def _horizon() -> PlanningHorizon:
    return PlanningHorizon(
        start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
    )


def _opp(
    oid: str = "OPP-A",
    *,
    start_min: int = 60,
    end_min: int = 90,
    value: float = 5.0,
) -> ObservationOpportunity:
    base = dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC)
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
        energy_cost=1.0,
        storage_cost=1.0,
    )


def _declared_request(
    *,
    name: str = "declared query request",
    owner: str = "owner-a",
    idempotency_key: str | None = None,
    opportunities: tuple[ObservationOpportunity, ...] | None = None,
    constraints: ConstraintSet | None = None,
    limits: SchedulingProblemLimits | None = None,
) -> ObservationPlanningRequest:
    return ObservationPlanningRequest(
        name=name,
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=opportunities or (_opp(),),
        satellites=(SatelliteResource(id="SAT-A", energy_capacity=20.0, storage_capacity=20.0),),
        targets=(ObservationTarget(id="T1"),),
        constraints=constraints or ConstraintSet(),
        limits=limits or SchedulingProblemLimits(),
        requested_by=owner,
        idempotency_key=idempotency_key,
    )


def _fixture_request(
    *, name: str = "fixture query request", owner: str = "owner-a"
) -> ObservationPlanningRequest:
    return ObservationPlanningRequest(
        name=name,
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.FIXTURE,
        fixture_name="default",
        requested_by=owner,
    )


def _greedy_request(*, name: str = "greedy query request") -> ObservationPlanningRequest:
    return _declared_request(
        name=name,
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30, value=5.0),
            _opp("OPP-B", start_min=40, end_min=70, value=6.0),
        ),
        limits=SchedulingProblemLimits(max_variables=2, exact_max_variables=1),
    )


def _infeasible_request() -> ObservationPlanningRequest:
    return _declared_request(
        name="infeasible query request",
        opportunities=(
            _opp("OPP-A", start_min=0, end_min=30),
            _opp("OPP-B", start_min=10, end_min=40),
        ),
        constraints=ConstraintSet(mandatory=("OPP-A", "OPP-B")),
    )


def _timeout_exact(
    problem: SchedulingProblem,
    config: SolverConfiguration,
    evaluator: Evaluator | None = None,
) -> SolverResult:
    return build_result(
        solver_kind=SolverKind.EXACT,
        solver_name="fake-timeout",
        solver_version="test",
        problem_checksum=problem.checksum,
        config=config,
        evaluation=None,
        status=ExperimentStatus.TIMED_OUT,
        optimality=OptimalityStatus.UNKNOWN,
        known_optimum=None,
        runtime_seconds=0.0,
        evaluated_candidates=0,
        limitations="timeout",
    )


def _execute(
    session: Session,
    request: ObservationPlanningRequest,
    *,
    owner_id: str = "owner-a",
) -> tuple[str, str, str | None]:
    execution = execute_observation_planning(session=session, owner_id=owner_id, request=request)
    return execution.request_id, execution.run_id, execution.plan_id


def _persist_result(
    session: Session,
    request: ObservationPlanningRequest,
    result: object,
    *,
    owner_id: str = "owner-a",
) -> tuple[str, str, str | None]:
    repo = SqlAlchemyObservationPlanningRepository(session)
    stored = repo.create_planning_request(request, owner_id=owner_id)
    run = repo.persist_planning_result(
        request_id=stored.id,
        owner_id=stored.owner_id,
        result=result,  # type: ignore[arg-type]
    )
    return stored.id, run.id, run.plan_id


def test_retrieve_fixture_and_declared_request_details(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        fixture_id, _, _ = _execute(session, _fixture_request())
        declared_id, _, _ = _execute(session, _declared_request(name="declared detail"))

        fixture = get_observation_planning_request(
            session, owner_id="owner-a", request_id=fixture_id
        )
        declared = get_observation_planning_request(
            session, owner_id="owner-a", request_id=declared_id
        )

    assert isinstance(fixture, ObservationPlanningRequestDetails)
    assert fixture.summary.source_mode == ObservationPlanningSourceMode.FIXTURE
    assert declared.summary.source_mode == ObservationPlanningSourceMode.DECLARED
    assert declared.request.name == "declared detail"


def test_retrieve_exact_and_greedy_successful_executions(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        _, exact_run_id, exact_plan_id = _execute(session, _declared_request())
        _, greedy_run_id, greedy_plan_id = _execute(session, _greedy_request())

        exact = get_observation_planning_execution(session, owner_id="owner-a", run_id=exact_run_id)
        greedy = get_observation_planning_execution(
            session, owner_id="owner-a", run_id=greedy_run_id
        )

    assert exact.plan is not None
    assert exact.plan.summary.id == exact_plan_id
    assert exact.run.summary.selected_solver == AuthoritativePlanningSolver.EXACT
    assert greedy.plan is not None
    assert greedy.plan.summary.id == greedy_plan_id
    assert greedy.run.summary.selected_solver == AuthoritativePlanningSolver.GREEDY
    assert greedy.run.summary.optimality_label.value == "heuristic"


def test_retrieve_non_success_runs_without_fabricated_plan(tmp_path: Path) -> None:
    infeasible_request = _infeasible_request()
    timeout_request = _declared_request(name="timeout query request")
    infeasible = plan_observation_request(infeasible_request)
    timed_out = plan_observation_request(
        timeout_request,
        exact_solver=_timeout_exact,
        allow_greedy_fallback=False,
    )
    with _session(tmp_path) as session:
        _, infeasible_run_id, infeasible_plan = _persist_result(
            session, infeasible_request, infeasible
        )
        _, timeout_run_id, timeout_plan = _persist_result(session, timeout_request, timed_out)

        infeasible_details = get_observation_planning_execution(
            session, owner_id="owner-a", run_id=infeasible_run_id
        )
        timeout_details = get_observation_planning_execution(
            session, owner_id="owner-a", run_id=timeout_run_id
        )

    assert infeasible_plan is None
    assert infeasible_details.plan is None
    assert infeasible_details.run.summary.status == PlanningResultStatus.INFEASIBLE
    assert timeout_plan is None
    assert timeout_details.plan is None
    assert timeout_details.run.summary.status == PlanningResultStatus.TIMED_OUT


def test_cross_owner_retrieval_is_not_found(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        request_id, run_id, plan_id = _execute(session, _declared_request())
        assert plan_id is not None

        with pytest.raises(NotFoundError):
            get_observation_planning_request(session, owner_id="owner-b", request_id=request_id)
        with pytest.raises(NotFoundError):
            get_observation_planning_run(session, owner_id="owner-b", run_id=run_id)
        with pytest.raises(NotFoundError):
            get_observation_plan(session, owner_id="owner-b", plan_id=plan_id)


def test_list_requests_runs_and_plans_are_owner_scoped(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        _execute(session, _declared_request(name="owner-a-1"), owner_id="owner-a")
        _execute(session, _declared_request(name="owner-b-1", owner="owner-b"), owner_id="owner-b")

        requests = list_observation_planning_requests(session, owner_id="owner-a")
        runs = list_observation_planning_runs(session, owner_id="owner-a")
        plans = list_observation_plans(session, owner_id="owner-a")

    assert [item.name for item in requests.items] == ["owner-a-1"]
    assert len(runs.items) == 1
    assert all(item.owner_id == "owner-a" for item in runs.items)
    assert len(plans.items) == 1
    assert all(item.owner_id == "owner-a" for item in plans.items)


def test_deterministic_ordering_and_stable_pagination(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        for index in range(3):
            _execute(
                session,
                _declared_request(name=f"ordered-{index}", idempotency_key=f"ordered-{index}"),
            )

        full = list_observation_planning_requests(session, owner_id="owner-a", limit=10)
        first = list_observation_planning_requests(session, owner_id="owner-a", limit=1, offset=0)
        second = list_observation_planning_requests(session, owner_id="owner-a", limit=1, offset=1)
        repeat = list_observation_planning_requests(session, owner_id="owner-a", limit=1, offset=0)

    ordered = sorted(full.items, key=lambda item: (item.created_at, item.id), reverse=True)
    assert list(full.items) == ordered
    assert first.items == repeat.items
    assert first.items[0].id == full.items[0].id
    assert second.items[0].id == full.items[1].id
    assert first.has_next is True
    assert isinstance(full, ObservationPlanningPage)


def test_page_size_and_offset_validation(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        with pytest.raises(ValidationError, match="limit"):
            list_observation_planning_requests(session, owner_id="owner-a", limit=0)
        with pytest.raises(ValidationError, match="limit"):
            list_observation_planning_requests(session, owner_id="owner-a", limit=101)
        with pytest.raises(ValidationError, match="offset"):
            list_observation_planning_requests(session, owner_id="owner-a", offset=-1)


def test_status_source_and_feasible_filters(tmp_path: Path) -> None:
    infeasible_request = _infeasible_request()
    infeasible = plan_observation_request(infeasible_request)
    with _session(tmp_path) as session:
        _execute(session, _fixture_request(name="fixture-filter"))
        _execute(session, _declared_request(name="declared-filter"))
        _persist_result(session, infeasible_request, infeasible)

        fixture_requests = list_observation_planning_requests(
            session, owner_id="owner-a", source_mode=ObservationPlanningSourceMode.FIXTURE
        )
        feasible_runs = list_observation_planning_runs(
            session, owner_id="owner-a", feasible_only=True
        )
        infeasible_runs = list_observation_planning_runs(
            session, owner_id="owner-a", status=PlanningResultStatus.INFEASIBLE
        )
        exact_runs = list_observation_planning_runs(
            session,
            owner_id="owner-a",
            authoritative_solver=AuthoritativePlanningSolver.EXACT,
        )

    assert [item.name for item in fixture_requests.items] == ["fixture-filter"]
    assert all(item.feasible for item in feasible_runs.items)
    assert len(infeasible_runs.items) == 1
    assert all(
        item.selected_solver == AuthoritativePlanningSolver.EXACT for item in exact_runs.items
    )


def test_request_tamper_detection(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        request_id, _, _ = _execute(session, _declared_request())
        row = session.get(ObservationPlanningRequestRow, request_id)
        assert row is not None
        tampered = dict(row.request_json)
        tampered["name"] = "tampered"
        session.execute(
            update(ObservationPlanningRequestRow)
            .where(ObservationPlanningRequestRow.id == request_id)
            .values(request_json=tampered)
        )
        session.flush()

        with pytest.raises(ValidationError, match="checksum"):
            get_observation_planning_request(session, owner_id="owner-a", request_id=request_id)


def test_run_scientific_identity_tamper_detection(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        _, run_id, _ = _execute(session, _declared_request())
        row = session.get(ObservationPlanningRunRow, run_id)
        assert row is not None
        tampered = dict(row.scientific_identity_json)
        tampered["selected_opportunity_ids"] = []
        session.execute(
            update(ObservationPlanningRunRow)
            .where(ObservationPlanningRunRow.id == run_id)
            .values(scientific_identity_json=tampered)
        )
        session.flush()

        with pytest.raises(ValidationError, match="scientific identity"):
            get_observation_planning_run(session, owner_id="owner-a", run_id=run_id)


def test_plan_snapshot_tamper_detection(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        _, _, plan_id = _execute(session, _declared_request())
        assert plan_id is not None
        session.execute(
            update(ObservationPlanRow)
            .where(ObservationPlanRow.id == plan_id)
            .values(selected_opportunity_ids_json=["OPP-Z"])
        )
        session.flush()

        with pytest.raises(ValidationError, match="selected IDs"):
            get_observation_plan(session, owner_id="owner-a", plan_id=plan_id)


def test_schema_version_tamper_detection(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        request_id, _, _ = _execute(session, _declared_request())
        session.execute(text("PRAGMA ignore_check_constraints=ON"))
        session.execute(
            update(ObservationPlanningRequestRow)
            .where(ObservationPlanningRequestRow.id == request_id)
            .values(request_schema_version="future")
        )
        session.flush()

        with pytest.raises(ValidationError, match="request schema"):
            get_observation_planning_request(session, owner_id="owner-a", request_id=request_id)


@pytest.mark.parametrize("owner_id", ["", "   ", " padded "])
def test_owner_id_is_required_and_unpadded(tmp_path: Path, owner_id: str) -> None:
    with _session(tmp_path) as session, pytest.raises(ValidationError, match="owner_id"):
        list_observation_planning_requests(session, owner_id=owner_id)


def test_query_results_do_not_expose_orm_rows(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        _, run_id, plan_id = _execute(session, _declared_request())
        assert plan_id is not None
        request_page = list_observation_planning_requests(session, owner_id="owner-a")
        run_details = get_observation_planning_run(session, owner_id="owner-a", run_id=run_id)
        plan_details = get_observation_plan(session, owner_id="owner-a", plan_id=plan_id)

    assert not isinstance(request_page.items[0], ObservationPlanningRequestRow)
    assert isinstance(run_details, ObservationPlanningRunDetails)
    assert not isinstance(run_details, ObservationPlanningRunRow)
    assert not isinstance(plan_details, ObservationPlanRow)


def test_queries_use_no_quantum_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        _, run_id, _ = _execute(session, _declared_request())
        monkeypatch.setattr(builtins, "__import__", guarded_import)
        details = get_observation_planning_execution(session, owner_id="owner-a", run_id=run_id)

    assert details.run.summary.status == PlanningResultStatus.VERIFIED_FEASIBLE
