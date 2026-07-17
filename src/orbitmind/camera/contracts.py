"""Immutable contracts for local camera creation sessions."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

CAMERA_SESSION_CONTRACT_VERSION = 1
CAMERA_EPHEMERAL_TTL_SECONDS = 900
CAMERA_MAX_IMAGE_WIDTH = 1920
CAMERA_MAX_IMAGE_HEIGHT = 1080
CAMERA_MAX_ENCODED_BYTES = 5_000_000
CAMERA_DEVICE_LABEL_MAX_LENGTH = 128

_OPAQUE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$", re.ASCII)


class CameraSessionState(StrEnum):
    """Lifecycle states for a local camera creation session."""

    INACTIVE = "inactive"
    PERMISSION_PENDING = "permission_pending"
    PREVIEW_ACTIVE = "preview_active"
    FRAME_CAPTURED_EPHEMERAL = "frame_captured_ephemeral"
    PROPOSAL_PENDING = "proposal_pending"
    PROPOSAL_READY = "proposal_ready"
    SAVED = "saved"
    DISCARDED = "discarded"
    EXPIRED = "expired"
    FAILED = "failed"


class CameraCreationGoal(StrEnum):
    """Bounded local creation goals supported by the camera workflow."""

    DESCRIBE_SCENE = "describe_scene"
    PROJECT_BRIEF = "project_brief"
    EXPERIMENT_OBSERVATION = "experiment_observation"
    DEVELOPMENT_TASK = "development_task"
    RESEARCH_QUESTION = "research_question"


class CameraPermissionResult(StrEnum):
    """Browser camera-permission outcome."""

    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    GRANTED = "granted"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"
    REVOKED = "revoked"


class CameraCaptureSource(StrEnum):
    """Permitted capture source for this contract version."""

    LOCAL_CAMERA = "local_camera"


class CameraMediaType(StrEnum):
    """Permitted encoded image media types."""

    JPEG = "image/jpeg"
    PNG = "image/png"


class CameraApprovalStatus(StrEnum):
    """Human approval status for a creation proposal."""

    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class CameraRetentionStatus(StrEnum):
    """Retention state for captured image content."""

    NONE = "none"
    EPHEMERAL = "ephemeral"
    PERSISTED = "persisted"
    DISCARDED = "discarded"
    EXPIRED = "expired"
    DELETED = "deleted"


class CameraDeletionStatus(StrEnum):
    """Deletion status for approved persisted image content."""

    NOT_APPLICABLE = "not_applicable"
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    DELETED = "deleted"
    FAILED = "failed"


class CameraFailureCode(StrEnum):
    """Bounded failure reasons for camera session processing."""

    CAMERA_NOT_SUPPORTED = "camera_not_supported"
    CAMERA_PERMISSION_DENIED = "camera_permission_denied"
    CAMERA_NOT_FOUND = "camera_not_found"
    CAMERA_IN_USE = "camera_in_use"
    CAMERA_DISCONNECTED = "camera_disconnected"
    CAMERA_START_FAILED = "camera_start_failed"
    CAPTURE_FAILED = "capture_failed"
    IMAGE_TOO_LARGE = "image_too_large"
    IMAGE_DIMENSIONS_INVALID = "image_dimensions_invalid"
    IMAGE_TYPE_INVALID = "image_type_invalid"
    IMAGE_DECODE_FAILED = "image_decode_failed"
    TEMPORARY_STORAGE_FAILED = "temporary_storage_failed"
    SESSION_EXPIRED = "session_expired"
    PROPOSAL_FAILED = "proposal_failed"
    SAVE_NOT_APPROVED = "save_not_approved"
    DELETION_FAILED = "deletion_failed"


class CameraEpistemicLabel(StrEnum):
    """Epistemic labels available to downstream camera-derived outputs."""

    VISUAL_OBSERVATION = "visual_observation"
    USER_SUPPLIED_CONTEXT = "user_supplied_context"
    MODEL_INTERPRETATION = "model_interpretation"
    INFERRED = "inferred"
    UNCERTAIN = "uncertain"
    NOT_INDEPENDENTLY_VERIFIED = "not_independently_verified"


class CameraFrameFacts(BaseModel):
    """Validated non-content facts about one encoded camera frame."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    media_type: CameraMediaType
    width: StrictInt = Field(ge=1, le=CAMERA_MAX_IMAGE_WIDTH)
    height: StrictInt = Field(ge=1, le=CAMERA_MAX_IMAGE_HEIGHT)
    encoded_size: StrictInt = Field(ge=1, le=CAMERA_MAX_ENCODED_BYTES)
    content_checksum: StrictStr = Field(pattern=r"^[0-9a-f]{64}$")


