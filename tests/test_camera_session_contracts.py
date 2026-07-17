from __future__ import annotations

import builtins
import os
import socket
import uuid
from datetime import UTC, datetime, timedelta, timezone
from itertools import product
from typing import Any

import pytest
from pydantic import ValidationError

from orbitmind.camera import (
    CAMERA_DEVICE_LABEL_MAX_LENGTH,
    CAMERA_EPHEMERAL_TTL_SECONDS,
    CAMERA_MAX_ENCODED_BYTES,
    CAMERA_MAX_IMAGE_HEIGHT,
    CAMERA_MAX_IMAGE_WIDTH,
    CAMERA_SESSION_CONTRACT_VERSION,
    CameraApprovalStatus,
    CameraCaptureSource,
    CameraCreationGoal,
    CameraDeletionStatus,
    CameraEpistemicLabel,
    CameraFailureCode,
    CameraFrameFacts,
    CameraMediaType,
    CameraPermissionResult,
    CameraRetentionStatus,
    CameraSessionSnapshot,
    CameraSessionState,
    is_camera_terminal_state,
    is_camera_transition_allowed,
    validate_camera_transition,
)

CREATED_AT = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
EXPIRES_AT = CREATED_AT + timedelta(seconds=CAMERA_EPHEMERAL_TTL_SECONDS)
CHECKSUM = "a" * 64

EXPECTED_ENUM_VALUES = {
    CameraSessionState: {
        "inactive",
        "permission_pending",
        "preview_active",
        "frame_captured_ephemeral",
        "proposal_pending",
        "proposal_ready",
        "saved",
        "discarded",
        "expired",
        "failed",
    },
    CameraCreationGoal: {
        "describe_scene",
        "project_brief",
        "experiment_observation",
        "development_task",
        "research_question",
    },
    CameraPermissionResult: {
        "not_requested",
        "pending",
        "granted",
        "denied",
        "unavailable",
        "revoked",
    },
    CameraCaptureSource: {"local_camera"},
    CameraMediaType: {"image/jpeg", "image/png"},
    CameraApprovalStatus: {"not_requested", "pending", "approved", "rejected"},
    CameraRetentionStatus: {
        "none",
        "ephemeral",
        "persisted",
        "discarded",
        "expired",
        "deleted",
    },
    CameraDeletionStatus: {
        "not_applicable",
        "not_requested",
        "pending",
        "deleted",
        "failed",
    },
    CameraFailureCode: {
        "camera_not_supported",
        "camera_permission_denied",
        "camera_not_found",
        "camera_in_use",
        "camera_disconnected",
        "camera_start_failed",
        "capture_failed",
        "image_too_large",
        "image_dimensions_invalid",
        "image_type_invalid",
        "image_decode_failed",
        "temporary_storage_failed",
        "session_expired",
        "proposal_failed",
        "save_not_approved",
        "deletion_failed",
    },
    CameraEpistemicLabel: {
        "visual_observation",
        "user_supplied_context",
        "model_interpretation",
        "inferred",
        "uncertain",
        "not_independently_verified",
    },
}

