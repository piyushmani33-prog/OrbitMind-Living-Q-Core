"""Orbital domain models: source record, state sample, scientific result."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.core.units import UNITS
from orbitmind.governance.epistemic import EpistemicStatus


class SampleStatus(StrEnum):
    """Per-sample propagation status."""

    OK = "ok"
    ERROR = "error"


class OrbitalSourceRecord(BaseModel):
    """Provenance of a bundled orbital element set (TLE fixture)."""

    model_config = ConfigDict(frozen=True)

    satellite_id: str
    name: str
    norad_cat_id: int | None = None
    source_name: str
    source_url: str
    epoch_utc: str
    fixture_created: str
    data_use_note: str
    checksum: str
    test_only: bool = True
    # An element set is an assumption/model-estimate input, not live truth (SR-05).
    epistemic_status: EpistemicStatus = EpistemicStatus.ASSUMPTION


class Vector3(BaseModel):
    """A 3-D vector with explicit component fields."""

    model_config = ConfigDict(frozen=True)

    x: float
    y: float
    z: float


class OrbitalStateSample(BaseModel):
    """A single propagated state at one UTC instant."""

    model_config = ConfigDict(frozen=True)

    timestamp: datetime
    position_km: Vector3 | None = None  # TEME
    velocity_kmps: Vector3 | None = None  # TEME
    latitude_deg: float | None = None
    longitude_deg: float | None = None
    altitude_km: float | None = None
    status: SampleStatus = SampleStatus.OK
    error: str | None = None


class ScientificResult(BaseModel):
    """Aggregate result of an orbital propagation (deterministic calculation)."""

    mission_id: str
    satellite_id: str
    samples: list[OrbitalStateSample]
    computation_version: str
    software_versions: dict[str, str]
    units: dict[str, str] = Field(default_factory=lambda: dict(UNITS))
    source: OrbitalSourceRecord
    summary: dict[str, float] = Field(default_factory=dict)
    # SGP4 output is a deterministic computation (and a model of reality).
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION

    @property
    def ok_samples(self) -> list[OrbitalStateSample]:
        return [s for s in self.samples if s.status is SampleStatus.OK]
