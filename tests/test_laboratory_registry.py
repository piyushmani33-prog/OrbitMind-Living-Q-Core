"""Behavioral tests for the deterministic in-process Laboratory Registry."""

from __future__ import annotations

import pytest

from orbitmind.core.errors import ValidationError as DomainValidationError
from orbitmind.laboratory.catalog import (
    build_catalog_digest,
    build_catalog_projection,
    build_default_registry,
    build_development_laboratory_manifest,
    canonical_catalog_json,
    canonical_catalog_payload,
)
from orbitmind.laboratory.contracts import (
    LABORATORY_FRAMEWORK_CONTRACT_VERSION,
    AdapterDeclaration,
    ApprovalGate,
    CompatibilityInfo,
    DeprecationState,
    FrameworkCompatibilityRange,
    LaboratoryDomain,
    LaboratoryImplementationStatus,
    NetworkPosture,
    PersistencePosture,
    ReplayRequirement,
    ResourceBoundaries,
)
from orbitmind.laboratory.registry import (
    DuplicateLaboratoryError,
    IncompatibleLaboratoryFrameworkError,
    LaboratoryRegistry,
    UnknownLaboratoryError,
    UnsupportedLaboratoryManifestSchemaError,
)


def test_explicit_registration_and_lookup() -> None:
    registry = LaboratoryRegistry()
    manifest = build_development_laboratory_manifest()
    assert len(registry) == 0
    registry.register(manifest)
    assert len(registry) == 1
    assert "development-laboratory" in registry
    assert registry.get("development-laboratory") == manifest


def test_listing_is_deterministic_regardless_of_registration_order() -> None:
    first = build_development_laboratory_manifest()
    second = first.model_copy(update={"laboratory_id": "aaa-laboratory"})

    forward = LaboratoryRegistry()
    forward.register(first)
    forward.register(second)
    backward = LaboratoryRegistry()
    backward.register(second)
    backward.register(first)

    expected_ids = ["aaa-laboratory", "development-laboratory"]
    assert [m.laboratory_id for m in forward.list_manifests()] == expected_ids
    assert [m.laboratory_id for m in backward.list_manifests()] == expected_ids
    assert forward.list_manifests() == backward.list_manifests()


def test_duplicate_registration_is_rejected() -> None:
    registry = LaboratoryRegistry()
    registry.register(build_development_laboratory_manifest())
    with pytest.raises(DuplicateLaboratoryError):
        registry.register(build_development_laboratory_manifest())
    assert len(registry) == 1


def test_incompatible_manifest_is_rejected_without_partial_registration() -> None:
    registry = LaboratoryRegistry()
    incompatible = build_development_laboratory_manifest().model_copy(
        update={
            "framework_compatibility": FrameworkCompatibilityRange(
                minimum_inclusive="2.0.0",
                maximum_exclusive="3.0.0",
            )
        }
    )

    with pytest.raises(IncompatibleLaboratoryFrameworkError) as excinfo:
        registry.register(incompatible)

    assert excinfo.value.code == "incompatible_laboratory_framework"
    assert len(registry) == 0
    assert registry.list_manifests() == ()


def test_unsupported_schema_is_rejected_without_partial_registration() -> None:
    registry = LaboratoryRegistry()
    unsupported = build_development_laboratory_manifest().model_copy(
        update={"schema_version": "laboratory-manifest-v999"}
    )

    with pytest.raises(UnsupportedLaboratoryManifestSchemaError) as excinfo:
        registry.register(unsupported)

    assert excinfo.value.code == "unsupported_laboratory_manifest_schema"
    assert len(registry) == 0


def test_non_manifest_registration_is_rejected() -> None:
    registry = LaboratoryRegistry()
    with pytest.raises(DomainValidationError):
        registry.register({"laboratory_id": "sneaky"})  # type: ignore[arg-type]


def test_unknown_lookup_raises_safe_not_found() -> None:
    registry = build_default_registry()
    with pytest.raises(UnknownLaboratoryError) as excinfo:
        registry.get("no-such-laboratory")
    assert excinfo.value.http_status == 404
    assert excinfo.value.message == "laboratory not found"


def test_registry_instances_are_isolated() -> None:
    populated = build_default_registry()
    empty = LaboratoryRegistry()
    assert len(populated) == 1
    assert len(empty) == 0
    empty.register(build_development_laboratory_manifest())
    assert len(populated) == 1  # no shared/global state between instances


def test_registered_records_are_immutable() -> None:
    registry = build_default_registry()
    manifest = registry.get("development-laboratory")
    with pytest.raises(Exception, match="frozen"):
        manifest.display_name = "Mutated"  # type: ignore[misc]
    assert registry.get("development-laboratory").display_name == "Development Laboratory"


def test_registry_has_no_execution_activation_or_grant_surface() -> None:
    registry = build_default_registry()
    public_api = {name for name in dir(registry) if not name.startswith("_")}
    assert public_api == {"register", "list_manifests", "get"}
    forbidden = {"execute", "run", "activate", "grant", "install", "load", "discover", "spawn"}
    assert not (public_api & forbidden)


def test_default_registry_registers_exactly_the_development_laboratory() -> None:
    registry = build_default_registry()
    assert [m.laboratory_id for m in registry.list_manifests()] == ["development-laboratory"]


