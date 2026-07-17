"""Immutable, inert creation proposals for ephemeral camera-media sessions."""

from __future__ import annotations

import re
import secrets
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import MappingProxyType

from orbitmind.camera.contracts import (
    CameraFrameFacts,
    CameraMediaType,
    CameraRetentionStatus,
)

CAMERA_CREATION_PROPOSAL_CONTRACT_VERSION = 1
CAMERA_PROPOSAL_CONTEXT_MAX_CODEPOINTS = 500
CAMERA_PROPOSAL_STATE = "proposal_only"
CAMERA_PROPOSAL_EXECUTION_STATUS = "not_authorized"
CAMERA_PROPOSAL_ANALYSIS_STATUS = "not_performed"

_OPAQUE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)


class CameraCreationGoal(StrEnum):
    """Closed, non-operational intent taxonomy for camera creation proposals."""

    VISUAL_REFERENCE = "visual_reference"
    DOCUMENTATION = "documentation"
    TRANSFORMATION_REQUEST = "transformation_request"
    EXPLANATION_REQUEST = "explanation_request"
    OTHER = "other"


CAMERA_CREATION_GOAL_LABELS: Mapping[CameraCreationGoal, str] = MappingProxyType(
    {
        CameraCreationGoal.VISUAL_REFERENCE: "Use as a visual reference",
        CameraCreationGoal.DOCUMENTATION: "Prepare documentation",
        CameraCreationGoal.TRANSFORMATION_REQUEST: "Prepare a transformation request",
        CameraCreationGoal.EXPLANATION_REQUEST: "Prepare an explanation request",
        CameraCreationGoal.OTHER: "Other",
    }
)


