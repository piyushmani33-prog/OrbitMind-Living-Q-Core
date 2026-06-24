"""Phase 4B first-slice tests: bounded request -> SchedulingProblem translation."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.errors import ValidationError
from orbitmind.observation_planning import (
    ObservationPlanningRequest,
    ObservationPlanningSourceMode,
    PlanningHorizon,
    PlanningVerificationLabel,
    planning_request_checksum,
    translate_request_to_problem,
)
from orbitmind.optimization.models import (
    ConstraintSet,
    ObservationOpportunity,
    ObservationTarget,
    SatelliteResource,
    SchedulingObjective,
    TimeWindow,
)


def _horizon(
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> PlanningHorizon:
    return PlanningHorizon(
        start=start or dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        end=end or dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
    )


def _opp(
    oid: str,
    sat: str = "SAT-A",
    target: str = "T1",
    start_min: int = 0,
    end_min: int = 30,
    value: float = 5.0,
) -> ObservationOpportunity:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return ObservationOpportunity(
        id=oid,
        satellite_id=sat,
        target_id=target,
        window=TimeWindow(
            start=base + dt.timedelta(minutes=start_min),
            end=base + dt.timedelta(minutes=end_min),
        ),
        mission_value=value,
        duration_seconds=(end_min - start_min) * 60.0,
        energy_cost=1.0,
        storage_cost=1.0,
    )


def test_fixture_request_translates_to_honest_fixture_problem() -> None:
    request = ObservationPlanningRequest(
        name="fixture planning prototype",
        horizon=_horizon(),
        fixture_name="default",
        constraints=ConstraintSet(max_observations=3),
        objective=SchedulingObjective(mission_value_weight=2.0),
        idempotency_key="transport-only",
    )

    translated = translate_request_to_problem(request)

    assert translated.request_checksum == planning_request_checksum(request)
    assert translated.verification_label == PlanningVerificationLabel.VERIFIED_FIXTURE_PLAN
    assert translated.problem.name == request.name
    assert translated.problem.checksum
    assert translated.problem.source == "observation-planning-fixture"
    assert translated.problem.constraints.max_observations == 3
    assert translated.problem.objective.mission_value_weight == 2.0
    assert "access-window geometry is not computed" in translated.problem.limitations
    assert "not an operational tasking" in translated.problem.limitations


def test_planning_request_checksum_is_stable_and_excludes_idempotency_key() -> None:
    base = ObservationPlanningRequest(
        name="stable request",
        horizon=_horizon(),
        fixture_name="default",
        idempotency_key="first",
    )
    same_transport_only = base.model_copy(update={"idempotency_key": "second"})
    renamed = base.model_copy(update={"name": "renamed request"})

    assert planning_request_checksum(base) == planning_request_checksum(same_transport_only)
    assert planning_request_checksum(base) != planning_request_checksum(renamed)


def test_declared_request_checksum_is_order_independent_for_registries() -> None:
    opp_a = _opp("OPP-A", target="T1", value=5.0)
    opp_b = _opp("OPP-B", target="T2", start_min=40, end_min=70, value=6.0)
    sat = SatelliteResource(id="SAT-A", energy_capacity=10.0, storage_capacity=10.0)
    t1 = ObservationTarget(id="T1", priority=2)
    t2 = ObservationTarget(id="T2", priority=1)

    first = ObservationPlanningRequest(
        name="declared planning prototype",
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=(opp_a, opp_b),
        satellites=(sat,),
        targets=(t1, t2),
    )
    reordered = first.model_copy(update={"opportunities": (opp_b, opp_a), "targets": (t2, t1)})

    assert planning_request_checksum(first) == planning_request_checksum(reordered)


def test_planning_request_checksum_canonicalizes_constraint_order() -> None:
    first = ObservationPlanningRequest(
        name="constraint order",
        horizon=_horizon(),
        fixture_name="mutual-exclusion",
        constraints=ConstraintSet(
            mandatory=("OPP-2", "OPP-1"),
            mutually_exclusive=(("OPP-3", "OPP-1"), ("OPP-2", "OPP-1")),
        ),
    )
    reordered = first.model_copy(
        update={
            "constraints": ConstraintSet(
                mandatory=("OPP-1", "OPP-2"),
                mutually_exclusive=(("OPP-1", "OPP-2"), ("OPP-1", "OPP-3")),
            )
        }
    )

    assert planning_request_checksum(first) == planning_request_checksum(reordered)


def test_declared_request_translates_to_normalized_problem() -> None:
    offset = dt.timezone(dt.timedelta(hours=5))
    start = dt.datetime(2026, 6, 21, 15, 0, tzinfo=offset)
    opp = _opp("OPP-A").model_copy(
        update={"window": TimeWindow(start=start, end=start + dt.timedelta(minutes=30))}
    )
    request = ObservationPlanningRequest(
        name="declared opportunity plan",
        horizon=_horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=(opp,),
        satellites=(SatelliteResource(id="SAT-A", energy_capacity=5.0, storage_capacity=5.0),),
        targets=(ObservationTarget(id="T1"),),
    )

    translated = translate_request_to_problem(request)

    assert (
        translated.verification_label
        == PlanningVerificationLabel.VERIFIED_DECLARED_OPPORTUNITY_PLAN
    )
    assert translated.problem.source == "observation-planning-declared"
    assert translated.problem.opportunities[0].window.start.tzinfo == dt.UTC
    assert translated.problem.opportunities[0].window.start.hour == 10
    assert translated.problem.opportunities[0].duration_seconds == 30 * 60.0


def test_planning_horizon_rejects_naive_and_overlong_windows() -> None:
    with pytest.raises(PydanticValidationError):
        PlanningHorizon(
            start=dt.datetime(2026, 6, 21, 9, 0),
            end=dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC),
        )

    with pytest.raises(PydanticValidationError):
        PlanningHorizon(
            start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 24, 9, 0, tzinfo=dt.UTC),
        )


def test_planning_request_rejects_mixed_fixture_and_declared_inputs() -> None:
    with pytest.raises(PydanticValidationError):
        ObservationPlanningRequest(
            name="mixed",
            horizon=_horizon(),
            fixture_name="default",
            opportunities=(_opp("OPP-A"),),
        )

    with pytest.raises(PydanticValidationError):
        ObservationPlanningRequest(
            name="declared without registries",
            horizon=_horizon(),
            source_mode=ObservationPlanningSourceMode.DECLARED,
            fixture_name=None,
            opportunities=(_opp("OPP-A"),),
        )


def test_translation_rejects_unknown_fixture_and_out_of_horizon_opportunities() -> None:
    unknown_fixture = ObservationPlanningRequest(
        name="unknown fixture",
        horizon=_horizon(),
        fixture_name="does-not-exist",
    )
    with pytest.raises(ValidationError):
        translate_request_to_problem(unknown_fixture)

    outside = ObservationPlanningRequest(
        name="outside horizon",
        horizon=_horizon(
            start=dt.datetime(2026, 6, 21, 11, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        ),
        fixture_name="default",
    )
    with pytest.raises(ValidationError):
        translate_request_to_problem(outside)