class CameraSessionSnapshot(BaseModel):
    """Immutable validated snapshot of one local camera session."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: StrictInt = CAMERA_SESSION_CONTRACT_VERSION
    session_id: StrictStr
    owner_id: StrictStr | None = None
    state: CameraSessionState
    creation_goal: CameraCreationGoal | None = None
    created_at: datetime
    expires_at: datetime
    permission_result: CameraPermissionResult
    frame_facts: CameraFrameFacts | None = None
    capture_source: CameraCaptureSource = CameraCaptureSource.LOCAL_CAMERA
    sanitized_device_label: StrictStr | None = Field(
        default=None,
        min_length=1,
        max_length=CAMERA_DEVICE_LABEL_MAX_LENGTH,
    )
    frame_persisted: StrictBool = False
    proposal_id: StrictStr | None = None
    user_approval_status: CameraApprovalStatus = CameraApprovalStatus.NOT_REQUESTED
    retention_status: CameraRetentionStatus = CameraRetentionStatus.NONE
    deletion_status: CameraDeletionStatus = CameraDeletionStatus.NOT_APPLICABLE
    failure_code: CameraFailureCode | None = None

    @field_validator("contract_version")
    @classmethod
    def _validate_contract_version(cls, value: int) -> int:
        if value != CAMERA_SESSION_CONTRACT_VERSION:
            raise ValueError("contract_version must equal CAMERA_SESSION_CONTRACT_VERSION")
        return value

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str) -> str:
        return _require_opaque_identifier(value, field_name="session_id", max_length=160)

    @field_validator("owner_id")
    @classmethod
    def _validate_owner_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_opaque_identifier(value, field_name="owner_id", max_length=120)

    @field_validator("proposal_id")
    @classmethod
    def _validate_proposal_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _require_opaque_identifier(value, field_name="proposal_id", max_length=160)

    @field_validator("created_at", "expires_at")
    @classmethod
    def _validate_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("camera session timestamps must be timezone-aware UTC")
        if value.utcoffset() != timedelta(0):
            raise ValueError("camera session timestamps must use UTC, not a non-UTC offset")
        return value

    @field_validator("sanitized_device_label")
    @classmethod
    def _validate_sanitized_device_label(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip():
            raise ValueError("sanitized_device_label must not contain outer whitespace")
        if any(unicodedata.category(character) == "Cc" for character in value):
            raise ValueError("sanitized_device_label must not contain control characters")
        lowered = value.casefold()
        if "/" in value or "\\" in value or "://" in value:
            raise ValueError("sanitized_device_label must not contain a path or URL")
        if lowered.startswith(("data:", "file:")):
            raise ValueError("sanitized_device_label must not contain a path or URL")
        return value

    @model_validator(mode="after")
    def _validate_snapshot_invariants(self) -> Self:
        if self.expires_at - self.created_at != timedelta(seconds=CAMERA_EPHEMERAL_TTL_SECONDS):
            raise ValueError("expires_at must equal created_at plus CAMERA_EPHEMERAL_TTL_SECONDS")

        if self.proposal_id is not None and self.creation_goal is None:
            raise ValueError("creation_goal is required when proposal_id is present")
        if self.user_approval_status is CameraApprovalStatus.APPROVED and (
            self.state is not CameraSessionState.SAVED
        ):
            raise ValueError("approved user_approval_status is valid only for saved state")
        if self.frame_persisted and not (
            self.state is CameraSessionState.SAVED
            and self.retention_status is CameraRetentionStatus.PERSISTED
        ):
            raise ValueError("frame_persisted requires saved state with persisted retention_status")

        self._validate_deletion_invariants()
        self._validate_failure_invariants()
        self._validate_state_specific_invariants()
        return self

    def _validate_deletion_invariants(self) -> None:
        if self.deletion_status is CameraDeletionStatus.PENDING and not (
            self.state is CameraSessionState.SAVED
            and self.user_approval_status is CameraApprovalStatus.APPROVED
            and self.retention_status is CameraRetentionStatus.PERSISTED
            and self.frame_persisted
        ):
            raise ValueError("pending deletion requires an approved persisted frame in saved state")
        if self.deletion_status is CameraDeletionStatus.DELETED and not (
            self.state is CameraSessionState.SAVED
            and self.retention_status is CameraRetentionStatus.DELETED
            and not self.frame_persisted
        ):
            raise ValueError("deleted deletion_status requires saved state with deleted retention")
        deletion_failed = self.deletion_status is CameraDeletionStatus.FAILED
        failure_is_deletion = self.failure_code is CameraFailureCode.DELETION_FAILED
        if deletion_failed != failure_is_deletion:
            raise ValueError(
                "deletion_failed failure_code and failed deletion_status must occur together"
            )
        if deletion_failed and not (
            self.state is CameraSessionState.SAVED
            and self.user_approval_status is CameraApprovalStatus.APPROVED
            and self.retention_status is CameraRetentionStatus.PERSISTED
            and self.frame_persisted
        ):
            raise ValueError("failed deletion requires an approved persisted frame in saved state")

    def _validate_failure_invariants(self) -> None:
        if self.state is CameraSessionState.FAILED:
            if self.failure_code is None:
                raise ValueError("failed state requires failure_code")
            if self.failure_code in {
                CameraFailureCode.SESSION_EXPIRED,
                CameraFailureCode.DELETION_FAILED,
            }:
                raise ValueError("failed state requires a non-expiry, non-deletion failure_code")
            return

        if self.state is CameraSessionState.EXPIRED:
            if self.failure_code not in {None, CameraFailureCode.SESSION_EXPIRED}:
                raise ValueError("expired state permits only session_expired failure_code")
            return

        if (
            self.state is CameraSessionState.SAVED
            and self.deletion_status is CameraDeletionStatus.FAILED
        ):
            return

        if self.failure_code is not None:
            raise ValueError("failure_code is not valid for the current state")

    def _validate_state_specific_invariants(self) -> None:
        validators = {
            CameraSessionState.INACTIVE: self._validate_inactive,
            CameraSessionState.PERMISSION_PENDING: self._validate_permission_pending,
            CameraSessionState.PREVIEW_ACTIVE: self._validate_preview_active,
            CameraSessionState.FRAME_CAPTURED_EPHEMERAL: self._validate_frame_captured,
            CameraSessionState.PROPOSAL_PENDING: self._validate_proposal_pending,
            CameraSessionState.PROPOSAL_READY: self._validate_proposal_ready,
            CameraSessionState.SAVED: self._validate_saved,
            CameraSessionState.DISCARDED: self._validate_discarded,
            CameraSessionState.EXPIRED: self._validate_expired,
            CameraSessionState.FAILED: self._validate_failed,
        }
        validators[self.state]()

    def _validate_inactive(self) -> None:
        self._require_common_pre_capture(permission_result=CameraPermissionResult.NOT_REQUESTED)

    def _validate_permission_pending(self) -> None:
        self._require_common_pre_capture(permission_result=CameraPermissionResult.PENDING)

    def _validate_preview_active(self) -> None:
        self._require_common_pre_capture(permission_result=CameraPermissionResult.GRANTED)

    def _require_common_pre_capture(self, *, permission_result: CameraPermissionResult) -> None:
        if self.permission_result is not permission_result:
            raise ValueError(
                f"{self.state.value} requires permission_result={permission_result.value}"
            )
        if self.frame_facts is not None or self.frame_persisted:
            raise ValueError(f"{self.state.value} must not contain captured frame facts")
        if self.proposal_id is not None or self.creation_goal is not None:
            raise ValueError(f"{self.state.value} must not contain proposal data")
        if self.retention_status is not CameraRetentionStatus.NONE:
            raise ValueError(f"{self.state.value} requires retention_status=none")
        if self.user_approval_status is not CameraApprovalStatus.NOT_REQUESTED:
            raise ValueError(f"{self.state.value} cannot have user approval")
        if self.deletion_status is not CameraDeletionStatus.NOT_APPLICABLE:
            raise ValueError(f"{self.state.value} cannot have deletion status")

    def _validate_frame_captured(self) -> None:
        self._require_ephemeral_frame()
        if self.proposal_id is not None:
            raise ValueError("frame_captured_ephemeral must not contain proposal_id")
        if self.user_approval_status is not CameraApprovalStatus.NOT_REQUESTED:
            raise ValueError("frame_captured_ephemeral cannot have user approval")

    def _validate_proposal_pending(self) -> None:
        self._require_ephemeral_frame()
        if self.creation_goal is None:
            raise ValueError("proposal_pending requires creation_goal")
        if self.proposal_id is not None:
            raise ValueError("proposal_pending must not contain proposal_id")
        if self.user_approval_status is not CameraApprovalStatus.NOT_REQUESTED:
            raise ValueError("proposal_pending cannot have user approval")

    def _validate_proposal_ready(self) -> None:
        self._require_ephemeral_frame()
        if self.creation_goal is None or self.proposal_id is None:
            raise ValueError("proposal_ready requires creation_goal and proposal_id")
        if self.user_approval_status is not CameraApprovalStatus.PENDING:
            raise ValueError("proposal_ready requires pending user approval")

    def _require_ephemeral_frame(self) -> None:
        if self.permission_result is not CameraPermissionResult.GRANTED:
            raise ValueError(f"{self.state.value} requires granted camera permission")
        if self.frame_facts is None:
            raise ValueError(f"{self.state.value} requires frame_facts")
        if self.retention_status is not CameraRetentionStatus.EPHEMERAL:
            raise ValueError(f"{self.state.value} requires ephemeral retention")
        if self.frame_persisted:
            raise ValueError(f"{self.state.value} cannot persist the frame")
        if self.deletion_status is not CameraDeletionStatus.NOT_APPLICABLE:
            raise ValueError(f"{self.state.value} cannot have deletion status")

    def _validate_saved(self) -> None:
        if self.permission_result is not CameraPermissionResult.GRANTED:
            raise ValueError("saved state requires granted camera permission")
        if self.frame_facts is None:
            raise ValueError("saved state requires frame_facts")
        if self.creation_goal is None or self.proposal_id is None:
            raise ValueError("saved state requires creation_goal and proposal_id")
        if self.user_approval_status is not CameraApprovalStatus.APPROVED:
            raise ValueError("saved state requires approved user approval")
        if self.retention_status is CameraRetentionStatus.PERSISTED:
            if not self.frame_persisted:
                raise ValueError("persisted saved state requires frame_persisted=true")
            if self.deletion_status not in {
                CameraDeletionStatus.NOT_REQUESTED,
                CameraDeletionStatus.PENDING,
                CameraDeletionStatus.FAILED,
            }:
                raise ValueError("persisted saved state has invalid deletion_status")
            return
        if self.retention_status is CameraRetentionStatus.DELETED:
            if self.frame_persisted:
                raise ValueError("deleted saved state requires frame_persisted=false")
            if self.deletion_status is not CameraDeletionStatus.DELETED:
                raise ValueError("deleted saved state requires deletion_status=deleted")
            return
        raise ValueError("saved state requires persisted or deleted retention_status")

    def _validate_discarded(self) -> None:
        if self.retention_status is not CameraRetentionStatus.DISCARDED:
            raise ValueError("discarded state requires discarded retention_status")
        if self.frame_persisted:
            raise ValueError("discarded state requires frame_persisted=false")
        if self.deletion_status is not CameraDeletionStatus.NOT_APPLICABLE:
            raise ValueError("discarded state cannot have deletion status")
        if self.user_approval_status not in {
            CameraApprovalStatus.NOT_REQUESTED,
            CameraApprovalStatus.REJECTED,
        }:
            raise ValueError("discarded state has invalid user approval status")

    def _validate_expired(self) -> None:
        if self.retention_status is not CameraRetentionStatus.EXPIRED:
            raise ValueError("expired state requires expired retention_status")
        if self.frame_persisted:
            raise ValueError("expired state requires frame_persisted=false")
        if self.deletion_status is not CameraDeletionStatus.NOT_APPLICABLE:
            raise ValueError("expired state cannot have deletion status")
        if self.user_approval_status is CameraApprovalStatus.APPROVED:
            raise ValueError("expired state cannot have approved user approval")

    def _validate_failed(self) -> None:
        if self.frame_persisted:
            raise ValueError("failed state requires frame_persisted=false")
        if self.retention_status not in {
            CameraRetentionStatus.NONE,
            CameraRetentionStatus.EPHEMERAL,
            CameraRetentionStatus.DISCARDED,
            CameraRetentionStatus.EXPIRED,
        }:
            raise ValueError("failed state has invalid retention_status")
        if self.deletion_status is not CameraDeletionStatus.NOT_APPLICABLE:
            raise ValueError("failed state cannot have deletion status")
        if self.user_approval_status is CameraApprovalStatus.APPROVED:
            raise ValueError("failed state cannot have approved user approval")


_ALLOWED_TRANSITIONS = frozenset(
    {
        (CameraSessionState.INACTIVE, CameraSessionState.PERMISSION_PENDING),
        (CameraSessionState.INACTIVE, CameraSessionState.DISCARDED),
        (CameraSessionState.INACTIVE, CameraSessionState.FAILED),
        (CameraSessionState.PERMISSION_PENDING, CameraSessionState.PREVIEW_ACTIVE),
        (CameraSessionState.PERMISSION_PENDING, CameraSessionState.DISCARDED),
        (CameraSessionState.PERMISSION_PENDING, CameraSessionState.FAILED),
        (
            CameraSessionState.PREVIEW_ACTIVE,
            CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
        ),
        (CameraSessionState.PREVIEW_ACTIVE, CameraSessionState.DISCARDED),
        (CameraSessionState.PREVIEW_ACTIVE, CameraSessionState.FAILED),
        (
            CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
            CameraSessionState.PROPOSAL_PENDING,
        ),
        (
            CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
            CameraSessionState.PERMISSION_PENDING,
        ),
        (
            CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
            CameraSessionState.DISCARDED,
        ),
        (CameraSessionState.FRAME_CAPTURED_EPHEMERAL, CameraSessionState.EXPIRED),
        (CameraSessionState.FRAME_CAPTURED_EPHEMERAL, CameraSessionState.FAILED),
        (CameraSessionState.PROPOSAL_PENDING, CameraSessionState.PROPOSAL_READY),
        (CameraSessionState.PROPOSAL_PENDING, CameraSessionState.DISCARDED),
        (CameraSessionState.PROPOSAL_PENDING, CameraSessionState.EXPIRED),
        (CameraSessionState.PROPOSAL_PENDING, CameraSessionState.FAILED),
        (CameraSessionState.PROPOSAL_READY, CameraSessionState.SAVED),
        (CameraSessionState.PROPOSAL_READY, CameraSessionState.DISCARDED),
        (CameraSessionState.PROPOSAL_READY, CameraSessionState.EXPIRED),
        (CameraSessionState.PROPOSAL_READY, CameraSessionState.FAILED),
    }
)

_TERMINAL_STATES = frozenset(
    {
        CameraSessionState.SAVED,
        CameraSessionState.DISCARDED,
        CameraSessionState.EXPIRED,
        CameraSessionState.FAILED,
    }
)


def is_camera_transition_allowed(
    previous: CameraSessionState, following: CameraSessionState
) -> bool:
    """Return whether a state transition is permitted by contract version 1."""

    return (previous, following) in _ALLOWED_TRANSITIONS


def validate_camera_transition(previous: CameraSessionState, following: CameraSessionState) -> None:
    """Raise when a camera session state transition is not permitted."""

    if not is_camera_transition_allowed(previous, following):
        raise ValueError(f"camera transition {previous.value} -> {following.value} is not allowed")


def is_camera_terminal_state(state: CameraSessionState) -> bool:
    """Return whether the state terminates the camera session lifecycle."""

    return state in _TERMINAL_STATES


def _require_opaque_identifier(value: str, *, field_name: str, max_length: int) -> str:
    if not value or len(value) > max_length:
        raise ValueError(f"{field_name} must contain 1 to {max_length} characters")
    if value != value.strip() or _OPAQUE_IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a clean opaque identifier")
    return value