class CameraProposalValidationError(ValueError):
    """Stable, sanitized validation failure for proposal inputs."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CameraCreationProposalRequest:
    """Strict, normalized user intent before an inert proposal is created."""

    goal: CameraCreationGoal
    user_context: str | None

    def __post_init__(self) -> None:
        """Require direct construction to use the same normalized closed contract."""

        if type(self.goal) is not CameraCreationGoal:
            raise ValueError("camera proposal goal is invalid")
        if self.user_context != normalize_user_context(self.user_context, goal=self.goal):
            raise ValueError("camera proposal context is not normalized")

    @classmethod
    def from_json_object(cls, value: object) -> CameraCreationProposalRequest:
        """Create one strict request from an already-decoded JSON object."""

        if type(value) is not dict or set(value) != {"goal", "user_context"}:
            raise CameraProposalValidationError("camera_proposal_request_invalid")

        raw_goal = value["goal"]
        if type(raw_goal) is not str:
            raise CameraProposalValidationError("camera_proposal_goal_invalid")
        try:
            goal = CameraCreationGoal(raw_goal)
        except ValueError as exc:
            raise CameraProposalValidationError("camera_proposal_goal_invalid") from exc

        context = normalize_user_context(value["user_context"], goal=goal)
        return cls(goal=goal, user_context=context)


@dataclass(frozen=True, slots=True)
class CameraCreationProposal:
    """One non-executing, in-memory statement of user intent."""

    contract_version: int
    proposal_id: str
    session_id: str
    goal: CameraCreationGoal
    user_context: str | None
    state: str
    execution_status: str
    analysis_status: str
    created_at: datetime
    expires_at: datetime
    media_type: CameraMediaType
    width: int
    height: int
    encoded_size: int
    content_checksum: str
    retention_status: CameraRetentionStatus
    human_approval_required: bool

    def __post_init__(self) -> None:
        """Reject malformed internal contracts before they can be attached to a session."""

        if self.contract_version != CAMERA_CREATION_PROPOSAL_CONTRACT_VERSION:
            raise ValueError("camera proposal contract version is invalid")
        if _OPAQUE_IDENTIFIER_PATTERN.fullmatch(self.proposal_id) is None:
            raise ValueError("camera proposal identifier is invalid")
        if _OPAQUE_IDENTIFIER_PATTERN.fullmatch(self.session_id) is None:
            raise ValueError("camera proposal session identifier is invalid")
        if type(self.goal) is not CameraCreationGoal:
            raise ValueError("camera proposal goal is invalid")
        if self.user_context != normalize_user_context(self.user_context, goal=self.goal):
            raise ValueError("camera proposal context is not normalized")
        if (
            self.state != CAMERA_PROPOSAL_STATE
            or self.execution_status != CAMERA_PROPOSAL_EXECUTION_STATUS
            or self.analysis_status != CAMERA_PROPOSAL_ANALYSIS_STATUS
            or self.retention_status is not CameraRetentionStatus.EPHEMERAL
            or self.human_approval_required is not True
        ):
            raise ValueError("camera proposal semantics are invalid")
        _validate_utc(self.created_at, field_name="created_at")
        _validate_utc(self.expires_at, field_name="expires_at")
        if self.created_at > self.expires_at:
            raise ValueError("camera proposal expiry must not precede creation")
        if type(self.media_type) is not CameraMediaType:
            raise ValueError("camera proposal media type is invalid")
        if (
            type(self.width) is not int
            or type(self.height) is not int
            or type(self.encoded_size) is not int
            or self.width < 1
            or self.height < 1
            or self.encoded_size < 1
            or not isinstance(self.content_checksum, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.content_checksum, re.ASCII) is None
        ):
            raise ValueError("camera proposal media facts are invalid")

    def to_response(self) -> dict[str, object]:
        """Return the exact public record without capabilities or media locations."""

        return {
            "contract_version": self.contract_version,
            "proposal_id": self.proposal_id,
            "session_id": self.session_id,
            "goal": self.goal.value,
            "user_context": self.user_context,
            "state": self.state,
            "execution_status": self.execution_status,
            "analysis_status": self.analysis_status,
            "created_at": _format_utc(self.created_at),
            "expires_at": _format_utc(self.expires_at),
            "media_type": self.media_type.value,
            "width": self.width,
            "height": self.height,
            "encoded_size": self.encoded_size,
            "content_checksum": self.content_checksum,
            "retention_status": self.retention_status.value,
            "human_approval_required": self.human_approval_required,
        }


def normalize_user_context(value: object, *, goal: CameraCreationGoal) -> str | None:
    """Normalize inert plain text, allowing only ordinary spaces and LF line breaks."""

    if value is None:
        normalized: str | None = None
    elif type(value) is str:
        normalized = unicodedata.normalize(
            "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
        ).strip()
        if "\x00" in normalized or any(
            unicodedata.category(character) == "Cc" and character != "\n"
            for character in normalized
        ):
            raise CameraProposalValidationError("camera_proposal_context_invalid")
        if len(normalized) > CAMERA_PROPOSAL_CONTEXT_MAX_CODEPOINTS:
            raise CameraProposalValidationError("camera_proposal_context_invalid")
    else:
        raise CameraProposalValidationError("camera_proposal_context_invalid")

    if goal is CameraCreationGoal.OTHER and not normalized:
        raise CameraProposalValidationError("camera_proposal_context_invalid")
    return normalized


def create_camera_creation_proposal(
    *,
    request: CameraCreationProposalRequest,
    session_id: str,
    created_at: datetime,
    expires_at: datetime,
    frame_facts: CameraFrameFacts,
) -> CameraCreationProposal:
    """Create one proposal entirely from request intent and stored session facts."""

    proposal_id = secrets.token_urlsafe(32)
    return CameraCreationProposal(
        contract_version=CAMERA_CREATION_PROPOSAL_CONTRACT_VERSION,
        proposal_id=proposal_id,
        session_id=session_id,
        goal=request.goal,
        user_context=request.user_context,
        state=CAMERA_PROPOSAL_STATE,
        execution_status=CAMERA_PROPOSAL_EXECUTION_STATUS,
        analysis_status=CAMERA_PROPOSAL_ANALYSIS_STATUS,
        created_at=created_at,
        expires_at=expires_at,
        media_type=frame_facts.media_type,
        width=frame_facts.width,
        height=frame_facts.height,
        encoded_size=frame_facts.encoded_size,
        content_checksum=frame_facts.content_checksum,
        retention_status=CameraRetentionStatus.EPHEMERAL,
        human_approval_required=True,
    )


def _validate_utc(value: datetime, *, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError(f"camera proposal {field_name} must be UTC")


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
