"""Contract tests for the Laboratory Manifest and capability declarations."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from orbitmind.laboratory.capabilities import (
    CAPABILITY_IS_NOT_PERMISSION,
    ApprovalPosture,
    CapabilityDeclaration,
    CapabilityDeterminism,
    ExecutionAuthority,
    LabCapability,
)
from orbitmind.laboratory.contracts import (
    LABORATORY_MANIFEST_SCHEMA_VERSION,
    ApprovalGate,
    CompatibilityInfo,
    HardwarePosture,
    LaboratoryDomain,
    LaboratoryImplementationStatus,
    LaboratoryManifest,
    NetworkPosture,
    PersistencePosture,
    ReplayRequirement,
    ResourceBoundaries,
)


def _declaration(
    capability: LabCapability = LabCapability.REPOSITORY_READ,
) -> CapabilityDeclaration:
    return CapabilityDeclaration(
        capability=capability,
        approval_posture=ApprovalPosture.MISSION_APPROVAL_REQUIRED,
        determinism=CapabilityDeterminism.DETERMINISTIC,
        summary="Declared for contract tests; no tool is connected.",
    )


def _manifest_kwargs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "laboratory_id": "test-laboratory",
        "display_name": "Test Laboratory",
        "laboratory_version": "0.1.0",
        "domain": LaboratoryDomain.DEVELOPMENT,
        "description": "A minimal valid manifest for contract tests.",
        "implementation_status": LaboratoryImplementationStatus.CATALOG_FOUNDATION,
        "capabilities": (_declaration(),),
        "accepted_goal_categories": ("test-goal",),
        "required_deterministic_services": ("verification",),
        "produced_artifact_categories": ("test-report",),
        "produced_evidence_categories": ("test-evidence",),
        "network_posture": NetworkPosture.OFFLINE_ONLY,
        "hardware_posture": HardwarePosture.NO_HARDWARE_ACCESS,
        "persistence_posture": PersistencePosture.NO_LABORATORY_PERSISTENCE,
        "approval_gates": (ApprovalGate.REPOSITORY_WRITE,),
        "replay_support": ReplayRequirement.DETERMINISTIC_REPLAY_REQUIRED,
        "verification_requirements": ("Outputs must pass verification.",),
        "resource_boundaries": ResourceBoundaries(
            max_concurrent_missions=1,
            max_mission_wall_clock_seconds=60,
            notes="Bounds for contract tests.",
        ),
        "compatibility": CompatibilityInfo(
            platform_version_baseline="0.1.0",
            mission_contract="Reuses the Mission aggregate.",
        ),
        "limitations": ("Nothing executes in this contract-test manifest.",),
    }
    base.update(overrides)
    return base


def _manifest(**overrides: Any) -> LaboratoryManifest:
    return LaboratoryManifest(**_manifest_kwargs(**overrides))


# --- strict validation -------------------------------------------------------


def test_manifest_pins_schema_version() -> None:
    manifest = _manifest()
    assert manifest.schema_version == LABORATORY_MANIFEST_SCHEMA_VERSION
    with pytest.raises(ValidationError):
        _manifest(schema_version="laboratory-manifest-v999")


def test_manifest_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        _manifest(surprise_field="not allowed")


@pytest.mark.parametrize(
    "bad_id",
    ["", "X", "UPPER-CASE", "has space", "a" * 60, "../escape", "dotted.name", "under_score"],
)
def test_manifest_rejects_invalid_identifiers(bad_id: str) -> None:
    with pytest.raises(ValidationError):
        _manifest(laboratory_id=bad_id)


def test_manifest_rejects_unbounded_strings_and_collections() -> None:
    with pytest.raises(ValidationError):
        _manifest(description="x" * 601)
    with pytest.raises(ValidationError):
        _manifest(display_name="")
    with pytest.raises(ValidationError):
        _manifest(accepted_goal_categories=tuple(f"goal-{index}" for index in range(13)))
    with pytest.raises(ValidationError):
        _manifest(limitations=())  # limitations are mandatory honesty
    with pytest.raises(ValidationError):
        _manifest(verification_requirements=())


def test_manifest_rejects_pathlike_category_tokens() -> None:
    """Category tokens can never smuggle paths, dots or executable references."""
    for bad_token in ("../up", "pkg.module", "a/b", "cmd exe", "Weird"):
        with pytest.raises(ValidationError):
            _manifest(produced_artifact_categories=(bad_token,))


def test_manifest_is_immutable() -> None:
    manifest = _manifest()
    with pytest.raises(ValidationError):
        manifest.display_name = "Mutated"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        manifest.capabilities = ()  # type: ignore[misc]


def test_capability_declaration_is_immutable() -> None:
    declaration = _declaration()
    with pytest.raises(ValidationError):
        declaration.approval_posture = ApprovalPosture.LOCALLY_SAFE  # type: ignore[misc]


# --- capability semantics ----------------------------------------------------


def test_capability_declaration_never_grants_anything() -> None:
    declaration = _declaration()
    assert declaration.grants_permission is False
    assert declaration.tool_connected is False
    assert declaration.adapter_connected is False
    assert declaration.execution_authority is ExecutionAuthority.NONE
    assert "does not grant permission" in CAPABILITY_IS_NOT_PERMISSION


def test_capability_declaration_cannot_claim_connected_tools_or_authority() -> None:
    """v1 pins tool/adapter/authority to their only truthful values."""
    with pytest.raises(ValidationError):
        CapabilityDeclaration(
            capability=LabCapability.REPOSITORY_WRITE,
            approval_posture=ApprovalPosture.ACTION_APPROVAL_REQUIRED,
            determinism=CapabilityDeterminism.DETERMINISTIC,
            summary="Attempting to claim a connected tool.",
            tool_connected=True,  # type: ignore[arg-type]
        )
    with pytest.raises(ValidationError):
        CapabilityDeclaration(
            capability=LabCapability.REPOSITORY_WRITE,
            approval_posture=ApprovalPosture.ACTION_APPROVAL_REQUIRED,
            determinism=CapabilityDeterminism.DETERMINISTIC,
            summary="Attempting to claim a connected adapter.",
            adapter_connected=True,  # type: ignore[arg-type]
        )


def test_manifest_rejects_duplicate_capability_declarations() -> None:
    with pytest.raises(ValidationError):
        _manifest(capabilities=(_declaration(), _declaration()))


def test_approval_posture_vocabulary_is_explicit() -> None:
    assert {posture.value for posture in ApprovalPosture} == {
        "locally_safe",
        "mission_approval_required",
        "action_approval_required",
        "prohibited_by_default",
    }


# --- deterministic ordering + stable serialization ---------------------------


def test_manifest_normalizes_collections_to_sorted_order() -> None:
    manifest = _manifest(
        capabilities=(
            _declaration(LabCapability.TEST_EXECUTE),
            _declaration(LabCapability.REPOSITORY_READ),
        ),
        approval_gates=(ApprovalGate.PUSH, ApprovalGate.COMMIT),
        produced_artifact_categories=("zeta-report", "alpha-report"),
    )
    assert [d.capability for d in manifest.capabilities] == [
        LabCapability.REPOSITORY_READ,
        LabCapability.TEST_EXECUTE,
    ]
    assert manifest.approval_gates == (ApprovalGate.COMMIT, ApprovalGate.PUSH)
    assert manifest.produced_artifact_categories == ("alpha-report", "zeta-report")


def test_manifest_serialization_is_stable() -> None:
    ordered = _manifest(produced_artifact_categories=("alpha-report", "zeta-report"))
    shuffled = _manifest(produced_artifact_categories=("zeta-report", "alpha-report"))
    assert ordered.canonical_json() == shuffled.canonical_json()
    assert ordered.canonical_json() == ordered.canonical_json()
    round_trip = LaboratoryManifest.model_validate_json(ordered.canonical_json())
    assert round_trip == ordered


def test_manifest_carries_no_executable_references() -> None:
    """No import path, command or filesystem reference appears in a manifest."""
    serialized = _manifest().canonical_json()
    for marker in ("orbitmind.", "src/", "src\\\\", ".py", "subprocess", "import "):
        assert marker not in serialized
