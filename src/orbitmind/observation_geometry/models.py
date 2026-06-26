"""Strict domain models for bounded Earth-satellite observation geometry.

The package computes deterministic model output from pinned TLE inputs. It does not fetch
live elements, prove current satellite truth, claim taskability, or imply command readiness.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.timeutils import ensure_utc
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.space.elements import ElementParseError, validate_propagatable
from orbitmind.space.models import OrbitalSourceRecord

GEOMETRY_SCHEMA_VERSION: Literal["1"] = "1"
GEOMETRY_COMPUTATION_VERSION: Literal["orbitmind-look-angle-geometry-1.0"] = (
    "orbitmind-look-angle-geometry-1.0"
)

MAX_HORIZON_SECONDS = 86_400
MIN_STEP_SECONDS = 1
MAX_STEP_SECONDS = 3_600
MAX_PRIMARY_SAMPLES = 100_000
MAX_VISIBILITY_INTERVALS = 1_024
MAX_SATELLITES = 1
MAX_SITES = 1
MIN_ELEVATION_THRESHOLD_DEG = 0.0
MAX_ELEVATION_THRESHOLD_DEG = 90.0
MAX_REFINEMENT_ITERATIONS_PER_CROSSING = 50
MAX_TOTAL_REFINEMENT_EVALUATIONS = 102_400
REFINEMENT_TIME_TOLERANCE_SECONDS = 0.001
MAX_ID_LENGTH = 120
MAX_NAME_LENGTH = 160
MAX_LIMITATION_LENGTH = 260
MAX_ERROR_CODE_LENGTH = 80
MAX_FAILED_ERROR_RECORDS = 100_000

COARSE_SAMPLING_LIMITATION = (
    "Sampling can miss a visibility event that begins and ends between adjacent samples. "
    "Boundary refinement improves already-detected crossings but does not discover unsampled "
    "passes."
)
GEOMETRY_LIMITATIONS: tuple[str, ...] = (
    "Deterministic geometry from pinned TLE input; not live orbit truth.",
    "UT1 is approximated by UTC; no external Earth-orientation parameters or polar-motion "
    "correction are applied.",
    "No atmospheric refraction, terrain model, sensor field of view, slew constraint, weather, "
    "RF link, regulatory eligibility, taskability, approval, or command readiness is computed.",
    COARSE_SAMPLING_LIMITATION,
)
GEOMETRY_UNITS: dict[str, str] = {
    "time": "UTC timezone-aware ISO-8601",
    "observer_latitude": "degrees north-positive geodetic WGS-84",
    "observer_longitude": "degrees east-positive geodetic WGS-84",
    "observer_altitude": "kilometres above WGS-84 ellipsoid",
    "teme_position": "kilometres",
    "ecef_position": "kilometres",
    "azimuth": "degrees clockwise from true north in [0, 360)",
    "elevation": "degrees in [-90, 90]",
    "slant_range": "kilometres",
}


class GeometrySampleStatus(StrEnum):
    """Per-sample look-angle status."""

    OK = "ok"
    ERROR = "error"


class VisibilityRefinementStatus(StrEnum):
    """How interval boundaries were represented."""

    REFINED = "refined"
    SAMPLED = "sampled"
    CLIPPED = "clipped"
    REFINEMENT_FAILED = "refinement_failed"


class GeometryVerificationCheck(BaseModel):
    """One structural verification check."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    check_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    passed: bool
    message: str = Field(min_length=1, max_length=MAX_LIMITATION_LENGTH)


class GeometryVerificationResult(BaseModel):
    """Independent structural verification outcome for geometry results."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool
    checks: tuple[GeometryVerificationCheck, ...]
    recomputed_checksum: str | None = Field(default=None, min_length=64, max_length=64)
    limitations: tuple[str, ...] = (
        "Structural verification recomputes checksums and validates shape/order/ranges; it does "
        "not independently prove current orbital truth.",
        "Reference-vector checks validate implementation behavior for pinned vectors, not live "
        "satellite state.",
    )


class GeodeticPosition(BaseModel):
    """A bounded ground position on or near Earth."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg: float = Field(ge=-180.0, le=180.0)
    altitude_km: float = Field(default=0.0, ge=-0.5, le=9.0)

    @model_validator(mode="after")
    def _check_finite(self) -> GeodeticPosition:
        _require_finite(self.latitude_deg, "latitude_deg")
        _require_finite(self.longitude_deg, "longitude_deg")
        _require_finite(self.altitude_km, "altitude_km")
        return self


