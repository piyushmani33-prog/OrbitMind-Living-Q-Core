"""Typed domain models for source definitions, policy, rights, cache, freshness.

These are OrbitMind-internal models. Source-specific response shapes (e.g. CelesTrak
OMM JSON) live in the connector package and must NOT leak into these models.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow


class SourceKind(StrEnum):
    """Where data comes from (source connector kind)."""

    SAMPLE = "sample"  # bundled offline fixture (Phase 1 default)
    CELESTRAK = "celestrak"  # CelesTrak General Perturbations (Phase 2)
    JPL_SBDB = "jpl-sbdb"  # JPL Small-Body Database lookup (Phase 3A)
    JPL_SBDB_QUERY = "jpl-sbdb-query"  # JPL SBDB constrained query (Phase 3A)
    JPL_CAD = "jpl-cad"  # JPL/CNEOS Close-Approach Data (Phase 3A)


class SchemaFormat(StrEnum):
    """Machine-readable formats a source may return."""

    JSON_OMM = "json-omm"  # structured GP / OMM JSON (preferred)
    TLE = "tle"  # two-line element text
    JSON = "json"  # generic structured JSON (e.g. JPL SBDB/CAD)


class FreshnessState(StrEnum):
    """Explicit freshness classification of orbital data."""

    TEST_FIXTURE = "test-fixture"
    CURRENT = "current"
    FRESH = "fresh"
    AGING = "aging"
    STALE = "stale"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


class DataLiveness(StrEnum):
    """Whether the returned data is live, cached, stale, expired, or fixture."""

    LIVE = "live"
    CACHED = "cached"
    STALE = "stale"
    EXPIRED = "expired"
    FIXTURE = "fixture"


class CacheStatus(StrEnum):
    """Outcome of a cache lookup/store for a request."""

    HIT = "hit"
    MISS = "miss"
    EXPIRED = "expired"
    STORED = "stored"
    BYPASSED = "bypassed"
    SUPPRESSED = "suppressed"  # refresh suppressed by minimum-interval policy


class FetchOutcome(StrEnum):
    """Outcome of an attempt to obtain a source record."""

    FETCHED = "fetched"  # live network fetch succeeded
    CACHED = "cached"  # served from a valid cache entry
    SUPPRESSED = "suppressed"  # min-refresh interval prevented a live fetch
    FAILED = "failed"  # network/schema error
    DISABLED = "disabled"  # network or source disabled by policy


class SourceHealth(StrEnum):
    """Operational health of a source."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    UNKNOWN = "unknown"


class SourceLicenseRecord(BaseModel):
    """Data-rights metadata for a source. Never invent legal rights."""

    model_config = ConfigDict(frozen=True)

    license_name: str
    attribution_text: str
    usage_note: str
    # Default to the conservative posture: rights unclear until reviewed.
    requires_review: bool = True
    commercial_use_confirmed: bool = False
    reference_url: str = ""


class SourcePolicy(BaseModel):
    """Operational + rights policy governing how a source may be accessed."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    official_name: str
    base_url: str
    data_category: str
    attribution_text: str
    license: SourceLicenseRecord

    # Polling / caching discipline
    min_refresh_seconds: int = Field(ge=0)
    cache_ttl_seconds: int = Field(ge=0)

    # Freshness thresholds (age of the DATA epoch), seconds
    freshness_current_seconds: int = 6 * 3600
    freshness_fresh_seconds: int = 24 * 3600
    freshness_aging_seconds: int = 3 * 24 * 3600
    freshness_stale_seconds: int = 7 * 24 * 3600

    # Transport policy
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    max_retries: int = Field(ge=0, default=2)
    allowed_methods: tuple[str, ...] = ("GET",)
    allowed_hostnames: tuple[str, ...] = ()
    https_only: bool = True
    follow_redirects: bool = False
    max_response_bytes: int = 1_048_576
    allowed_content_types: tuple[str, ...] = ("application/json",)

    # Schema
    schema_format: SchemaFormat = SchemaFormat.JSON_OMM
    schema_version: str = "omm-1"

    # Behavior
    failure_behavior: str = "fail-safe-no-fallback"
    network_enabled: bool = False  # effective switch (global AND source)
    policy_version: str = "1"
    # Documentation version / inspection date this policy was verified against.
    documentation_reference: str = ""


class SourceDefinition(BaseModel):
    """A registered source and its policy."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    name: str
    kind: SourceKind
    description: str
    policy: SourcePolicy
    enabled: bool = False


class SourceSchemaVersion(BaseModel):
    """A known schema version for a source."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    schema_format: SchemaFormat
    version: str
    description: str = ""


class SourceFetchRecord(BaseModel):
    """A record of one attempt to obtain a source record (audit/provenance)."""

    id: str = Field(default_factory=new_id)
    source_id: str
    cache_key: str
    url: str
    outcome: FetchOutcome
    requested_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None
    http_status: int | None = None
    content_type: str | None = None
    response_bytes: int | None = None
    checksum: str | None = None
    schema_version: str | None = None
    from_cache: bool = False
    error: str | None = None


class SourceCacheRecord(BaseModel):
    """Metadata describing a cached raw source payload (body stored on disk)."""

    cache_key: str
    source_id: str
    url: str
    body_path: str  # relative to the cache root
    checksum: str
    schema_version: str
    http_status: int
    content_type: str
    fetched_at: datetime
    expires_at: datetime
    effective_epoch: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    failure_reason: str | None = None


class SourceFreshnessAssessment(BaseModel):
    """The freshness classification attached to a piece of orbital data."""

    model_config = ConfigDict(frozen=True)

    state: FreshnessState
    liveness: DataLiveness
    cache_status: CacheStatus
    data_epoch: datetime | None = None
    fetched_at: datetime | None = None
    age_seconds: float | None = None
    expires_at: datetime | None = None
    explanation: str = ""


class SourceHealthStatus(BaseModel):
    """Operational health snapshot for a source."""

    source_id: str
    health: SourceHealth
    network_enabled: bool
    source_enabled: bool
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    last_failure_reason: str | None = None
    detail: str = ""


class OrbitalElementRecord(BaseModel):
    """Normalized orbital element set (source-agnostic) ready for propagation.

    Carries the canonical TLE lines used by the existing SGP4 path plus headline
    structured elements and full source provenance/freshness.
    """

    model_config = ConfigDict(frozen=True)

    satellite_id: str
    object_name: str
    norad_cat_id: int | None = None
    object_id: str | None = None
    epoch: datetime  # element-set epoch (UTC)
    tle_line1: str
    tle_line2: str
    inclination_deg: float | None = None
    eccentricity: float | None = None
    mean_motion: float | None = None
    source_id: str
    schema_version: str
    checksum: str
    freshness: SourceFreshnessAssessment


class ElementFetchResult(BaseModel):
    """A normalized element record plus the fetch record describing how it was obtained."""

    record: OrbitalElementRecord
    fetch: SourceFetchRecord


class MissionSourceData(BaseModel):
    """The source-data provenance block reported on every mission result."""

    source_id: str
    record_identifier: str
    object_name: str
    data_epoch: datetime
    fetched_at: datetime | None
    cache_status: str
    freshness_state: str
    liveness: str
    policy_version: str
    checksum: str
    limitations: str
