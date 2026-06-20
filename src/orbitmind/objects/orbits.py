"""Orbit/position representations — a tagged union, one per object class.

Each object class keeps a distinct representation so scientific differences are not
collapsed (ADR-0016). Asteroid/comet elements are heliocentric Keplerian; satellite
elements are TLE/GP. Missing values are ``None`` — never silently zero.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

# Canonical units for each field (explicit, documented).
SMALL_BODY_UNITS: dict[str, str] = {
    "eccentricity": "dimensionless",
    "semimajor_axis_au": "au",
    "perihelion_distance_au": "au",
    "aphelion_distance_au": "au",
    "inclination_deg": "degrees",
    "ascending_node_deg": "degrees",
    "arg_perihelion_deg": "degrees",
    "mean_anomaly_deg": "degrees",
    "orbital_period_days": "days",
    "mean_motion_deg_per_day": "degrees/day",
    "time_of_perihelion_jd": "JD (TDB)",
    "epoch_jd": "JD (TDB)",
}


class EarthOrbitElements(BaseModel):
    """Satellite/debris TLE/GP representation (SGP4 applies). Not used for small bodies."""

    model_config = ConfigDict(frozen=True)

    representation: Literal["earth-orbit-tle"] = "earth-orbit-tle"
    tle_line1: str
    tle_line2: str
    epoch_utc: str | None = None


class SmallBodyOrbitElements(BaseModel):
    """Heliocentric Keplerian elements for asteroids/comets (SGP4 MUST NOT be used)."""

    model_config = ConfigDict(frozen=True)

    representation: Literal["small-body-heliocentric"] = "small-body-heliocentric"
    epoch_jd: float | None = None
    eccentricity: float | None = None
    semimajor_axis_au: float | None = None
    perihelion_distance_au: float | None = None
    aphelion_distance_au: float | None = None
    inclination_deg: float | None = None
    ascending_node_deg: float | None = None
    arg_perihelion_deg: float | None = None
    mean_anomaly_deg: float | None = None
    orbital_period_days: float | None = None
    mean_motion_deg_per_day: float | None = None
    time_of_perihelion_jd: float | None = None
    units: dict[str, str] = Field(default_factory=lambda: dict(SMALL_BODY_UNITS))


class PlanetaryEphemerisReference(BaseModel):
    """Future: a reference to a planetary ephemeris (Horizons/SPICE). Not implemented."""

    model_config = ConfigDict(frozen=True)

    representation: Literal["planetary-ephemeris-ref"] = "planetary-ephemeris-ref"
    body_id: str
    ephemeris: str | None = None


class FixedSkyCoordinateReference(BaseModel):
    """Future: fixed-sky coordinates for stars/galaxies. Not implemented."""

    model_config = ConfigDict(frozen=True)

    representation: Literal["fixed-sky-coordinate"] = "fixed-sky-coordinate"
    ra_deg: float | None = None
    dec_deg: float | None = None
    frame: str = "ICRS"


class SignalSourceReference(BaseModel):
    """Future: a reference to a time-series/spectral signal source. Not implemented."""

    model_config = ConfigDict(frozen=True)

    representation: Literal["signal-source-ref"] = "signal-source-ref"
    locator: str


OrbitRepresentation = Annotated[
    EarthOrbitElements
    | SmallBodyOrbitElements
    | PlanetaryEphemerisReference
    | FixedSkyCoordinateReference
    | SignalSourceReference,
    Field(discriminator="representation"),
]
