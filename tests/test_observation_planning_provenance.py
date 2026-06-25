"""Phase 4B.2A tests for pinned input provenance and declared eligibility."""

from __future__ import annotations

import datetime as dt
import inspect

import pytest
from pydantic import ValidationError as PydanticValidationError

import orbitmind.observation_planning.provenance as provenance_module
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import ValidationError
from orbitmind.observation_planning.models import (
    ObservationPlanningRequest,
    ObservationPlanningSourceMode,
    PlanningHorizon,
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
    eligibility_windows_to_opportunities,
    provenance_checksum,
    validate_request_against_eligibility,
)
from orbitmind.optimization.models import ObservationTarget, SatelliteResource


def _checksum(label: str) -> str:
    return sha256_text(label)


def _rights(
    *,
    status: InputRightsStatus = InputRightsStatus.DECLARED,
    redistribution: InputRightsPermission = InputRightsPermission.UNKNOWN,
) -> InputRightsDeclaration:
    return InputRightsDeclaration(
        rights_status=status,
        license_id="fixture-license" if status == InputRightsStatus.VERIFIED else None,
        redistribution=redistribution,
        commercial_use=InputRightsPermission.UNKNOWN,
        attribution_required=status == InputRightsStatus.VERIFIED,
        user_responsibility="caller remains responsible for supplied rights declarations",
        limitations=("rights declaration only; not legal clearance",),
    )


def _artifact(label: str = "content") -> PinnedInputArtifact:
    return PinnedInputArtifact(
        artifact_id=f"artifact-{label}",
        content_checksum=_checksum(label),
        media_type="application/json",
        record_count=2,
    )


def _fixture_source(version: str = "v1") -> InputSourceIdentity:
    return InputSourceIdentity(
        source_id="fixture-observation-windows",
        source_type=PinnedInputSourceType.FIXTURE,
        source_mode=PinnedInputSourceMode.FIXTURE_BACKED,
        publisher="OrbitMind",
        dataset_name="observation-planning-fixtures",
        dataset_version=version,
        dataset_revision="rev-a",
    )


def _declared_source() -> InputSourceIdentity:
    return InputSourceIdentity(
        source_id="user-declared-windows",
        source_type=PinnedInputSourceType.USER_DECLARED,
        source_mode=PinnedInputSourceMode.USER_DECLARED,
    )


def _derived_source(version: str = "v1") -> InputSourceIdentity:
    return InputSourceIdentity(
        source_id="derived-declared-windows",
        source_type=PinnedInputSourceType.DERIVED,
        source_mode=PinnedInputSourceMode.DERIVED_FROM_DECLARED_INPUT,
        dataset_name="derived-eligibility-window-set",
        dataset_version=version,
    )


def _fixture_provenance(
    *,
    source: InputSourceIdentity | None = None,
    artifact: PinnedInputArtifact | None = None,
    rights: InputRightsDeclaration | None = None,
    retrieved_at: dt.datetime | None = None,
) -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=source or _fixture_source(),
        artifact=artifact or _artifact(),
        retrieved_at=retrieved_at or dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        rights=rights or _rights(status=InputRightsStatus.VERIFIED),
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _declared_provenance(
    *,
    declared_at: dt.datetime | None = None,
    rights: InputRightsDeclaration | None = None,
) -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=_declared_source(),
        artifact=_artifact("declared"),
        declared_at=declared_at or dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        rights=rights or _rights(status=InputRightsStatus.DECLARED),
        verification_status=ScientificInputVerificationStatus.USER_DECLARED,
    )


def _derived_provenance(parent_checksum: str) -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=_derived_source(),
        artifact=_artifact("derived"),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 5, tzinfo=dt.UTC),
        rights=_rights(status=InputRightsStatus.DECLARED),
        verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
        parent_provenance_checksums=(parent_checksum,),
    )