class GroundObservationSite(BaseModel):
    """A single bounded observer site for look-angle geometry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    site_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    position: GeodeticPosition

    @model_validator(mode="after")
    def _check_site(self) -> GroundObservationSite:
        _require_clean_id(self.site_id, "site_id")
        if self.name is not None:
            _require_clean_text(self.name, "name", max_length=MAX_NAME_LENGTH)
        return self


class PinnedOrbitElementSet(BaseModel):
    """Pinned TLE element input used by deterministic geometry computation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: OrbitalSourceRecord
    tle_line1: str = Field(min_length=69, max_length=69)
    tle_line2: str = Field(min_length=69, max_length=69)
    element_checksum: str = Field(default="", max_length=64)
    orbit_epoch: datetime | None = None
    source_epistemic_status: EpistemicStatus = EpistemicStatus.ASSUMPTION

    @model_validator(mode="after")
    def _check_elements(self) -> PinnedOrbitElementSet:
        _validate_tle_lines(self.tle_line1, self.tle_line2)
        try:
            validate_propagatable(self.tle_line1, self.tle_line2)
        except ElementParseError as exc:
            raise ValueError("TLE element set must be propagatable at epoch") from exc
        expected = element_set_checksum(self)
        if self.element_checksum and self.element_checksum != expected:
            raise ValueError("element_checksum does not match canonical TLE identity")
        object.__setattr__(self, "element_checksum", expected)
        object.__setattr__(self, "orbit_epoch", _parse_tle_epoch(self.tle_line1))
        object.__setattr__(self, "source_epistemic_status", self.source.epistemic_status)
        return self


class GeometryComputationRequest(BaseModel):
    """Bounded look-angle computation request.

    Sampling is start-inclusive. The end timestamp is sampled only when it lies exactly on the
    regular step grid; otherwise the final primary sample is the largest stepped timestamp before
    ``end``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = GEOMETRY_SCHEMA_VERSION
    elements: PinnedOrbitElementSet
    site: GroundObservationSite
    start: datetime
    end: datetime
    step_seconds: int = Field(ge=MIN_STEP_SECONDS, le=MAX_STEP_SECONDS)
    minimum_elevation_deg: float = Field(
        default=0.0, ge=MIN_ELEVATION_THRESHOLD_DEG, lt=MAX_ELEVATION_THRESHOLD_DEG
    )
    request_checksum: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _check_request(self) -> GeometryComputationRequest:
        start = _normalize_utc(self.start, "start")
        end = _normalize_utc(self.end, "end")
        _require_finite(self.minimum_elevation_deg, "minimum_elevation_deg")
        if end <= start:
            raise ValueError("geometry computation end must be after start")
        horizon_seconds = (end - start).total_seconds()
        if horizon_seconds > MAX_HORIZON_SECONDS:
            raise ValueError("geometry computation horizon exceeds 86400 seconds")
        if self.expected_sample_count() > MAX_PRIMARY_SAMPLES:
            raise ValueError("geometry computation exceeds maximum primary sample count")
        max_crossings = max(0, self.expected_sample_count() - 1)
        theoretical_refinement = max_crossings * MAX_REFINEMENT_ITERATIONS_PER_CROSSING
        if theoretical_refinement > MAX_TOTAL_REFINEMENT_EVALUATIONS:
            raise ValueError("geometry computation exceeds maximum refinement work bound")
        checksum = request_checksum(self.model_copy(update={"start": start, "end": end}))
        if self.request_checksum and self.request_checksum != checksum:
            raise ValueError("request_checksum does not match canonical request identity")
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "request_checksum", checksum)
        return self

    @property
    def horizon_seconds(self) -> float:
        """Computation horizon in seconds."""

        return (ensure_utc(self.end) - ensure_utc(self.start)).total_seconds()

    def expected_sample_count(self) -> int:
        """Primary sample count for the documented start-inclusive stepped grid."""

        return int(self.horizon_seconds // self.step_seconds) + 1


class GeometrySample(BaseModel):
    """One observer-relative look-angle sample."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    status: GeometrySampleStatus
    azimuth_deg: float | None = None
    elevation_deg: float | None = None
    slant_range_km: float | None = None
    safe_error_code: str | None = Field(default=None, max_length=MAX_ERROR_CODE_LENGTH)

    @model_validator(mode="after")
    def _check_sample(self) -> GeometrySample:
        timestamp = _normalize_utc(self.timestamp, "sample timestamp")
        if self.status is GeometrySampleStatus.OK:
            if (
                self.azimuth_deg is None
                or self.elevation_deg is None
                or self.slant_range_km is None
            ):
                raise ValueError("successful geometry sample requires all geometry fields")
            _require_angle_range(self.azimuth_deg, 0.0, 360.0, "azimuth_deg", upper_open=True)
            _require_angle_range(self.elevation_deg, -90.0, 90.0, "elevation_deg")
            _require_finite(self.slant_range_km, "slant_range_km")
            if self.slant_range_km <= 0.0:
                raise ValueError("slant_range_km must be positive")
            if self.safe_error_code is not None:
                raise ValueError("successful geometry sample must not include an error code")
        else:
            if (
                self.azimuth_deg is not None
                or self.elevation_deg is not None
                or self.slant_range_km is not None
            ):
                raise ValueError("errored geometry sample must not fabricate geometry values")
            if self.safe_error_code is None:
                raise ValueError("errored geometry sample requires a bounded safe error code")
            _require_clean_text(
                self.safe_error_code,
                "safe_error_code",
                max_length=MAX_ERROR_CODE_LENGTH,
            )
        object.__setattr__(self, "timestamp", timestamp)
        return self


