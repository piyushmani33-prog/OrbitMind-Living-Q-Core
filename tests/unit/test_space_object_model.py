"""Unit tests for the unified space-object model and orbit separation."""

from __future__ import annotations

from orbitmind.objects.models import IMPLEMENTED_KINDS, SpaceObject, SpaceObjectKind
from orbitmind.objects.orbits import EarthOrbitElements, SmallBodyOrbitElements


def test_only_asteroid_and_comet_are_implemented() -> None:
    assert frozenset({SpaceObjectKind.ASTEROID, SpaceObjectKind.COMET}) == IMPLEMENTED_KINDS
    # All 15 kinds exist for future compatibility.
    assert len(list(SpaceObjectKind)) == 15


def test_orbit_representations_are_distinct() -> None:
    earth = EarthOrbitElements(tle_line1="1 ...", tle_line2="2 ...")
    small = SmallBodyOrbitElements(semimajor_axis_au=1.458, eccentricity=0.22)
    assert earth.representation == "earth-orbit-tle"
    assert small.representation == "small-body-heliocentric"
    # Small-body elements have NO TLE fields (asteroids are not satellites).
    assert not hasattr(small, "tle_line1")
    # Earth orbit elements have NO heliocentric fields.
    assert not hasattr(earth, "semimajor_axis_au")


def test_space_object_has_no_single_satellite_id() -> None:
    assert "satellite_id" not in SpaceObject.model_fields
    # Identity is carried by a structured identifier, not a flat satellite_id.
    assert "identity" in SpaceObject.model_fields


def test_small_body_units_are_explicit() -> None:
    small = SmallBodyOrbitElements()
    assert small.units["semimajor_axis_au"] == "au"
    assert small.units["inclination_deg"] == "degrees"
    # Missing values are None, never zero.
    assert small.eccentricity is None
