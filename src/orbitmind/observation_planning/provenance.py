"""Pinned input provenance and declared eligibility contracts for Phase 4B.2A.

This module is deliberately domain-only. It records immutable scientific input identity
and declared or fixture-backed eligibility intervals without computing orbital access,
visibility, taskability, command readiness, or regulatory approval.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc
from orbitmind.observation_planning.models import ObservationPlanningRequest
from orbitmind.optimization.models import ObservationOpportunity, TimeWindow

_PROVENANCE_SCHEMA_VERSION: Literal["1"] = "1"
_ELIGIBILITY_SCHEMA_VERSION: Literal["1"] = "1"
_MAX_ID_LENGTH = 120
_MAX_LIMITATION_LENGTH = 240
_MAX_RIGHTS_NOTE_LENGTH = 240
_MAX_MEDIA_TYPE_LENGTH = 120
_MAX_ELIGIBILITY_WINDOWS = 24
_MAX_ELIGIBILITY_WINDOW_DURATION = timedelta(hours=48)
_CHECKSUM_ALGORITHM: Literal["sha256"] = "sha256"
_NON_OPERATIONAL_LIMITATION = (
    "Declared eligibility only; does not prove orbital visibility, taskability, "
    "command readiness, regulatory approval, or mission feasibility."
)


class PinnedInputSourceType(StrEnum):
    """Bounded source categories accepted by the provenance domain."""

    FIXTURE = "fixture"
    USER_DECLARED = "user_declared"
    DERIVED = "derived"


class PinnedInputSourceMode(StrEnum):
    """Honest source modes for pinned scientific inputs."""

    FIXTURE_BACKED = "fixture_backed"
    USER_DECLARED = "user_declared"
    DERIVED_FROM_DECLARED_INPUT = "derived_from_declared_input"


class InputRightsStatus(StrEnum):
    """Declared rights status; this is recordkeeping, not legal clearance."""

    VERIFIED = "verified"
    DECLARED = "declared"
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"


class InputRightsPermission(StrEnum):
    """A small permission vocabulary for provenance rights declarations."""

    PERMITTED = "permitted"
    PROHIBITED = "prohibited"
    UNKNOWN = "unknown"
    RESTRICTED = "restricted"


class ScientificInputVerificationStatus(StrEnum):
    """Epistemic labels for pinned inputs and declared eligibility."""

    FIXTURE_VERIFIED = "fixture_verified"
    USER_DECLARED = "user_declared"
    DERIVED_FROM_DECLARED = "derived_from_declared"
    UNVERIFIED = "unverified"
    UNKNOWN = "unknown"


class EligibilityDeclarationMode(StrEnum):
    """Non-geometric eligibility declaration modes."""

    FIXTURE_BACKED = "fixture_backed"
    USER_DECLARED = "user_declared"
    DERIVED_FROM_DECLARED_INPUT = "derived_from_declared_input"


class InputRightsDeclaration(BaseModel):
    """Immutable rights declaration for a pinned input.

    The declaration records known or caller-declared rights facts. It does not provide legal
    advice and does not transform unknown or restricted rights into clearance.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    rights_status: InputRightsStatus
    license_id: str | None = Field(default=None, min_length=1, max_length=_MAX_ID_LENGTH)
    redistribution: InputRightsPermission = InputRightsPermission.UNKNOWN
    commercial_use: InputRightsPermission = InputRightsPermission.UNKNOWN
    attribution_required: bool | None = None
    user_responsibility: str = Field(default="", max_length=_MAX_RIGHTS_NOTE_LENGTH)
    limitations: tuple[str, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def _check_limitations(self) -> InputRightsDeclaration:
        _require_clean_strings(self.limitations, "rights limitation", allow_empty_tuple=True)
        if self.rights_status == InputRightsStatus.RESTRICTED and (
            self.redistribution == InputRightsPermission.PERMITTED
            or self.commercial_use == InputRightsPermission.PERMITTED
        ):
            raise ValueError(
                "restricted rights cannot explicitly permit redistribution or commercial use"
            )
        return self


class InputSourceIdentity(BaseModel):
    """Stable identity of the scientific source that was pinned."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    source_type: PinnedInputSourceType
    source_mode: PinnedInputSourceMode
    publisher: str | None = Field(default=None, min_length=1, max_length=_MAX_ID_LENGTH)
    dataset_name: str | None = Field(default=None, min_length=1, max_length=_MAX_ID_LENGTH)
    dataset_version: str | None = Field(default=None, min_length=1, max_length=_MAX_ID_LENGTH)
    dataset_revision: str | None = Field(default=None, min_length=1, max_length=_MAX_ID_LENGTH)

    @model_validator(mode="after")
    def _check_source_shape(self) -> InputSourceIdentity:
        _require_clean_id(self.source_id, "source_id")
        if self.source_type == PinnedInputSourceType.FIXTURE:
            if self.source_mode != PinnedInputSourceMode.FIXTURE_BACKED:
                raise ValueError("fixture sources require fixture-backed source mode")
            if self.dataset_name is None or self.dataset_version is None:
                raise ValueError("fixture sources require dataset_name and dataset_version")
        elif self.source_type == PinnedInputSourceType.USER_DECLARED:
            if self.source_mode != PinnedInputSourceMode.USER_DECLARED:
                raise ValueError("user-declared sources require user-declared source mode")
        else:
            if self.source_mode != PinnedInputSourceMode.DERIVED_FROM_DECLARED_INPUT:
                raise ValueError("derived sources require derived-from-declared-input mode")
            if self.dataset_name is None or self.dataset_version is None:
                raise ValueError("derived sources require dataset_name and dataset_version")
        return self


class PinnedInputArtifact(BaseModel):
    """Content identity for a pinned scientific input artifact or declaration snapshot."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    content_checksum: str = Field(min_length=64, max_length=64)
    checksum_algorithm: Literal["sha256"] = _CHECKSUM_ALGORITHM
    media_type: str = Field(min_length=1, max_length=_MAX_MEDIA_TYPE_LENGTH)
    record_count: int | None = Field(default=None, ge=0, le=1_000_000)

    @model_validator(mode="after")
    def _check_artifact(self) -> PinnedInputArtifact:
        _require_clean_id(self.artifact_id, "artifact_id")
        _require_sha256(self.content_checksum, "content_checksum")
        return self


class PinnedInputProvenance(BaseModel):
    """Immutable identity of the scientific input used by planning.

    ``parent_provenance_checksums`` is required for derived sources so the derived record can be
    traced back to pinned fixture or user-declared inputs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = _PROVENANCE_SCHEMA_VERSION
    source: InputSourceIdentity
    artifact: PinnedInputArtifact
    declared_at: datetime | None = None
    retrieved_at: datetime | None = None
    effective_start: datetime | None = None
    effective_end: datetime | None = None
    rights: InputRightsDeclaration
    verification_status: ScientificInputVerificationStatus
    parent_provenance_checksums: tuple[str, ...] = Field(default=(), max_length=8)
    limitations: tuple[str, ...] = Field(default=(_NON_OPERATIONAL_LIMITATION,), max_length=8)

    @property
    def checksum(self) -> str:
        """Deterministic checksum over scientific provenance identity."""

        return provenance_checksum(self)

    @model_validator(mode="after")
    def _check_provenance(self) -> PinnedInputProvenance:
        declared_at = _normalize_optional_time(self.declared_at, "declared_at")
        retrieved_at = _normalize_optional_time(self.retrieved_at, "retrieved_at")
        effective_start = _normalize_optional_time(self.effective_start, "effective_start")
        effective_end = _normalize_optional_time(self.effective_end, "effective_end")
        if (
            effective_start is not None
            and effective_end is not None
            and effective_end <= effective_start
        ):
            raise ValueError("effective coverage end must be after start")
        for checksum in self.parent_provenance_checksums:
            _require_sha256(checksum, "parent_provenance_checksum")
        if len(set(self.parent_provenance_checksums)) != len(self.parent_provenance_checksums):
            raise ValueError("parent provenance checksums must be unique")
        if self.source.source_type == PinnedInputSourceType.USER_DECLARED and declared_at is None:
            raise ValueError("user-declared provenance requires declared_at")
        if (
            self.source.source_type == PinnedInputSourceType.DERIVED
            and not self.parent_provenance_checksums
        ):
            raise ValueError("derived provenance requires parent provenance checksum")
        if (
            self.source.source_type != PinnedInputSourceType.DERIVED
            and self.parent_provenance_checksums
        ):
            raise ValueError("only derived provenance may carry parent provenance checksums")
        _check_limitations_are_non_operational(self.limitations)
        object.__setattr__(self, "declared_at", declared_at)
        object.__setattr__(self, "retrieved_at", retrieved_at)
        object.__setattr__(self, "effective_start", effective_start)
        object.__setattr__(self, "effective_end", effective_end)
        object.__setattr__(
            self,
            "parent_provenance_checksums",
            tuple(sorted(self.parent_provenance_checksums)),
        )
        return self


class EligibilityWindow(BaseModel):
    """Declared or fixture-backed interval in which an observation may be considered eligible.

    This is not a computed orbital-access, visibility, contact, or taskability window.
    Overlap between windows is allowed because these records are candidate eligibility inputs;
    scheduling constraints decide whether overlapping opportunities may be selected together.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    asset_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    target_id: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    start: datetime
    end: datetime
    source_provenance_checksum: str = Field(min_length=64, max_length=64)
    declaration_mode: EligibilityDeclarationMode
    eligibility_reason: str = Field(min_length=1, max_length=_MAX_ID_LENGTH)
    verification_status: ScientificInputVerificationStatus
    limitations: tuple[str, ...] = Field(default=(_NON_OPERATIONAL_LIMITATION,), max_length=8)

    @model_validator(mode="after")
    def _check_window(self) -> EligibilityWindow:
        _require_clean_id(self.id, "eligibility window ID")
        _require_clean_id(self.asset_id, "asset ID")
        _require_clean_id(self.target_id, "target ID")
        start = ensure_utc(self.start)
        end = ensure_utc(self.end)
        if end <= start:
            raise ValueError("eligibility window end must be after start")
        if end - start > _MAX_ELIGIBILITY_WINDOW_DURATION:
            raise ValueError("eligibility window exceeds maximum duration")
        _require_sha256(self.source_provenance_checksum, "source_provenance_checksum")
        _check_limitations_are_non_operational(self.limitations)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        return self


class EligibilityWindowSet(BaseModel):
    """Schema-versioned set of declared or fixture-backed eligibility windows."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = _ELIGIBILITY_SCHEMA_VERSION
    source_provenance: PinnedInputProvenance
    windows: tuple[EligibilityWindow, ...] = Field(max_length=_MAX_ELIGIBILITY_WINDOWS)
    generation_rule_version: str = Field(
        default="declared-eligibility-window-set-v1",
        min_length=1,
        max_length=_MAX_ID_LENGTH,
    )
    limitations: tuple[str, ...] = Field(default=(_NON_OPERATIONAL_LIMITATION,), max_length=8)

    @property
    def checksum(self) -> str:
        """Deterministic checksum over the window set identity."""

        return eligibility_window_set_checksum(self)

    @model_validator(mode="after")
    def _check_set(self) -> EligibilityWindowSet:
        _check_limitations_are_non_operational(self.limitations)
        if len(self.windows) > _MAX_ELIGIBILITY_WINDOWS:
            raise ValueError(f"eligibility windows must contain at most {_MAX_ELIGIBILITY_WINDOWS}")
        window_ids = [window.id for window in self.windows]
        if len(window_ids) != len(set(window_ids)):
            raise ValueError("eligibility window IDs must be unique")
        scientific_keys = {
            (
                window.asset_id,
                window.target_id,
                window.start,
                window.end,
            )
            for window in self.windows
        }
        if len(scientific_keys) != len(self.windows):
            raise ValueError("duplicate eligibility windows for the same asset/target/time")
        self_checksum = provenance_checksum(self.source_provenance)
        allowed_checksums = {self_checksum}
        if self.source_provenance.source.source_type == PinnedInputSourceType.DERIVED:
            allowed_checksums.update(self.source_provenance.parent_provenance_checksums)
        for window in self.windows:
            if window.source_provenance_checksum not in allowed_checksums:
                raise ValueError("eligibility window references unsupported provenance")
            _require_compatible_window_mode(window, self.source_provenance)
        object.__setattr__(
            self,
            "windows",
            tuple(sorted(self.windows, key=_window_sort_key)),
        )
        return self


def provenance_checksum(provenance: PinnedInputProvenance) -> str:
    """Compute a deterministic checksum for pinned input provenance."""

    return sha256_canonical_json(_canonical_value(provenance))


def eligibility_window_set_checksum(window_set: EligibilityWindowSet) -> str:
    """Compute a deterministic checksum for an eligibility-window set."""

    return sha256_canonical_json(_canonical_value(window_set))


def eligibility_windows_to_opportunities(
    window_set: EligibilityWindowSet,
    *,
    mission_value: float = 1.0,
    energy_cost: float = 0.0,
    storage_cost: float = 0.0,
) -> tuple[ObservationOpportunity, ...]:
    """Convert declared eligibility windows into bounded candidate opportunities.

    The conversion is deterministic and non-geometric. It does not invoke solvers, providers,
    databases, or visibility calculations.
    """

    if len(window_set.windows) > _MAX_ELIGIBILITY_WINDOWS:
        raise ValidationError("eligibility conversion exceeds planning variable bound")
    set_checksum = eligibility_window_set_checksum(window_set)
    opportunities: list[ObservationOpportunity] = []
    for window in window_set.windows:
        duration = (window.end - window.start).total_seconds()
        opportunities.append(
            ObservationOpportunity(
                id=f"eligibility-{window.id}",
                satellite_id=window.asset_id,
                target_id=window.target_id,
                window=TimeWindow(start=window.start, end=window.end),
                mission_value=mission_value,
                duration_seconds=duration,
                energy_cost=energy_cost,
                storage_cost=storage_cost,
                source=f"declared-eligibility:{window.declaration_mode.value}",
                provenance=(
                    f"eligibility_window_set_checksum={set_checksum}; "
                    f"source_provenance_checksum={window.source_provenance_checksum}; "
                    "no computed access geometry"
                ),
                limitations=_NON_OPERATIONAL_LIMITATION,
            )
        )
    return tuple(opportunities)


def validate_request_against_eligibility(
    request: ObservationPlanningRequest,
    window_set: EligibilityWindowSet,
) -> None:
    """Validate that a declared planning request matches a pinned eligibility-window set."""

    expected = {
        (window.asset_id, window.target_id, window.start, window.end)
        for window in window_set.windows
    }
    for opportunity in request.opportunities:
        actual = (
            opportunity.satellite_id,
            opportunity.target_id,
            ensure_utc(opportunity.window.start),
            ensure_utc(opportunity.window.end),
        )
        if actual not in expected:
            raise ValidationError("planning request opportunity is not backed by eligibility set")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
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
    return value


def _normalize_optional_time(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    try:
        return ensure_utc(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be timezone-aware") from exc


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _require_clean_id(value: str, field_name: str) -> None:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be non-empty and unpadded")


def _require_clean_strings(
    values: tuple[str, ...],
    field_name: str,
    *,
    allow_empty_tuple: bool,
) -> None:
    if not allow_empty_tuple and not values:
        raise ValueError(f"{field_name} values are required")
    for value in values:
        if not value or value.strip() != value or len(value) > _MAX_LIMITATION_LENGTH:
            raise ValueError(f"{field_name} must be non-empty, unpadded, and bounded")


def _check_limitations_are_non_operational(limitations: tuple[str, ...]) -> None:
    _require_clean_strings(limitations, "limitation", allow_empty_tuple=False)
    forbidden_claims = (
        "operationally verified",
        "access confirmed",
        "verified visibility",
        "line of sight confirmed",
        "taskable",
        "command approved",
        "live validated",
    )
    joined = " ".join(limitations).lower()
    if any(claim in joined for claim in forbidden_claims):
        raise ValueError("limitations must not make operational or access-geometry claims")


def _require_compatible_window_mode(
    window: EligibilityWindow,
    provenance: PinnedInputProvenance,
) -> None:
    source_type = provenance.source.source_type
    if source_type == PinnedInputSourceType.FIXTURE:
        if window.declaration_mode != EligibilityDeclarationMode.FIXTURE_BACKED:
            raise ValueError("fixture provenance requires fixture-backed eligibility windows")
    elif source_type == PinnedInputSourceType.USER_DECLARED:
        if window.declaration_mode != EligibilityDeclarationMode.USER_DECLARED:
            raise ValueError("user-declared provenance requires user-declared eligibility windows")
    elif window.declaration_mode != EligibilityDeclarationMode.DERIVED_FROM_DECLARED_INPUT:
        raise ValueError("derived provenance requires derived eligibility windows")


def _window_sort_key(window: EligibilityWindow) -> tuple[str, str, str, str]:
    return (
        window.asset_id,
        window.target_id,
        window.start.isoformat(),
        window.id,
    )