class ComputedVisibilityInterval(BaseModel):
    """A sampled/refined visibility interval above the configured elevation threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rise_time: datetime
    set_time: datetime
    peak_time: datetime
    peak_elevation_deg: float
    rise_azimuth_deg: float
    set_azimuth_deg: float
    rise_boundary_clipped: bool = False
    set_boundary_clipped: bool = False
    refinement_status: VisibilityRefinementStatus = VisibilityRefinementStatus.SAMPLED

    @model_validator(mode="after")
    def _check_interval(self) -> ComputedVisibilityInterval:
        rise = _normalize_utc(self.rise_time, "rise_time")
        set_time = _normalize_utc(self.set_time, "set_time")
        peak = _normalize_utc(self.peak_time, "peak_time")
        if set_time < rise:
            raise ValueError("visibility set_time must be at or after rise_time")
        if peak < rise or peak > set_time:
            raise ValueError("visibility peak_time must be contained in the interval")
        _require_angle_range(self.peak_elevation_deg, -90.0, 90.0, "peak_elevation_deg")
        _require_angle_range(self.rise_azimuth_deg, 0.0, 360.0, "rise_azimuth_deg", upper_open=True)
        _require_angle_range(self.set_azimuth_deg, 0.0, 360.0, "set_azimuth_deg", upper_open=True)
        object.__setattr__(self, "rise_time", rise)
        object.__setattr__(self, "set_time", set_time)
        object.__setattr__(self, "peak_time", peak)
        return self


class GeometryComputationResult(BaseModel):
    """Deterministic model output for bounded look-angle geometry."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = GEOMETRY_SCHEMA_VERSION
    request_checksum: str = Field(min_length=64, max_length=64)
    element_checksum: str = Field(min_length=64, max_length=64)
    source_identity_checksum: str = Field(min_length=64, max_length=64)
    samples: tuple[GeometrySample, ...]
    intervals: tuple[ComputedVisibilityInterval, ...] = ()
    sample_count: int = Field(ge=0, le=MAX_PRIMARY_SAMPLES)
    failed_sample_count: int = Field(ge=0, le=MAX_FAILED_ERROR_RECORDS)
    computation_version: Literal["orbitmind-look-angle-geometry-1.0"] = GEOMETRY_COMPUTATION_VERSION
    units: dict[str, str] = Field(default_factory=lambda: dict(GEOMETRY_UNITS))
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION
    limitations: tuple[str, ...] = GEOMETRY_LIMITATIONS
    geometry_checksum: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _check_result(self) -> GeometryComputationResult:
        _require_sha256(self.request_checksum, "request_checksum")
        _require_sha256(self.element_checksum, "element_checksum")
        _require_sha256(self.source_identity_checksum, "source_identity_checksum")
        if self.sample_count != len(self.samples):
            raise ValueError("sample_count must equal the number of samples")
        failed = sum(1 for sample in self.samples if sample.status is GeometrySampleStatus.ERROR)
        if self.failed_sample_count != failed:
            raise ValueError("failed_sample_count must equal errored samples")
        if len(self.intervals) > MAX_VISIBILITY_INTERVALS:
            raise ValueError("visibility interval count exceeds bound")
        _check_limitations(self.limitations)
        if COARSE_SAMPLING_LIMITATION not in self.limitations:
            raise ValueError("geometry result must carry the coarse-sampling limitation")
        checksum = geometry_checksum(self)
        if self.geometry_checksum and self.geometry_checksum != checksum:
            raise ValueError("geometry_checksum does not match canonical geometry identity")
        object.__setattr__(self, "geometry_checksum", checksum)
        return self


def element_set_checksum(elements: PinnedOrbitElementSet) -> str:
    """Checksum over normalized TLE lines and approved source identity fields."""

    return sha256_canonical_json(
        {
            "tle_line1": elements.tle_line1.rstrip(),
            "tle_line2": elements.tle_line2.rstrip(),
            "source": _canonical_source(elements.source),
        }
    )


