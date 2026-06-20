"""OrbitMind-owned typed filters for SBDB query + CAD (no raw upstream params).

These models expose only an allowlisted subset of upstream capability. No raw
SQL-like expressions, arbitrary filter languages, or arbitrary field names are
accepted, and result sizes are bounded.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.objects.models import SpaceObjectKind
from orbitmind.smallbody.models import JplSourceRecord
from orbitmind.sources.models import SourceFreshnessAssessment

# Allowlisted SBDB query output fields (a curated, safe subset of JPL field names).
SBDB_QUERY_FIELDS: frozenset[str] = frozenset(
    {
        "full_name",
        "pdes",
        "name",
        "neo",
        "pha",
        "class",
        "e",
        "a",
        "q",
        "i",
        "om",
        "w",
        "ma",
        "per",
        "ad",
        "H",
        "diameter",
        "albedo",
        "moid",
        "condition_code",
        "data_arc",
    }
)
# Fields OrbitMind will sort on (deterministic, applied to the returned page).
SBDB_SORTABLE_FIELDS: frozenset[str] = frozenset(
    {"full_name", "pdes", "a", "e", "i", "q", "H", "diameter", "moid"}
)
# Allowlisted JPL orbit-class codes.
SBDB_ORBIT_CLASSES: frozenset[str] = frozenset(
    {
        "IEO",
        "ATE",
        "APO",
        "AMO",
        "MCA",
        "IMB",
        "MBA",
        "OMB",
        "TJN",
        "CEN",
        "TNO",
        "AST",
        "JFC",
        "JFc",
        "HTC",
        "ETc",
        "CTc",
        "PAA",
        "HYA",
    }
)
# Allowlisted close-approach bodies.
CAD_BODIES: frozenset[str] = frozenset({"Earth", "Moon", "Merc", "Venus", "Mars", "Juptr", "Satrn"})


class SmallBodyKindFilter(StrEnum):
    """Object-kind selector for queries (asteroid/comet only this phase)."""

    ASTEROID = "asteroid"
    COMET = "comet"


def _kind_to_space_object_kind(kind: SmallBodyKindFilter | None) -> SpaceObjectKind | None:
    if kind is SmallBodyKindFilter.ASTEROID:
        return SpaceObjectKind.ASTEROID
    if kind is SmallBodyKindFilter.COMET:
        return SpaceObjectKind.COMET
    return None


class SbdbQueryFilter(BaseModel):
    """Constrained SBDB query filter (allowlisted, bounded)."""

    model_config = ConfigDict(frozen=True)

    object_kind: SmallBodyKindFilter | None = None
    near_earth_object: bool | None = None
    potentially_hazardous: bool | None = None
    orbit_class: str | None = None
    limit: int = Field(default=20, ge=1, le=200)
    offset: int = Field(default=0, ge=0)
    sort_field: str = "full_name"
    output_fields: list[str] = Field(default_factory=lambda: ["full_name", "neo", "pha", "class"])

    @model_validator(mode="after")
    def _check_allowlists(self) -> SbdbQueryFilter:
        if self.orbit_class is not None and self.orbit_class not in SBDB_ORBIT_CLASSES:
            raise ValueError(f"unsupported orbit_class: {self.orbit_class}")
        if self.sort_field not in SBDB_SORTABLE_FIELDS:
            raise ValueError(f"unsupported sort_field: {self.sort_field}")
        bad = [f for f in self.output_fields if f not in SBDB_QUERY_FIELDS]
        if bad:
            raise ValueError(f"unsupported output_fields: {', '.join(bad)}")
        return self

    def space_object_kind(self) -> SpaceObjectKind | None:
        return _kind_to_space_object_kind(self.object_kind)


class SmallBodyQueryItem(BaseModel):
    """One row of an SBDB query result (selected fields only)."""

    model_config = ConfigDict(frozen=True)

    full_name: str | None = None
    designation: str | None = None
    near_earth_object_source: bool | None = None
    potentially_hazardous_source: bool | None = None
    orbit_class_code: str | None = None
    semimajor_axis_au: float | None = None
    eccentricity: float | None = None
    inclination_deg: float | None = None
    perihelion_distance_au: float | None = None
    absolute_magnitude_h: float | None = None
    diameter_km: float | None = None
    moid_au: float | None = None


class SmallBodyQueryResultSet(BaseModel):
    """An SBDB query result set with provenance + truncation/pagination metadata."""

    items: list[SmallBodyQueryItem]
    total_reported: int
    returned: int
    truncated: bool
    limit: int
    offset: int
    source: JplSourceRecord
    freshness: SourceFreshnessAssessment


class CadQueryFilter(BaseModel):
    """Constrained Close-Approach Data filter (allowlisted, bounded)."""

    model_config = ConfigDict(frozen=True)

    date_min: dt.datetime
    date_max: dt.datetime
    body: str = "Earth"
    max_distance_au: float | None = Field(default=None, gt=0.0, le=1.0)
    near_earth_object_only: bool = False
    potentially_hazardous_only: bool = False
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def _check(self) -> CadQueryFilter:
        if self.date_min.tzinfo is None or self.date_max.tzinfo is None:
            raise ValueError("date_min and date_max must be timezone-aware (UTC)")
        if self.date_max <= self.date_min:
            raise ValueError("date_max must be after date_min")
        if self.body not in CAD_BODIES:
            raise ValueError(f"unsupported approach body: {self.body}")
        return self
