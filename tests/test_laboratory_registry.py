"""Behavioral tests for the deterministic in-process Laboratory Registry."""

from __future__ import annotations

import pytest

from orbitmind.core.errors import ValidationError as DomainValidationError
from orbitmind.laboratory.catalog import (
    build_catalog_projection,
    build_default_registry,
    build_development_laboratory_manifest,
)
from orbitmind.laboratory.registry import (
    DuplicateLaboratoryError,
    LaboratoryRegistry,
    UnknownLaboratoryError,
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
    for declaration in manifest.capabilities:
        assert declaration.tool_connected is False
        assert declaration.adapter_connected is False
        assert declaration.grants_permission is False
