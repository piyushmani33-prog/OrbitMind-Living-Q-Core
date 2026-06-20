"""Normalized small-body domain models (asteroid/comet) and close approaches."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.objects.models import (
    ObjectVerificationStatus,
    SpaceObjectIdentity,
    SpaceObjectKind,
)
from orbitmind.objects.orbits import SmallBodyOrbitElements
from orbitmind.sources.models import SourceFreshnessAssessment


class JplSourceRecord(BaseModel):
    """Provenance for a JPL-sourced record (no internal paths/secrets)."""

    model_config = ConfigDict(frozen=True)

    source_id: str  # jpl-sbdb | jpl-sbdb-query | jpl-cad
    source_record_id: str  # e.g. SPK-ID / designation
    requested_identifier: str
    signature_version: str | None = None  # JPL API "signature.version"
    fetched_at: datetime | None = None
    checksum: str
    schema_version: str
    policy_version: str


class OrbitSolutionMetadata(BaseModel):
    """Quality/solution metadata for a small-body orbit (source-reported)."""

    model_config = ConfigDict(frozen=True)

    epoch_jd: float | None = None
    solution_date: str | None = None
    condition_code: str | None = None  # JPL orbit condition code "0".."9" (uncertainty)
    moid_au: float | None = None  # minimum orbit intersection distance (Earth)
    rms: float | None = None


class OrbitUncertainty(BaseModel):
    """Source-reported orbit uncertainty (NOT an OrbitMind calculation)."""

    model_config = ConfigDict(frozen=True)

    condition_code: str | None = None
    note: str = "Source-reported JPL orbit condition code (0=best .. 9=poor)."


class ObservationArc(BaseModel):
    """Observation arc metadata (source-reported)."""

    model_config = ConfigDict(frozen=True)

    first_observation: str | None = None
    last_observation: str | None = None
    arc_days: float | None = None
    n_observations_used: int | None = None


class SmallBodyOrbit(BaseModel):
    """A small-body heliocentric orbit: elements + solution metadata + uncertainty."""

    model_config = ConfigDict(frozen=True)

    elements: SmallBodyOrbitElements
    solution: OrbitSolutionMetadata = Field(default_factory=OrbitSolutionMetadata)
    uncertainty: OrbitUncertainty = Field(default_factory=OrbitUncertainty)
    observation_arc: ObservationArc = Field(default_factory=ObservationArc)


class SmallBodyPhysicalProperties(BaseModel):
    """Source-provided physical properties (all model-estimate; missing => None)."""

    model_config = ConfigDict(frozen=True)

    absolute_magnitude_h: float | None = None  # mag
    diameter_km: float | None = None
    diameter_min_km: float | None = None
    diameter_max_km: float | None = None
    albedo: float | None = None
    rotation_period_h: float | None = None
    units: dict[str, str] = Field(
        default_factory=lambda: {
            "absolute_magnitude_h": "mag",
            "diameter_km": "km",
            "rotation_period_h": "hours",
        }
    )


class SmallBodyClassification(BaseModel):
    """Source-provided classification (orbit class, NEO/PHA flags)."""

    model_config = ConfigDict(frozen=True)

    orbit_class_code: str | None = None
    orbit_class_name: str | None = None
    spectral_type: str | None = None


class HazardDesignation(BaseModel):
    """SOURCE-PROVIDED hazard flags. OrbitMind does NOT compute these (SR/epistemics)."""

    model_config = ConfigDict(frozen=True)

    near_earth_object_source: bool | None = None  # JPL "neo"
    potentially_hazardous_source: bool | None = None  # JPL "pha"
    note: str = (
        "Flags are reported by JPL, not computed by OrbitMind. 'Potentially hazardous' "
        "is a source classification, not an impact prediction."
    )


class SmallBodyIdentity(BaseModel):
    """Small-body identity specialization (kind asteroid/comet)."""

    model_config = ConfigDict(frozen=True)

    kind: SpaceObjectKind
    full_name: str
    designation: str | None = None
    number: str | None = None
    spk_id: str | None = None


class SmallBodyRecord(BaseModel):
    """A normalized small-body record (asteroid or comet) with provenance + labels."""

    id: str = Field(default_factory=new_id)
    identity: SpaceObjectIdentity
    small_body_identity: SmallBodyIdentity
    orbit: SmallBodyOrbit
    physical: SmallBodyPhysicalProperties = Field(default_factory=SmallBodyPhysicalProperties)
    classification: SmallBodyClassification = Field(default_factory=SmallBodyClassification)
    hazard: HazardDesignation = Field(default_factory=HazardDesignation)
    source: JplSourceRecord
    freshness: SourceFreshnessAssessment
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION
    verification_status: ObjectVerificationStatus = ObjectVerificationStatus.NOT_VERIFIED
    limitations: str = (
        "Source-reported JPL SBDB data. Orbit solution may carry uncertainty; "
        "physical properties are estimates. Not independently verified by OrbitMind."
    )
    raw_artifact_ref: str | None = None  # relative cache path if the raw body is retained
    created_at: datetime = Field(default_factory=utcnow)


# --- Close-approach domain models ------------------------------------------
class CloseApproachBody(BaseModel):
    """The body a small body approaches (e.g. Earth)."""

    model_config = ConfigDict(frozen=True)

    name: str


class CloseApproachDistance(BaseModel):
    """Close-approach distance (au). Nominal is not a guarantee."""

    model_config = ConfigDict(frozen=True)

    nominal_au: float | None = None
    minimum_au: float | None = None
    maximum_au: float | None = None
    units: str = "au"


class CloseApproachVelocity(BaseModel):
    """Close-approach relative velocity (km/s)."""

    model_config = ConfigDict(frozen=True)

    relative_kms: float | None = None
    infinity_kms: float | None = None
    units: str = "km/s"


class CloseApproachRecord(BaseModel):
    """A normalized close-approach record (source-reported orbital solution data)."""

    id: str = Field(default_factory=new_id)
    designation: str
    full_name: str | None = None
    orbit_id: str | None = None
    time_utc: datetime
    time_jd: float | None = None
    body: CloseApproachBody
    distance: CloseApproachDistance
    velocity: CloseApproachVelocity
    absolute_magnitude_h: float | None = None
    time_sigma: str | None = None  # JPL t_sigma_f (3-sigma time uncertainty)
    near_earth_object_source: bool | None = None
    potentially_hazardous_source: bool | None = None
    source: JplSourceRecord
    freshness: SourceFreshnessAssessment
    epistemic_status: EpistemicStatus = EpistemicStatus.MODEL_ESTIMATE
    limitations: str = (
        "Source-reported close-approach from a JPL orbit solution; nominal distance is "
        "not a guarantee and uncertainty may exist. A close approach is NOT an impact, "
        "and hazard classification is source-reported, not computed by OrbitMind."
    )
    created_at: datetime = Field(default_factory=utcnow)


class CloseApproachResultSet(BaseModel):
    """A close-approach query result set with truncation/provenance metadata."""

    records: list[CloseApproachRecord]
    total_reported: int
    returned: int
    truncated: bool
    source: JplSourceRecord
    freshness: SourceFreshnessAssessment


class SmallBodyLookupResult(BaseModel):
    """A normalized lookup result plus cache metadata."""

    record: SmallBodyRecord
    from_cache: bool
    cache_status: str