def _window(
    window_id: str,
    provenance: PinnedInputProvenance,
    *,
    asset_id: str = "SAT-A",
    target_id: str = "T1",
    start_minute: int = 0,
    end_minute: int = 30,
    mode: EligibilityDeclarationMode | None = None,
    checksum: str | None = None,
) -> EligibilityWindow:
    start = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC) + dt.timedelta(minutes=start_minute)
    end = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC) + dt.timedelta(minutes=end_minute)
    if mode is None:
        source_type = provenance.source.source_type
        mode = (
            EligibilityDeclarationMode.FIXTURE_BACKED
            if source_type == PinnedInputSourceType.FIXTURE
            else EligibilityDeclarationMode.USER_DECLARED
            if source_type == PinnedInputSourceType.USER_DECLARED
            else EligibilityDeclarationMode.DERIVED_FROM_DECLARED_INPUT
        )
    return EligibilityWindow(
        id=window_id,
        asset_id=asset_id,
        target_id=target_id,
        start=start,
        end=end,
        source_provenance_checksum=checksum or provenance_checksum(provenance),
        declaration_mode=mode,
        eligibility_reason="declared-candidate-eligibility",
        verification_status=(
            ScientificInputVerificationStatus.FIXTURE_VERIFIED
            if mode == EligibilityDeclarationMode.FIXTURE_BACKED
            else ScientificInputVerificationStatus.USER_DECLARED
            if mode == EligibilityDeclarationMode.USER_DECLARED
            else ScientificInputVerificationStatus.DERIVED_FROM_DECLARED
        ),
    )


def _window_set(
    provenance: PinnedInputProvenance,
    windows: tuple[EligibilityWindow, ...] | None = None,
) -> EligibilityWindowSet:
    return EligibilityWindowSet(
        source_provenance=provenance,
        windows=(
            windows
            if windows is not None
            else (
                _window("W1", provenance),
                _window("W2", provenance, start_minute=40, end_minute=70),
            )
        ),
    )


def test_fixture_provenance_creation() -> None:
    provenance = _fixture_provenance()

    assert provenance.source.source_type == PinnedInputSourceType.FIXTURE
    assert provenance.verification_status == ScientificInputVerificationStatus.FIXTURE_VERIFIED
    assert provenance.checksum == provenance_checksum(provenance)


def test_user_declared_provenance_creation() -> None:
    provenance = _declared_provenance()

    assert provenance.source.source_type == PinnedInputSourceType.USER_DECLARED
    assert provenance.declared_at == dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC)
    assert provenance.verification_status == ScientificInputVerificationStatus.USER_DECLARED


def test_derived_provenance_requires_and_records_parent_checksum() -> None:
    parent = _declared_provenance()
    derived = _derived_provenance(parent.checksum)

    assert derived.source.source_type == PinnedInputSourceType.DERIVED
    assert derived.parent_provenance_checksums == (parent.checksum,)

    with pytest.raises(PydanticValidationError):
        PinnedInputProvenance(
            source=_derived_source(),
            artifact=_artifact("bad-derived"),
            rights=_rights(),
            verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
        )


def test_duplicate_parent_provenance_checksums_rejected() -> None:
    parent = _declared_provenance()

    with pytest.raises(PydanticValidationError):
        PinnedInputProvenance(
            source=_derived_source(),
            artifact=_artifact("duplicate-parent"),
            rights=_rights(),
            verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
            parent_provenance_checksums=(parent.checksum, parent.checksum),
        )


def test_provenance_checksum_is_deterministic() -> None:
    first = _fixture_provenance()
    second = _fixture_provenance()

    assert provenance_checksum(first) == provenance_checksum(second)


def test_provenance_timestamp_utc_equivalence() -> None:
    offset = dt.timezone(dt.timedelta(hours=5, minutes=30))
    utc = _fixture_provenance(retrieved_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC))
    equivalent = _fixture_provenance(retrieved_at=dt.datetime(2026, 6, 21, 14, 30, tzinfo=offset))

    assert utc.retrieved_at == equivalent.retrieved_at
    assert utc.checksum == equivalent.checksum


def test_source_version_change_alters_provenance_checksum() -> None:
    first = _fixture_provenance(source=_fixture_source(version="v1"))
    second = _fixture_provenance(source=_fixture_source(version="v2"))

    assert first.checksum != second.checksum