def request_checksum(request: GeometryComputationRequest) -> str:
    """Checksum over bounded scientific request identity."""

    return sha256_canonical_json(
        {
            "schema_version": request.schema_version,
            "element_checksum": request.elements.element_checksum,
            "site": _canonical_value(request.site),
            "start": _canonical_time(request.start),
            "end": _canonical_time(request.end),
            "step_seconds": request.step_seconds,
            "minimum_elevation_deg": _round_float(request.minimum_elevation_deg),
        }
    )


def source_identity_checksum(source: OrbitalSourceRecord) -> str:
    """Checksum over the source record used by the pinned orbit element set."""

    return sha256_canonical_json(_canonical_source(source))


def geometry_checksum(result: GeometryComputationResult) -> str:
    """Checksum over deterministic geometry output identity."""

    return sha256_canonical_json(
        {
            "schema_version": result.schema_version,
            "request_checksum": result.request_checksum,
            "element_checksum": result.element_checksum,
            "samples": [_canonical_sample(sample) for sample in result.samples],
            "intervals": [_canonical_value(interval) for interval in result.intervals],
            "computation_version": result.computation_version,
            "limitations": list(result.limitations),
        }
    )


def _canonical_source(source: OrbitalSourceRecord) -> dict[str, Any]:
    return {
        "satellite_id": source.satellite_id,
        "name": source.name,
        "norad_cat_id": source.norad_cat_id,
        "source_name": source.source_name,
        "source_url": source.source_url,
        "epoch_utc": source.epoch_utc,
        "fixture_created": source.fixture_created,
        "data_use_note": source.data_use_note,
        "checksum": source.checksum,
        "test_only": source.test_only,
        "epistemic_status": source.epistemic_status.value,
    }


def _canonical_sample(sample: GeometrySample) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "timestamp": _canonical_time(sample.timestamp),
        "status": sample.status.value,
    }
    if sample.status is GeometrySampleStatus.OK:
        payload.update(
            {
                "azimuth_deg": _round_float(sample.azimuth_deg),
                "elevation_deg": _round_float(sample.elevation_deg),
                "slant_range_km": _round_float(sample.slant_range_km),
            }
        )
    else:
        payload["safe_error_code"] = sample.safe_error_code
    return payload


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return _canonical_time(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {
            str(key): _canonical_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, float):
        return _round_float(value)
    return value


def _round_float(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 9)


def _canonical_time(value: datetime) -> str:
    return ensure_utc(value).isoformat(timespec="microseconds")


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    try:
        return ensure_utc(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware") from exc


def _require_clean_id(value: str, field_name: str) -> None:
    _require_clean_text(value, field_name, max_length=MAX_ID_LENGTH)


def _require_clean_text(value: str, field_name: str, *, max_length: int) -> None:
    if not value or value.strip() != value or len(value) > max_length:
        raise ValueError(f"{field_name} must be non-empty, unpadded, and bounded")


def _require_finite(value: float, field_name: str) -> None:
    if not math.isfinite(value):
        raise ValueError(f"{field_name} must be finite")


def _require_angle_range(
    value: float,
    lower: float,
    upper: float,
    field_name: str,
    *,
    upper_open: bool = False,
) -> None:
    _require_finite(value, field_name)
    upper_ok = value < upper if upper_open else value <= upper
    if value < lower or not upper_ok:
        bracket = ")" if upper_open else "]"
        raise ValueError(f"{field_name} must be in [{lower}, {upper}{bracket}")


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _check_limitations(limitations: tuple[str, ...]) -> None:
    if not limitations:
        raise ValueError("geometry limitations are required")
    forbidden = (
        "verified satellite access",
        "taskable",
        "command approved",
        "command readiness confirmed",
        "approved tasking",
        "quantum-authoritative",
    )
    joined = " ".join(limitations).lower()
    if any(claim in joined for claim in forbidden):
        raise ValueError("geometry limitations must not make operational claims")
    for item in limitations:
        _require_clean_text(item, "limitation", max_length=MAX_LIMITATION_LENGTH)


def _validate_tle_lines(line1: str, line2: str) -> None:
    if len(line1) != 69 or len(line2) != 69:
        raise ValueError("TLE lines must be exactly 69 characters")
    if not line1.startswith("1 ") or not line2.startswith("2 "):
        raise ValueError("TLE lines must have valid line numbers")
    if not _tle_checksum_valid(line1) or not _tle_checksum_valid(line2):
        raise ValueError("TLE line checksum is invalid")


def _tle_checksum_valid(line: str) -> bool:
    total = 0
    for char in line[:68]:
        if char.isdigit():
            total += int(char)
        elif char == "-":
            total += 1
    return str(total % 10) == line[68]


def _parse_tle_epoch(line1: str) -> datetime:
    year_two_digit = int(line1[18:20])
    year = 2000 + year_two_digit if year_two_digit < 57 else 1900 + year_two_digit
    day_of_year = float(line1[20:32])
    epoch = datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day_of_year - 1.0)
    return epoch.astimezone(UTC)