def test_catalog_projection_is_deterministic_and_registry_derived() -> None:
    first = build_catalog_projection(build_default_registry())
    second = build_catalog_projection(build_default_registry())
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.generated_from == "deterministic-laboratory-registry"
    assert [m.laboratory_id for m in first.laboratories] == ["development-laboratory"]
    # Planned laboratories are roadmap metadata, never registry members.
    planned_ids = {p.laboratory_id for p in first.planned_laboratories}
    assert planned_ids == {
        "research-laboratory",
        "quantum-laboratory",
        "robotics-laboratory",
        "space-laboratory",
        "manufacturing-laboratory",
    }
    registry = build_default_registry()
    for planned_id in planned_ids:
        assert planned_id not in registry


def test_development_laboratory_manifest_is_truthful() -> None:
    manifest = build_development_laboratory_manifest()
    limitations = " ".join(manifest.limitations)
    assert "No agent runtime is connected." in manifest.limitations
    assert "No autonomous development occurs." in manifest.limitations
    assert "No external AI adapter is connected." in manifest.limitations
    assert "human-authorized" in limitations
    assert "catalog and governance foundations only" in limitations
    assert manifest.framework_compatibility.contains(LABORATORY_FRAMEWORK_CONTRACT_VERSION)
    for declaration in manifest.capabilities:
        assert declaration.tool_connected is False
        assert declaration.adapter_connected is False
        assert declaration.grants_permission is False


def test_catalog_digest_is_deterministic_order_independent_and_side_effect_free() -> None:
    first = build_development_laboratory_manifest()
    second = first.model_copy(update={"laboratory_id": "aaa-laboratory"})
    forward = LaboratoryRegistry()
    backward = LaboratoryRegistry()
    for manifest in (first, second):
        forward.register(manifest)
    for manifest in (second, first):
        backward.register(manifest)

    before = forward.list_manifests()
    forward_digest = build_catalog_digest(before)
    backward_digest = build_catalog_digest(backward.list_manifests())

    assert forward_digest.algorithm == "sha256"
    assert len(forward_digest.value) == 64
    assert forward_digest.value == forward_digest.value.lower()
    assert forward_digest == backward_digest
    assert build_catalog_digest(before) == forward_digest
    assert forward.list_manifests() == before


def test_catalog_digest_changes_with_every_manifest_semantic_field() -> None:
    manifest = build_development_laboratory_manifest()
    baseline = build_catalog_digest((manifest,))
    canonical_manifest = canonical_catalog_payload((manifest,))["laboratories"]
    assert canonical_manifest == [manifest.model_dump(mode="json")]
    assert build_catalog_digest(()) != baseline
    assert (
        build_catalog_digest(
            (manifest, manifest.model_copy(update={"laboratory_id": "aaa-laboratory"}))
        )
        != baseline
    )

    changes = {
        "schema_version": "laboratory-manifest-v999",
        "laboratory_id": "changed-laboratory",
        "display_name": "Changed Laboratory",
        "laboratory_version": "0.1.1",
        "domain": LaboratoryDomain.RESEARCH,
        "description": "Changed laboratory description.",
        "implementation_status": LaboratoryImplementationStatus.PLANNED,
        "capabilities": (),
        "accepted_goal_categories": ("changed-goal",),
        "required_deterministic_services": ("changed-service",),
        "adapters": (
            AdapterDeclaration(
                adapter_id="changed-adapter",
                purpose="Changed catalog-only adapter declaration.",
                approval_posture_note="Still disconnected and non-executing.",
            ),
        ),
        "produced_artifact_categories": ("changed-artifact",),
        "produced_evidence_categories": ("changed-evidence",),
        "network_posture": NetworkPosture.PERMISSIONED_WINDOW_REQUIRED,
        "persistence_posture": PersistencePosture.READS_EXISTING_RECORDS_ONLY,
        "approval_gates": (ApprovalGate.CLOUD_SERVICE,),
        "replay_support": ReplayRequirement.NOT_APPLICABLE,
        "verification_requirements": ("Changed verification requirement.",),
        "resource_boundaries": ResourceBoundaries(
            max_concurrent_missions=2,
            max_mission_wall_clock_seconds=3_601,
            notes="Changed declared resource bounds.",
        ),
        "framework_compatibility": FrameworkCompatibilityRange(
            minimum_inclusive="1.0.0",
            maximum_exclusive="1.9.9",
        ),
        "compatibility": CompatibilityInfo(
            platform_version_baseline="0.1.1",
            mission_contract="Changed Mission contract statement.",
        ),
        "limitations": ("Changed limitation statement.",),
        "deprecation_state": DeprecationState.DEPRECATED,
    }

    for field, value in changes.items():
        changed = manifest.model_copy(update={field: value})
        assert build_catalog_digest((changed,)) != baseline, field


def test_catalog_digest_golden_vector_and_empty_catalog_contract() -> None:
    canonical_empty = canonical_catalog_json(())
    assert canonical_catalog_payload(()) == {
        "catalog_digest_format_version": "laboratory-catalog-digest-v1",
        "catalog_schema_version": "laboratory-catalog-v1",
        "framework_contract_version": "1.0.0",
        "supported_manifest_schema_versions": ["laboratory-manifest-v1"],
        "laboratories": [],
    }
    assert canonical_empty == (
        '{"catalog_digest_format_version":"laboratory-catalog-digest-v1",'
        '"catalog_schema_version":"laboratory-catalog-v1",'
        '"framework_contract_version":"1.0.0","laboratories":[],'
        '"supported_manifest_schema_versions":["laboratory-manifest-v1"]}'
    )
    assert (
        build_catalog_digest(()).value
        == "76d0070395bb1b1e5a6a4fdea9b1b7fcc18743ac991e936de5179406cd1396ad"
    )