def test_content_checksum_change_alters_provenance_checksum() -> None:
    first = _fixture_provenance(artifact=_artifact("content-a"))
    second = _fixture_provenance(artifact=_artifact("content-b"))

    assert first.checksum != second.checksum


def test_rights_declaration_is_included_in_identity() -> None:
    declared = _fixture_provenance(rights=_rights(status=InputRightsStatus.DECLARED))
    restricted = _fixture_provenance(
        rights=_rights(
            status=InputRightsStatus.RESTRICTED,
            redistribution=InputRightsPermission.RESTRICTED,
        )
    )

    assert declared.checksum != restricted.checksum


def test_unknown_rights_remain_explicit() -> None:
    rights = _rights(status=InputRightsStatus.UNKNOWN)
    provenance = _declared_provenance(rights=rights)

    assert provenance.rights.rights_status == InputRightsStatus.UNKNOWN
    assert provenance.rights.commercial_use == InputRightsPermission.UNKNOWN


def test_restricted_rights_reject_direct_permission_contradictions() -> None:
    with pytest.raises(PydanticValidationError):
        _rights(
            status=InputRightsStatus.RESTRICTED,
            redistribution=InputRightsPermission.PERMITTED,
        )

    with pytest.raises(PydanticValidationError):
        InputRightsDeclaration(
            rights_status=InputRightsStatus.RESTRICTED,
            commercial_use=InputRightsPermission.PERMITTED,
            limitations=("restricted but contradictory",),
        )


def test_invalid_checksum_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        PinnedInputArtifact(
            artifact_id="bad",
            content_checksum="not-a-sha256",
            media_type="application/json",
        )


def test_unsupported_schema_version_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        PinnedInputProvenance(
            schema_version="2",  # type: ignore[arg-type]
            source=_fixture_source(),
            artifact=_artifact(),
            rights=_rights(status=InputRightsStatus.VERIFIED),
            verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
        )


def test_eligibility_window_creation_normalizes_time() -> None:
    provenance = _fixture_provenance()
    offset = dt.timezone(dt.timedelta(hours=5))
    window = EligibilityWindow(
        id="W1",
        asset_id="SAT-A",
        target_id="T1",
        start=dt.datetime(2026, 6, 21, 15, 0, tzinfo=offset),
        end=dt.datetime(2026, 6, 21, 15, 30, tzinfo=offset),
        source_provenance_checksum=provenance.checksum,
        declaration_mode=EligibilityDeclarationMode.FIXTURE_BACKED,
        eligibility_reason="fixture-candidate",
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )

    assert window.start == dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    assert window.end == dt.datetime(2026, 6, 21, 10, 30, tzinfo=dt.UTC)


def test_eligibility_window_rejects_naive_timestamp() -> None:
    provenance = _fixture_provenance()

    with pytest.raises(PydanticValidationError):
        EligibilityWindow(
            id="W1",
            asset_id="SAT-A",
            target_id="T1",
            start=dt.datetime(2026, 6, 21, 10, 0),
            end=dt.datetime(2026, 6, 21, 10, 30, tzinfo=dt.UTC),
            source_provenance_checksum=provenance.checksum,
            declaration_mode=EligibilityDeclarationMode.FIXTURE_BACKED,
            eligibility_reason="fixture-candidate",
            verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
        )


def test_eligibility_window_rejects_reversed_or_zero_duration() -> None:
    provenance = _fixture_provenance()

    with pytest.raises(PydanticValidationError):
        _window("W1", provenance, start_minute=30, end_minute=30)
    with pytest.raises(PydanticValidationError):
        _window("W2", provenance, start_minute=40, end_minute=30)


def test_eligibility_window_rejects_excessive_duration() -> None:
    provenance = _fixture_provenance()

    with pytest.raises(PydanticValidationError):
        _window("W1", provenance, start_minute=0, end_minute=(48 * 60) + 1)


