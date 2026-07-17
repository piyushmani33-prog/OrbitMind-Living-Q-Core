"""Application-scoped ephemeral camera-media storage and capability authority."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import threading
from contextlib import suppress
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orbitmind.camera.contracts import (
    CAMERA_EPHEMERAL_TTL_SECONDS,
    CAMERA_SESSION_CONTRACT_VERSION,
    CameraDeletionStatus,
    CameraFailureCode,
    CameraFrameFacts,
    CameraMediaType,
    CameraRetentionStatus,
    CameraSessionState,
)
from orbitmind.camera.csrf import CAMERA_OPAQUE_SECRET_BYTES
from orbitmind.camera.media import CameraMediaError, CameraMediaNormalizer
from orbitmind.camera.proposal import (
    CameraCreationProposal,
    CameraCreationProposalRequest,
    create_camera_creation_proposal,
)
from orbitmind.camera.runtime import CameraMediaRuntimeContext

CAMERA_MEDIA_MAX_ACTIVE_SESSIONS = 8
CAMERA_MEDIA_MAX_AGGREGATE_BYTES = 40_000_000
CAMERA_MEDIA_CAPABILITY_HEADER = "X-OrbitMind-Camera-Capability"

_OPAQUE_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)
_OWNED_MEDIA_PATTERN = re.compile(
    r"^[A-Za-z0-9_-]{43}\.(?:jpg|png)(?:\.part)?$",
    re.ASCII,
)
_WINDOWS_REPARSE_POINT = 0x400


@dataclass(frozen=True, slots=True, repr=False)
class CameraMediaSessionMetadata:
    """The metadata-only public view of one ephemeral media session."""

    contract_version: int
    session_id: str
    state: CameraSessionState
    created_at: datetime
    expires_at: datetime
    media_type: CameraMediaType
    width: int
    height: int
    encoded_size: int
    content_checksum: str
    retention_status: CameraRetentionStatus

    def to_response(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "session_id": self.session_id,
            "state": self.state.value,
            "created_at": _format_utc(self.created_at),
            "expires_at": _format_utc(self.expires_at),
            "media_type": self.media_type.value,
            "width": self.width,
            "height": self.height,
            "encoded_size": self.encoded_size,
            "content_checksum": self.content_checksum,
            "retention_status": self.retention_status.value,
        }


@dataclass(frozen=True, slots=True, repr=False)
class CameraMediaSessionCreation:
    """One-time plaintext capability paired with public session metadata."""

    metadata: CameraMediaSessionMetadata
    session_capability: str


@dataclass(frozen=True, slots=True)
class CameraMediaShutdownReport:
    """Bounded cleanup result retained after service shutdown."""

    attempted_files: int
    deleted_files: int
    failed_files: int
    removed_partial_files: int
    failed_partial_files: int


@dataclass(frozen=True, slots=True, repr=False)
class _CameraMediaSessionRecord:
    session_id: str
    capability_digest: bytes
    created_at: datetime
    expires_at: datetime
    state: CameraSessionState
    frame_facts: CameraFrameFacts
    media_path: Path
    retention_status: CameraRetentionStatus
    frame_persisted: bool
    deletion_status: CameraDeletionStatus
    failure_code: CameraFailureCode | None
    proposal: CameraCreationProposal | None

    def metadata(self) -> CameraMediaSessionMetadata:
        return CameraMediaSessionMetadata(
            contract_version=CAMERA_SESSION_CONTRACT_VERSION,
            session_id=self.session_id,
            state=self.state,
            created_at=self.created_at,
            expires_at=self.expires_at,
            media_type=self.frame_facts.media_type,
            width=self.frame_facts.width,
            height=self.frame_facts.height,
            encoded_size=self.frame_facts.encoded_size,
            content_checksum=self.frame_facts.content_checksum,
            retention_status=self.retention_status,
        )


class CameraMediaService:
    """Synchronized, bounded owner of ephemeral normalized camera files."""

    def __init__(
        self,
        context: CameraMediaRuntimeContext,
        *,
        normalizer: CameraMediaNormalizer | None = None,
    ) -> None:
        self._context = context
        self._root = context.media_root
        self._normalizer = normalizer or CameraMediaNormalizer()
        self._records: dict[str, _CameraMediaSessionRecord] = {}
        self._aggregate_bytes = 0
        self._lock = threading.Lock()
        self._started = False
        self._closed = False
        self._shutdown_report: CameraMediaShutdownReport | None = None

    @property
    def media_root(self) -> Path:
        return self._root

    @property
    def active_session_count(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def aggregate_normalized_bytes(self) -> int:
        with self._lock:
            return self._aggregate_bytes

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def shutdown_report(self) -> CameraMediaShutdownReport | None:
        with self._lock:
            return self._shutdown_report

    def start(self) -> None:
        """Validate the injected root, initialize it, and remove only owned stale files."""

        with self._lock:
            if self._closed:
                raise RuntimeError("camera media service is closed")
            if self._started:
                return
            self._initialize_root_locked()
            self._started = True

    def create(
        self,
        content: bytes,
        declared_media_type: CameraMediaType,
    ) -> CameraMediaSessionCreation:
        normalized = self._normalizer.normalize(content, declared_media_type)
        session_id = _generate_secret(self._context.media_session_id_generator)
        capability = _generate_secret(self._context.media_capability_generator)
        if hmac.compare_digest(session_id, capability):
            raise CameraMediaError("camera_invalid_state", 409)
        capability_digest = hashlib.sha256(capability.encode("ascii")).digest()
        created_at = self._utc_now()
        expires_at = created_at + timedelta(seconds=CAMERA_EPHEMERAL_TTL_SECONDS)

        with self._lock:
            self._require_available_locked()
            self._cleanup_expired_locked(created_at)
            if (
                len(self._records) >= CAMERA_MEDIA_MAX_ACTIVE_SESSIONS
                or self._aggregate_bytes + normalized.facts.encoded_size
                > CAMERA_MEDIA_MAX_AGGREGATE_BYTES
            ):
                raise CameraMediaError("camera_ephemeral_capacity_exceeded", 409)
            if session_id in self._records:
                raise CameraMediaError("camera_invalid_state", 409)
            if any(
                hmac.compare_digest(capability_digest, record.capability_digest)
                for record in self._records.values()
            ):
                raise CameraMediaError("camera_invalid_state", 409)

            final_path = self._owned_path(session_id + normalized.extension)
            partial_path = self._owned_path(final_path.name + ".part")
            if final_path.exists() or partial_path.exists():
                raise CameraMediaError("temporary_storage_failed", 503)
            try:
                with partial_path.open("xb") as output:
                    output.write(normalized.content)
                    output.flush()
                    os.fsync(output.fileno())
                partial_path.replace(final_path)
            except OSError as exc:
                _best_effort_unlink(partial_path)
                raise CameraMediaError("temporary_storage_failed", 503) from exc

            record = _CameraMediaSessionRecord(
                session_id=session_id,
                capability_digest=capability_digest,
                created_at=created_at,
                expires_at=expires_at,
                state=CameraSessionState.FRAME_CAPTURED_EPHEMERAL,
                frame_facts=normalized.facts,
                media_path=final_path,
                retention_status=CameraRetentionStatus.EPHEMERAL,
                frame_persisted=False,
                deletion_status=CameraDeletionStatus.NOT_APPLICABLE,
                failure_code=None,
                proposal=None,
            )
            self._records[session_id] = record
            self._aggregate_bytes += normalized.facts.encoded_size
            return CameraMediaSessionCreation(
                metadata=record.metadata(),
                session_capability=capability,
            )

    def status(
        self,
        session_id: str,
        capability_values: tuple[str, ...],
    ) -> CameraMediaSessionMetadata:
        now = self._utc_now()
        with self._lock:
            self._require_available_locked()
            record = self._require_authorized_record_locked(session_id, capability_values)
            if now >= record.expires_at:
                self._expire_record_locked(record)
                raise CameraMediaError("session_expired", 410)
            self._cleanup_expired_locked(now, excluded_session_id=session_id)
            return record.metadata()

    def discard(self, session_id: str, capability_values: tuple[str, ...]) -> None:
        now = self._utc_now()
        with self._lock:
            self._require_available_locked()
            record = self._require_authorized_record_locked(session_id, capability_values)
            if now >= record.expires_at:
                self._expire_record_locked(record)
                raise CameraMediaError("session_expired", 410)
            self._cleanup_expired_locked(now, excluded_session_id=session_id)
            try:
                self._delete_registered_file_locked(record)
            except OSError as exc:
                self._records[session_id] = replace(
                    record,
                    deletion_status=CameraDeletionStatus.FAILED,
                    failure_code=CameraFailureCode.DELETION_FAILED,
                )
                raise CameraMediaError("deletion_failed", 500) from exc
            self._remove_record_locked(record)

    def preflight_proposal(self, session_id: str, capability_values: tuple[str, ...]) -> None:
        """Authorize one active parent record before a proposal body is read."""

        now = self._utc_now()
        with self._lock:
            self._require_available_locked()
            record = self._require_authorized_record_locked(session_id, capability_values)
            if now >= record.expires_at:
                self._expire_record_locked(record)
                raise CameraMediaError("session_expired", 410)
            self._cleanup_expired_locked(now, excluded_session_id=session_id)
            if record.proposal is not None:
                raise CameraMediaError("camera_proposal_already_exists", 409)

    def create_proposal(
        self,
        session_id: str,
        capability_values: tuple[str, ...],
        request: CameraCreationProposalRequest,
    ) -> CameraCreationProposal:
        """Attach one inert proposal using only authoritative in-memory record facts."""

        now = self._utc_now()
        with self._lock:
            self._require_available_locked()
            record = self._require_authorized_record_locked(session_id, capability_values)
            if now >= record.expires_at:
                self._expire_record_locked(record)
                raise CameraMediaError("session_expired", 410)
            self._cleanup_expired_locked(now, excluded_session_id=session_id)
            if record.proposal is not None:
                raise CameraMediaError("camera_proposal_already_exists", 409)
            proposal = create_camera_creation_proposal(
                request=request,
                session_id=record.session_id,
                created_at=now,
                expires_at=record.expires_at,
                frame_facts=record.frame_facts,
            )
            self._records[record.session_id] = replace(record, proposal=proposal)
            return proposal

    def close(self) -> CameraMediaShutdownReport:
        """Prevent new operations and best-effort delete all application-owned media."""

        with self._lock:
            if self._closed and self._shutdown_report is not None:
                return self._shutdown_report
            self._closed = True
            attempted = len(self._records)
            deleted = 0
            failed = 0
            for record in tuple(self._records.values()):
                try:
                    self._delete_registered_file_locked(record)
                    deleted += 1
                except OSError:
                    failed += 1
            self._records.clear()
            self._aggregate_bytes = 0
            removed_partial, failed_partial = self._remove_owned_partials_locked()
            self._started = False
            report = CameraMediaShutdownReport(
                attempted_files=attempted,
                deleted_files=deleted,
                failed_files=failed,
                removed_partial_files=removed_partial,
                failed_partial_files=failed_partial,
            )
            self._shutdown_report = report
            return report

    def _initialize_root_locked(self) -> None:
        runtime_temp = self._context.runtime_temp_dir
        if runtime_temp.exists():
            if not runtime_temp.is_dir() or _is_reparse(runtime_temp):
                raise RuntimeError("camera runtime temp root is unsafe")
        else:
            runtime_temp.mkdir(parents=True)
        if self._root.parent != runtime_temp or self._root.resolve(strict=False) != self._root:
            raise RuntimeError("camera media root is unsafe")
        if self._root.exists():
            if not self._root.is_dir() or _is_reparse(self._root):
                raise RuntimeError("camera media root is unsafe")
        else:
            self._root.mkdir()
        for child in tuple(self._root.iterdir()):
            if _OWNED_MEDIA_PATTERN.fullmatch(child.name) is None:
                continue
            if _is_reparse(child) or not child.is_file():
                raise RuntimeError("camera media root contains an unsafe owned entry")
            try:
                child.unlink()
            except OSError as exc:
                raise RuntimeError("camera media startup cleanup failed") from exc

    def _require_available_locked(self) -> None:
        if self._closed or not self._started:
            raise CameraMediaError("camera_invalid_state", 409)

    def _require_authorized_record_locked(
        self,
        session_id: str,
        capability_values: tuple[str, ...],
    ) -> _CameraMediaSessionRecord:
        if _OPAQUE_SECRET_PATTERN.fullmatch(session_id) is None:
            raise CameraMediaError("camera_session_not_found", 404)
        record = self._records.get(session_id)
        if record is None:
            raise CameraMediaError("camera_session_not_found", 404)
        if (
            len(capability_values) != 1
            or _OPAQUE_SECRET_PATTERN.fullmatch(capability_values[0]) is None
        ):
            raise CameraMediaError("camera_session_forbidden", 403)
        digest = hashlib.sha256(capability_values[0].encode("ascii")).digest()
        if not hmac.compare_digest(digest, record.capability_digest):
            raise CameraMediaError("camera_session_forbidden", 403)
        return record

    def _cleanup_expired_locked(
        self,
        now: datetime,
        *,
        excluded_session_id: str | None = None,
    ) -> None:
        expired = tuple(
            record
            for record in self._records.values()
            if record.session_id != excluded_session_id and now >= record.expires_at
        )
        for record in expired:
            try:
                self._expire_record_locked(record)
            except CameraMediaError:
                continue

    def _expire_record_locked(self, record: _CameraMediaSessionRecord) -> None:
        try:
            self._delete_registered_file_locked(record)
        except OSError as exc:
            self._records[record.session_id] = replace(
                record,
                deletion_status=CameraDeletionStatus.FAILED,
                failure_code=CameraFailureCode.DELETION_FAILED,
            )
            raise CameraMediaError("deletion_failed", 500) from exc
        self._remove_record_locked(record)

    def _delete_registered_file_locked(self, record: _CameraMediaSessionRecord) -> None:
        path = self._owned_path(record.media_path.name)
        if path != record.media_path or not path.is_file() or _is_reparse(path):
            raise OSError("registered camera media is unavailable")
        path.unlink()

    def _remove_record_locked(self, record: _CameraMediaSessionRecord) -> None:
        removed = self._records.pop(record.session_id, None)
        if removed is not None:
            self._aggregate_bytes -= removed.frame_facts.encoded_size

    def _remove_owned_partials_locked(self) -> tuple[int, int]:
        if not self._root.is_dir() or _is_reparse(self._root):
            return 0, 0
        removed = 0
        failed = 0
        for child in tuple(self._root.iterdir()):
            if (
                not child.name.endswith(".part")
                or _OWNED_MEDIA_PATTERN.fullmatch(child.name) is None
            ):
                continue
            try:
                if not child.is_file() or _is_reparse(child):
                    raise OSError("unsafe camera partial")
                child.unlink()
                removed += 1
            except OSError:
                failed += 1
        return removed, failed

    def _owned_path(self, filename: str) -> Path:
        if _OWNED_MEDIA_PATTERN.fullmatch(filename) is None:
            raise CameraMediaError("camera_invalid_state", 409)
        candidate = self._root / filename
        if candidate.parent != self._root:
            raise CameraMediaError("camera_invalid_state", 409)
        return candidate

    def _utc_now(self) -> datetime:
        now = self._context.utcnow()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise CameraMediaError("camera_invalid_state", 409)
        return now.astimezone(UTC)


def _generate_secret(generator: object) -> str:
    if not callable(generator):
        raise CameraMediaError("camera_invalid_state", 409)
    raw = generator()
    if type(raw) is not bytes or len(raw) != CAMERA_OPAQUE_SECRET_BYTES:
        raise CameraMediaError("camera_invalid_state", 409)
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if _OPAQUE_SECRET_PATTERN.fullmatch(encoded) is None:
        raise CameraMediaError("camera_invalid_state", 409)
    return encoded


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & _WINDOWS_REPARSE_POINT)


def _best_effort_unlink(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")
