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


def _sat(sid: str = "SAT-A") -> SatelliteResource:
    return SatelliteResource(id=sid, energy_capacity=10.0, storage_capacity=10.0)


def _target(tid: str = "T1") -> ObservationTarget:
    return ObservationTarget(id=tid)


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


def _declared_request(
    *,
    opportunities: tuple[ObservationOpportunity, ...] | None = None,
    satellites: tuple[SatelliteResource, ...] | None = None,
    targets: tuple[ObservationTarget, ...] | None = None,
    horizon: PlanningHorizon | None = None,
    constraints: ConstraintSet | None = None,
    objective: SchedulingObjective | None = None,
) -> ObservationPlanningRequest:
    return ObservationPlanningRequest(
        name="declared planning prototype",
        horizon=horizon or _horizon(),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=opportunities or (_opp("OPP-A"),),
        satellites=satellites or (_sat(),),
        targets=targets or (_target(),),
        constraints=constraints or ConstraintSet(),
        objective=objective or SchedulingObjective(),
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
    t1 = _target("T1").model_copy(update={"priority": 2})
    t2 = _target("T2").model_copy(update={"priority": 1})

    first = _declared_request(
        opportunities=(opp_a, opp_b),
        satellites=(_sat(),),
        targets=(t1, t2),
    )
    reordered = first.model_copy(update={"opportunities": (opp_b, opp_a), "targets": (t2, t1)})

    assert planning_request_checksum(first) == planning_request_checksum(reordered)


def test_declared_opportunity_checksum_canonicalizes_equivalent_offsets() -> None:
    utc_start = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    offset = dt.timezone(dt.timedelta(hours=5))
    offset_start = dt.datetime(2026, 6, 21, 15, 0, tzinfo=offset)
    utc_opp = _opp("OPP-A").model_copy(
        update={"window": TimeWindow(start=utc_start, end=utc_start + dt.timedelta(minutes=30))}
    )
    offset_opp = _opp("OPP-A").model_copy(
        update={
            "window": TimeWindow(
                start=offset_start,
                end=offset_start + dt.timedelta(minutes=30),
            )
        }
    )

    assert planning_request_checksum(
        _declared_request(opportunities=(utc_opp,))
    ) == planning_request_checksum(_declared_request(opportunities=(offset_opp,)))


def test_declared_opportunity_checksum_distinguishes_different_instants() -> None:
    base_start = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    shifted_start = base_start + dt.timedelta(minutes=1)
    base = _opp("OPP-A").model_copy(
        update={"window": TimeWindow(start=base_start, end=base_start + dt.timedelta(minutes=30))}
    )
    shifted = _opp("OPP-A").model_copy(
        update={
            "window": TimeWindow(
                start=shifted_start,
                end=shifted_start + dt.timedelta(minutes=30),
            )
        }
    )

    assert planning_request_checksum(_declared_request(opportunities=(base,))) != (
        planning_request_checksum(_declared_request(opportunities=(shifted,)))
    )


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
    request = _declared_request(
        opportunities=(opp,),
        satellites=(SatelliteResource(id="SAT-A", energy_capacity=5.0, storage_capacity=5.0),),
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

    with pytest.raises(PydanticValidationError):
        PlanningHorizon(
            start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        )

    with pytest.raises(PydanticValidationError):
        PlanningHorizon(
            start=dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
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


def test_planning_request_rejects_oversized_collections() -> None:
    with pytest.raises(PydanticValidationError):
        _declared_request(opportunities=tuple(_opp(f"OPP-{i:02d}") for i in range(25)))

    with pytest.raises(PydanticValidationError):
        _declared_request(satellites=tuple(_sat(f"SAT-{i:02d}") for i in range(25)))

    with pytest.raises(PydanticValidationError):
        _declared_request(targets=tuple(_target(f"T{i:02d}") for i in range(25)))

    with pytest.raises(PydanticValidationError):
        ObservationPlanningRequest(
            name="too many mandatory",
            horizon=_horizon(),
            fixture_name="default",
            constraints=ConstraintSet(mandatory=tuple(f"OPP-{i:02d}" for i in range(25))),
        )

    with pytest.raises(PydanticValidationError):
        ObservationPlanningRequest(
            name="too many mutex",
            horizon=_horizon(),
            fixture_name="default",
            constraints=ConstraintSet(
                mutually_exclusive=tuple((f"OPP-{i:03d}", f"OPP-{i + 1:03d}") for i in range(277))
            ),
        )


def test_planning_request_rejects_malformed_mutual_exclusion_group() -> None:
    malformed = ConstraintSet.model_construct(
        max_observations=None,
        mutually_exclusive=(("OPP-1", "OPP-2", "OPP-3"),),
        mandatory=(),
        per_target_limit=None,
        min_mission_value=None,
        enforce_no_overlap=True,
        enforce_energy_capacity=True,
        enforce_storage_capacity=True,
    )

    with pytest.raises(PydanticValidationError):
        ObservationPlanningRequest(
            name="bad mutex group",
            horizon=_horizon(),
            fixture_name="default",
            constraints=malformed,
        )


def test_declared_request_rejects_duplicate_ids_before_checksum_generation() -> None:
    with pytest.raises(PydanticValidationError):
        _declared_request(
            opportunities=(
                _opp("OPP-A", start_min=0, end_min=30),
                _opp("OPP-A", start_min=40, end_min=70),
            )
        )

    with pytest.raises(PydanticValidationError):
        _declared_request(satellites=(_sat("SAT-A"), _sat("SAT-A")))

    with pytest.raises(PydanticValidationError):
        _declared_request(targets=(_target("T1"), _target("T1")))


def test_declared_request_rejects_nonfinite_numeric_input() -> None:
    bad_opp = _opp("OPP-A").model_copy(update={"mission_value": float("nan")})
    with pytest.raises(PydanticValidationError):
        _declared_request(opportunities=(bad_opp,))

    bad_objective = SchedulingObjective.model_construct(
        mission_value_weight=float("inf"),
        penalty_coefficient=None,
    )
    with pytest.raises(PydanticValidationError):
        _declared_request(objective=bad_objective)


def test_translation_rejects_invalid_declared_references() -> None:
    bad_sat = _declared_request(opportunities=(_opp("OPP-A", sat="UNKNOWN"),))
    with pytest.raises(ValidationError):
        translate_request_to_problem(bad_sat)

    bad_target = _declared_request(opportunities=(_opp("OPP-A", target="UNKNOWN"),))
    with pytest.raises(ValidationError):
        translate_request_to_problem(bad_target)


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

    declared_outside = _declared_request(
        horizon=_horizon(
            start=dt.datetime(2026, 6, 21, 11, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        ),
        opportunities=(_opp("OPP-A", start_min=0, end_min=30),),
    )
    with pytest.raises(ValidationError):
        translate_request_to_problem(declared_outside)


def test_translation_does_not_mutate_request() -> None:
    offset = dt.timezone(dt.timedelta(hours=5))
    start = dt.datetime(2026, 6, 21, 15, 0, tzinfo=offset)
    opp = _opp("OPP-A").model_copy(
        update={"window": TimeWindow(start=start, end=start + dt.timedelta(minutes=30))}
    )
    request = _declared_request(opportunities=(opp,))
    before = request.model_dump(mode="json")

    translate_request_to_problem(request)

    assert request.model_dump(mode="json") == before
    assert request.opportunities[0].window.start.tzinfo == offset


def test_translating_same_request_twice_produces_same_problem_checksum() -> None:
    request = _declared_request(
        opportunities=(
            _opp("OPP-A", target="T1", start_min=0, end_min=30, value=5.0),
            _opp("OPP-B", target="T2", start_min=40, end_min=70, value=6.0),
        ),
        targets=(_target("T1"), _target("T2")),
    )

    first = translate_request_to_problem(request)
    second = translate_request_to_problem(request)

    assert first.problem.checksum == second.problem.checksum


@pytest.mark.parametrize(
    ("field_name", "payload"),
    [
        ("opportunities", tuple(_opp(f"OPP-{i:02d}") for i in range(25))),
        ("satellites", tuple(_sat(f"SAT-{i:02d}") for i in range(25))),
        ("targets", tuple(_target(f"T{i:02d}") for i in range(25))),
    ],
)
def test_request_collection_bounds_are_field_level(
    field_name: str, payload: tuple[object, ...]
) -> None:
    kwargs = {
        "name": "field level bound",
        "horizon": _horizon(),
        "source_mode": ObservationPlanningSourceMode.DECLARED,
        "fixture_name": None,
        "opportunities": (_opp("OPP-A"),),
        "satellites": (_sat(),),
        "targets": (_target(),),
    }
    kwargs[field_name] = payload

    with pytest.raises(PydanticValidationError) as exc_info:
        ObservationPlanningRequest(**kwargs)

    assert any(error["loc"] == (field_name,) for error in exc_info.value.errors())
