"""JPL SBDB lookup response models (source-specific; do not leak outward).

JPL returns most numeric values as strings and a few flags as booleans. These
models validate the structure; conversion to typed domain values happens in
``normalization``.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class SbdbOutcome(StrEnum):
    """Classification of an SBDB lookup response."""

    FOUND = "found"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not-found"


class SbdbSignature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str | None = None
    version: str | None = None


class SbdbOrbitClass(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str | None = None
    name: str | None = None


class SbdbObject(BaseModel):
    model_config = ConfigDict(extra="ignore")

    neo: bool | None = None
    pha: bool | None = None
    orbit_class: SbdbOrbitClass | None = None
    spkid: str | int | None = None
    des: str | None = None
    orbit_id: str | None = None
    fullname: str | None = None
    kind: str | None = None  # an|au|cn|cu (asteroid/comet, numbered/unnumbered)
    shortname: str | None = None


class SbdbElement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    value: str | None = None
    sigma: str | None = None
    units: str | None = None
    title: str | None = None


class SbdbOrbit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    epoch: str | None = None
    soln_date: str | None = None
    moid: str | None = None
    condition_code: str | None = None
    data_arc: str | None = None
    n_obs_used: int | None = None
    first_obs: str | None = None
    last_obs: str | None = None
    rms: str | None = None
    elements: list[SbdbElement] = Field(default_factory=list)


class SbdbPhysPar(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    value: str | None = None
    sigma: str | None = None
    units: str | None = None
    title: str | None = None


class SbdbListEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pdes: str | None = None
    name: str | None = None


class SbdbResponse(BaseModel):
    """A validated SBDB response (found, ambiguous, or not-found)."""

    model_config = ConfigDict(extra="ignore")

    signature: SbdbSignature | None = None
    object: SbdbObject | None = None
    orbit: SbdbOrbit | None = None
    phys_par: list[SbdbPhysPar] = Field(default_factory=list)
    message: str | None = None
    code: str | None = None
    matches: list[SbdbListEntry] | None = Field(default=None, alias="list")

    def outcome(self) -> SbdbOutcome:
        if self.object is not None:
            return SbdbOutcome.FOUND
        if self.matches:
            return SbdbOutcome.AMBIGUOUS
        return SbdbOutcome.NOT_FOUND