ALLOWED_TRANSITIONS = {
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
    (CameraSessionState.FRAME_CAPTURED_EPHEMERAL, CameraSessionState.DISCARDED),
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


def _frame(**overrides: Any) -> CameraFrameFacts:
    values: dict[str, Any] = {
        "media_type": CameraMediaType.JPEG,
        "width": 1280,
        "height": 720,
        "encoded_size": 250_000,
        "content_checksum": CHECKSUM,
    }
    values.update(overrides)
    return CameraFrameFacts(**values)


def _snapshot(**overrides: Any) -> CameraSessionSnapshot:
    values: dict[str, Any] = {
        "session_id": "camera-session-001",
        "state": CameraSessionState.INACTIVE,
        "created_at": CREATED_AT,
        "expires_at": EXPIRES_AT,
        "permission_result": CameraPermissionResult.NOT_REQUESTED,
    }
    values.update(overrides)
    return CameraSessionSnapshot(**values)


def _valid_snapshot_values() -> list[dict[str, Any]]:
    frame = _frame()
    return [
        {},
        {
            "state": CameraSessionState.PERMISSION_PENDING,
            "permission_result": CameraPermissionResult.PENDING,
        },
        {
            "state": CameraSessionState.PREVIEW_ACTIVE,
            "permission_result": CameraPermissionResult.GRANTED,
        },
        {
            "state": CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": frame,
            "retention_status": CameraRetentionStatus.EPHEMERAL,
        },
        {
            "state": CameraSessionState.PROPOSAL_PENDING,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": frame,
            "creation_goal": CameraCreationGoal.PROJECT_BRIEF,
            "retention_status": CameraRetentionStatus.EPHEMERAL,
        },
        {
            "state": CameraSessionState.PROPOSAL_READY,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": frame,
            "creation_goal": CameraCreationGoal.PROJECT_BRIEF,
            "proposal_id": "proposal-001",
            "user_approval_status": CameraApprovalStatus.PENDING,
            "retention_status": CameraRetentionStatus.EPHEMERAL,
        },
        {
            "state": CameraSessionState.SAVED,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": frame,
            "creation_goal": CameraCreationGoal.PROJECT_BRIEF,
            "proposal_id": "proposal-001",
            "user_approval_status": CameraApprovalStatus.APPROVED,
            "retention_status": CameraRetentionStatus.PERSISTED,
            "frame_persisted": True,
            "deletion_status": CameraDeletionStatus.NOT_REQUESTED,
        },
        {
            "state": CameraSessionState.DISCARDED,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": frame,
            "retention_status": CameraRetentionStatus.DISCARDED,
            "user_approval_status": CameraApprovalStatus.REJECTED,
        },
        {
            "state": CameraSessionState.EXPIRED,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": frame,
            "retention_status": CameraRetentionStatus.EXPIRED,
            "failure_code": CameraFailureCode.SESSION_EXPIRED,
        },
        {
            "state": CameraSessionState.FAILED,
            "permission_result": CameraPermissionResult.DENIED,
            "failure_code": CameraFailureCode.CAMERA_PERMISSION_DENIED,
        },
    ]


def test_contract_constants_are_exact() -> None:
    assert CAMERA_SESSION_CONTRACT_VERSION == 1
    assert CAMERA_EPHEMERAL_TTL_SECONDS == 900
    assert CAMERA_MAX_IMAGE_WIDTH == 1920
    assert CAMERA_MAX_IMAGE_HEIGHT == 1080
    assert CAMERA_MAX_ENCODED_BYTES == 5_000_000
    assert CAMERA_DEVICE_LABEL_MAX_LENGTH == 128


@pytest.mark.parametrize(("enum_type", "expected"), EXPECTED_ENUM_VALUES.items())
def test_enum_values_are_exact_and_have_no_aliases(
    enum_type: type[Any], expected: set[str]
) -> None:
    assert {member.value for member in enum_type} == expected
    assert len(enum_type.__members__) == len(expected)
    with pytest.raises(ValueError):
        enum_type("unknown")


def test_frame_facts_accept_exact_boundaries() -> None:
    facts = _frame(
        width=CAMERA_MAX_IMAGE_WIDTH,
        height=CAMERA_MAX_IMAGE_HEIGHT,
        encoded_size=CAMERA_MAX_ENCODED_BYTES,
        media_type=CameraMediaType.PNG,
        content_checksum="0" * 64,
    )
    assert facts.width == 1920
    assert facts.height == 1080
    assert facts.encoded_size == 5_000_000


@pytest.mark.parametrize(
    "overrides",
    [
        {"width": 0},
        {"width": CAMERA_MAX_IMAGE_WIDTH + 1},
        {"height": 0},
        {"height": CAMERA_MAX_IMAGE_HEIGHT + 1},
        {"encoded_size": 0},
        {"encoded_size": CAMERA_MAX_ENCODED_BYTES + 1},
        {"width": True},
        {"height": 1.5},
        {"encoded_size": "10"},
        {"content_checksum": "a" * 63},
        {"content_checksum": "a" * 65},
        {"content_checksum": "A" * 64},
        {"content_checksum": f"{'a' * 32} {'a' * 31}"},
        {"content_checksum": "g" * 64},
    ],
)
def test_frame_facts_reject_invalid_bounds_types_and_checksum(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _frame(**overrides)


def test_frame_facts_reject_unknown_media_and_extra_content_fields() -> None:
    with pytest.raises(ValidationError):
        _frame(media_type="image/gif")
    with pytest.raises(ValidationError):
        CameraFrameFacts(
            media_type=CameraMediaType.JPEG,
            width=100,
            height=100,
            encoded_size=100,
            content_checksum=CHECKSUM,
            image_bytes="forbidden-extra-field",
        )


@pytest.mark.parametrize("overrides", _valid_snapshot_values())
def test_valid_snapshot_for_each_lifecycle_state(overrides: dict[str, Any]) -> None:
    snapshot = _snapshot(**overrides)
    assert snapshot.expires_at - snapshot.created_at == timedelta(seconds=900)


def test_snapshot_is_immutable_and_forbids_extra_fields() -> None:
    snapshot = _snapshot()
    with pytest.raises(ValidationError):
        snapshot.state = CameraSessionState.FAILED
    with pytest.raises(ValidationError):
        CameraSessionSnapshot(
            session_id="camera-session-001",
            state=CameraSessionState.INACTIVE,
            created_at=CREATED_AT,
            expires_at=EXPIRES_AT,
            permission_result=CameraPermissionResult.NOT_REQUESTED,
            raw_image="forbidden-extra-field",
        )


@pytest.mark.parametrize(
    "overrides",
    [
        {"contract_version": 2},
        {"contract_version": True},
        {"session_id": ""},
        {"session_id": " camera-session"},
        {"session_id": "camera/session"},
        {"owner_id": "owner with spaces"},
        {"proposal_id": "proposal-001"},
    ],
)
def test_snapshot_rejects_invalid_version_and_identifiers(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**overrides)


def test_snapshot_accepts_clean_optional_owner_and_proposal_ids() -> None:
    snapshot = _snapshot(
        state=CameraSessionState.PROPOSAL_READY,
        permission_result=CameraPermissionResult.GRANTED,
        frame_facts=_frame(),
        creation_goal=CameraCreationGoal.RESEARCH_QUESTION,
        proposal_id="proposal:2026.001",
        owner_id="local-owner_001",
        user_approval_status=CameraApprovalStatus.PENDING,
        retention_status=CameraRetentionStatus.EPHEMERAL,
    )
    assert snapshot.owner_id == "local-owner_001"


@pytest.mark.parametrize(
    "created_at,expires_at",
    [
        (CREATED_AT.replace(tzinfo=None), EXPIRES_AT),
        (CREATED_AT, EXPIRES_AT.replace(tzinfo=None)),
        (
            CREATED_AT.astimezone(timezone(timedelta(hours=5, minutes=30))),
            EXPIRES_AT,
        ),
        (
            CREATED_AT,
            EXPIRES_AT.astimezone(timezone(timedelta(hours=-4))),
        ),
        (CREATED_AT, EXPIRES_AT + timedelta(seconds=1)),
        (CREATED_AT, CREATED_AT + timedelta(seconds=899)),
    ],
)
def test_snapshot_rejects_non_utc_and_inexact_expiry(
    created_at: datetime, expires_at: datetime
) -> None:
    with pytest.raises(ValidationError):
        _snapshot(created_at=created_at, expires_at=expires_at)


@pytest.mark.parametrize(
    "label",
    [
        " Camera",
        "Camera ",
        "Camera\nHD",
        "Camera\rHD",
        "Camera\x00HD",
        "https://camera.example/device",
        "file:camera.txt",
        "data:image/png",
        "camera/device",
        "camera\\device",
        "x" * (CAMERA_DEVICE_LABEL_MAX_LENGTH + 1),
    ],
)
def test_device_label_rejects_unsafe_values(label: str) -> None:
    with pytest.raises(ValidationError):
        _snapshot(sanitized_device_label=label)


def test_device_label_accepts_clean_bounded_value() -> None:
    assert _snapshot(sanitized_device_label="Integrated Camera (Front)").sanitized_device_label


@pytest.mark.parametrize(
    "overrides",
    [
        {"state": CameraSessionState.INACTIVE, "frame_facts": _frame()},
        {
            "state": CameraSessionState.PERMISSION_PENDING,
            "permission_result": CameraPermissionResult.GRANTED,
        },
        {
            "state": CameraSessionState.PREVIEW_ACTIVE,
            "permission_result": CameraPermissionResult.PENDING,
        },
        {
            "state": CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
            "permission_result": CameraPermissionResult.GRANTED,
            "retention_status": CameraRetentionStatus.EPHEMERAL,
        },
        {
            "state": CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "retention_status": CameraRetentionStatus.EPHEMERAL,
            "proposal_id": "proposal-001",
        },
        {
            "state": CameraSessionState.PROPOSAL_PENDING,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "retention_status": CameraRetentionStatus.EPHEMERAL,
        },
        {
            "state": CameraSessionState.PROPOSAL_READY,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "creation_goal": CameraCreationGoal.PROJECT_BRIEF,
            "retention_status": CameraRetentionStatus.EPHEMERAL,
            "user_approval_status": CameraApprovalStatus.PENDING,
        },
        {
            "state": CameraSessionState.PROPOSAL_READY,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "creation_goal": CameraCreationGoal.PROJECT_BRIEF,
            "proposal_id": "proposal-001",
            "retention_status": CameraRetentionStatus.EPHEMERAL,
            "user_approval_status": CameraApprovalStatus.APPROVED,
        },
        {
            "state": CameraSessionState.SAVED,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "creation_goal": CameraCreationGoal.PROJECT_BRIEF,
            "proposal_id": "proposal-001",
            "retention_status": CameraRetentionStatus.PERSISTED,
            "user_approval_status": CameraApprovalStatus.APPROVED,
            "deletion_status": CameraDeletionStatus.NOT_REQUESTED,
        },
        {
            "state": CameraSessionState.DISCARDED,
            "permission_result": CameraPermissionResult.GRANTED,
            "retention_status": CameraRetentionStatus.NONE,
        },
        {
            "state": CameraSessionState.EXPIRED,
            "permission_result": CameraPermissionResult.GRANTED,
            "retention_status": CameraRetentionStatus.EXPIRED,
            "frame_persisted": True,
        },
        {
            "state": CameraSessionState.FAILED,
            "permission_result": CameraPermissionResult.UNAVAILABLE,
        },
    ],
)
def test_snapshot_rejects_cross_field_invariant_violations(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**overrides)


@pytest.mark.parametrize(
    "deletion_status,retention_status,frame_persisted,failure_code",
    [
        (
            CameraDeletionStatus.PENDING,
            CameraRetentionStatus.PERSISTED,
            True,
            None,
        ),
        (
            CameraDeletionStatus.FAILED,
            CameraRetentionStatus.PERSISTED,
            True,
            CameraFailureCode.DELETION_FAILED,
        ),
        (
            CameraDeletionStatus.DELETED,
            CameraRetentionStatus.DELETED,
            False,
            None,
        ),
    ],
)
def test_saved_snapshot_supports_immutable_deletion_metadata_revisions(
    deletion_status: CameraDeletionStatus,
    retention_status: CameraRetentionStatus,
    frame_persisted: bool,
    failure_code: CameraFailureCode | None,
) -> None:
    snapshot = _snapshot(
        state=CameraSessionState.SAVED,
        permission_result=CameraPermissionResult.GRANTED,
        frame_facts=_frame(),
        creation_goal=CameraCreationGoal.DESCRIBE_SCENE,
        proposal_id="proposal-001",
        user_approval_status=CameraApprovalStatus.APPROVED,
        retention_status=retention_status,
        frame_persisted=frame_persisted,
        deletion_status=deletion_status,
        failure_code=failure_code,
    )
    assert snapshot.deletion_status is deletion_status


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "state": CameraSessionState.SAVED,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "creation_goal": CameraCreationGoal.DESCRIBE_SCENE,
            "proposal_id": "proposal-001",
            "user_approval_status": CameraApprovalStatus.APPROVED,
            "retention_status": CameraRetentionStatus.PERSISTED,
            "frame_persisted": True,
            "deletion_status": CameraDeletionStatus.FAILED,
        },
        {
            "state": CameraSessionState.SAVED,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "creation_goal": CameraCreationGoal.DESCRIBE_SCENE,
            "proposal_id": "proposal-001",
            "user_approval_status": CameraApprovalStatus.APPROVED,
            "retention_status": CameraRetentionStatus.PERSISTED,
            "frame_persisted": True,
            "deletion_status": CameraDeletionStatus.NOT_REQUESTED,
            "failure_code": CameraFailureCode.DELETION_FAILED,
        },
        {
            "state": CameraSessionState.PROPOSAL_READY,
            "permission_result": CameraPermissionResult.GRANTED,
            "frame_facts": _frame(),
            "creation_goal": CameraCreationGoal.DESCRIBE_SCENE,
            "proposal_id": "proposal-001",
            "user_approval_status": CameraApprovalStatus.PENDING,
            "retention_status": CameraRetentionStatus.EPHEMERAL,
            "deletion_status": CameraDeletionStatus.PENDING,
        },
    ],
)
def test_deletion_invariants_reject_mismatched_or_premature_status(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _snapshot(**overrides)


def test_transition_policy_matches_the_complete_approved_graph() -> None:
    actual = {
        pair
        for pair in product(CameraSessionState, repeat=2)
        if is_camera_transition_allowed(*pair)
    }
    assert actual == ALLOWED_TRANSITIONS
    for pair in ALLOWED_TRANSITIONS:
        validate_camera_transition(*pair)


@pytest.mark.parametrize(
    ("previous", "following"),
    [
        (CameraSessionState.INACTIVE, CameraSessionState.SAVED),
        (CameraSessionState.PERMISSION_PENDING, CameraSessionState.PROPOSAL_READY),
        (CameraSessionState.PREVIEW_ACTIVE, CameraSessionState.PROPOSAL_PENDING),
        (CameraSessionState.FRAME_CAPTURED_EPHEMERAL, CameraSessionState.SAVED),
        (CameraSessionState.PROPOSAL_PENDING, CameraSessionState.SAVED),
    ],
)
def test_representative_invalid_transitions_are_rejected(
    previous: CameraSessionState, following: CameraSessionState
) -> None:
    assert not is_camera_transition_allowed(previous, following)
    with pytest.raises(ValueError, match=f"{previous.value} -> {following.value}"):
        validate_camera_transition(previous, following)


@pytest.mark.parametrize("state", list(CameraSessionState))
def test_self_transitions_are_rejected(state: CameraSessionState) -> None:
    assert not is_camera_transition_allowed(state, state)
    with pytest.raises(ValueError, match=f"{state.value} -> {state.value}"):
        validate_camera_transition(state, state)


@pytest.mark.parametrize(
    "state",
    [
        CameraSessionState.SAVED,
        CameraSessionState.DISCARDED,
        CameraSessionState.EXPIRED,
        CameraSessionState.FAILED,
    ],
)
def test_terminal_states_cannot_reopen(state: CameraSessionState) -> None:
    assert is_camera_terminal_state(state)
    assert all(
        not is_camera_transition_allowed(state, following) for following in CameraSessionState
    )


def test_contract_construction_has_no_io_network_camera_or_identifier_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("pure contract unexpectedly attempted a side effect")

    monkeypatch.setattr(builtins, "open", unexpected)
    monkeypatch.setattr(socket, "socket", unexpected)
    monkeypatch.setattr(os, "getenv", unexpected)
    monkeypatch.setattr(uuid, "uuid4", unexpected)

    snapshot = _snapshot()
    assert snapshot.session_id == "camera-session-001"
    assert is_camera_transition_allowed(
        CameraSessionState.INACTIVE, CameraSessionState.PERMISSION_PENDING
    )


def test_contract_models_expose_no_raw_image_or_camera_device_fields() -> None:
    fields = set(CameraFrameFacts.model_fields) | set(CameraSessionSnapshot.model_fields)
    assert not fields.intersection(
        {
            "blob",
            "bytes",
            "device",
            "device_id",
            "file_path",
            "image_bytes",
            "local_path",
            "original_filename",
            "raw_image",
            "stream",
        }
    )