def test_eligibility_set_rejects_duplicate_window_id() -> None:
    provenance = _fixture_provenance()
    first = _window("W1", provenance)
    duplicate = _window("W1", provenance, start_minute=40, end_minute=70)

    with pytest.raises(PydanticValidationError):
        _window_set(provenance, (first, duplicate))


def test_eligibility_set_rejects_duplicate_scientific_window() -> None:
    provenance = _fixture_provenance()
    first = _window("W1", provenance)
    duplicate = _window("W2", provenance)

    with pytest.raises(PydanticValidationError):
        _window_set(provenance, (first, duplicate))


def test_overlapping_non_identical_eligibility_windows_are_accepted() -> None:
    provenance = _fixture_provenance()
    first = _window("W1", provenance, target_id="T1", start_minute=0, end_minute=30)
    overlapping = _window("W2", provenance, target_id="T2", start_minute=10, end_minute=40)

    window_set = _window_set(provenance, (first, overlapping))

    assert len(window_set.windows) == 2


def test_eligibility_set_bounds_total_window_count() -> None:
    provenance = _fixture_provenance()
    windows = tuple(
        _window(f"W{i}", provenance, start_minute=i * 2, end_minute=(i * 2) + 1) for i in range(25)
    )

    with pytest.raises(PydanticValidationError):
        _window_set(provenance, windows)


def test_equivalent_input_ordering_yields_stable_set_checksum() -> None:
    provenance = _fixture_provenance()
    first = _window("W1", provenance)
    second = _window("W2", provenance, start_minute=40, end_minute=70)

    first_set = _window_set(provenance, (first, second))
    second_set = _window_set(provenance, (second, first))

    assert first_set.checksum == second_set.checksum
    assert first_set.checksum == eligibility_window_set_checksum(first_set)


def test_changed_window_alters_set_checksum() -> None:
    provenance = _fixture_provenance()
    original = _window_set(provenance, (_window("W1", provenance),))
    changed = _window_set(provenance, (_window("W1", provenance, start_minute=1, end_minute=31),))

    assert original.checksum != changed.checksum


def test_wrong_provenance_reference_rejected() -> None:
    provenance = _fixture_provenance()
    window = _window("W1", provenance, checksum=_checksum("other-provenance"))

    with pytest.raises(PydanticValidationError):
        _window_set(provenance, (window,))


def test_derived_window_provenance_chain_is_accepted() -> None:
    parent = _declared_provenance()
    derived = _derived_provenance(parent.checksum)
    window = _window(
        "W1",
        derived,
        mode=EligibilityDeclarationMode.DERIVED_FROM_DECLARED_INPUT,
        checksum=parent.checksum,
    )

    window_set = _window_set(derived, (window,))

    assert window_set.windows[0].source_provenance_checksum == parent.checksum


def test_fixture_eligibility_conversion_is_deterministic() -> None:
    window_set = _window_set(_fixture_provenance())

    first = eligibility_windows_to_opportunities(window_set)
    second = eligibility_windows_to_opportunities(window_set)

    assert first == second
    assert first[0].source == "declared-eligibility:fixture_backed"


def test_user_declared_eligibility_conversion_is_deterministic() -> None:
    provenance = _declared_provenance()
    window_set = _window_set(provenance, (_window("W1", provenance),))

    first = eligibility_windows_to_opportunities(window_set, mission_value=2.0)
    second = eligibility_windows_to_opportunities(window_set, mission_value=2.0)

    assert first == second
    assert first[0].source == "declared-eligibility:user_declared"


def test_empty_eligibility_window_set_conversion_returns_empty_tuple() -> None:
    window_set = _window_set(_fixture_provenance(), ())

    assert eligibility_windows_to_opportunities(window_set) == ()


def test_conversion_uses_deterministic_default_mission_value() -> None:
    provenance = _fixture_provenance()
    window_set = _window_set(provenance, (_window("W1", provenance),))

    opportunity = eligibility_windows_to_opportunities(window_set)[0]

    assert opportunity.mission_value == 1.0


def test_conversion_respects_the_24_variable_request_maximum() -> None:
    provenance = _fixture_provenance()
    windows = tuple(
        _window(f"W{i}", provenance, start_minute=i * 2, end_minute=(i * 2) + 1) for i in range(24)
    )
    window_set = _window_set(provenance, windows)

    opportunities = eligibility_windows_to_opportunities(window_set)

    assert len(opportunities) == 24


def test_conversion_preserves_asset_target_and_time_identity() -> None:
    provenance = _declared_provenance()
    window = _window(
        "W1",
        provenance,
        asset_id="SAT-Z",
        target_id="TARGET-Z",
        start_minute=5,
        end_minute=25,
    )
    opportunity = eligibility_windows_to_opportunities(_window_set(provenance, (window,)))[0]

    assert opportunity.satellite_id == "SAT-Z"
    assert opportunity.target_id == "TARGET-Z"
    assert opportunity.window.start == window.start
    assert opportunity.window.end == window.end


def test_validate_request_against_eligibility_uses_declared_scientific_identity() -> None:
    provenance = _declared_provenance()
    window_set = _window_set(provenance, (_window("W1", provenance),))
    opportunity = eligibility_windows_to_opportunities(window_set)[0]
    request = ObservationPlanningRequest(
        name="declared from eligibility",
        horizon=PlanningHorizon(
            start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        ),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=(opportunity,),
        satellites=(
            SatelliteResource(
                id=opportunity.satellite_id,
                energy_capacity=10.0,
                storage_capacity=10.0,
            ),
        ),
        targets=(ObservationTarget(id=opportunity.target_id),),
    )

    validate_request_against_eligibility(request, window_set)

    mismatched = request.model_copy(
        update={"opportunities": (opportunity.model_copy(update={"satellite_id": "OTHER-SAT"}),)}
    )
    with pytest.raises(ValidationError):
        validate_request_against_eligibility(mismatched, window_set)


def test_validate_request_against_eligibility_allows_subset_requests() -> None:
    provenance = _declared_provenance()
    windows = (
        _window("W1", provenance),
        _window("W2", provenance, start_minute=40, end_minute=70),
    )
    window_set = _window_set(provenance, windows)
    first_opportunity = eligibility_windows_to_opportunities(window_set)[0]
    request = ObservationPlanningRequest(
        name="declared subset from eligibility",
        horizon=PlanningHorizon(
            start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        ),
        source_mode=ObservationPlanningSourceMode.DECLARED,
        fixture_name=None,
        opportunities=(first_opportunity,),
        satellites=(
            SatelliteResource(
                id=first_opportunity.satellite_id,
                energy_capacity=10.0,
                storage_capacity=10.0,
            ),
        ),
        targets=(ObservationTarget(id=first_opportunity.target_id),),
    )

    validate_request_against_eligibility(request, window_set)


def test_provenance_module_does_not_import_geometry_providers_or_quantum() -> None:
    source = inspect.getsource(provenance_module)

    assert "orbitmind.space" not in source
    assert "orbitmind.sources" not in source
    assert "orbitmind.quantum" not in source


def test_limitations_do_not_make_operational_claims() -> None:
    provenance = _fixture_provenance()
    window_set = _window_set(provenance)
    joined = " ".join((*provenance.limitations, *window_set.limitations)).lower()

    for forbidden in (
        "operationally verified",
        "access confirmed",
        "verified visibility",
        "line of sight confirmed",
        "taskable",
        "command approved",
        "live validated",
    ):
        assert forbidden not in joined

    with pytest.raises(PydanticValidationError):
        EligibilityWindow(
            id="W1",
            asset_id="SAT-A",
            target_id="T1",
            start=dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 6, 21, 10, 30, tzinfo=dt.UTC),
            source_provenance_checksum=provenance.checksum,
            declaration_mode=EligibilityDeclarationMode.FIXTURE_BACKED,
            eligibility_reason="fixture-candidate",
            verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
            limitations=("access confirmed for this asset",),
        )


def test_frozen_model_mutation_rejected() -> None:
    provenance = _fixture_provenance()

    with pytest.raises(PydanticValidationError):
        provenance.artifact = _artifact("other")  # type: ignore[misc]
