"""Bounded process-local custom-TLE replay handoff state.

This module is intentionally API-local. It provides request continuity for one
loopback browser process and has no persistence, network, or authentication role.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum

SESSION_COOKIE_NAME = "orbitmind_handoff_session"
SESSION_COOKIE_MAX_AGE_SECONDS = 1_800
HANDOFF_TOKEN_BYTES = 32
HANDOFF_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z", re.ASCII)
SESSION_HMAC_DOMAIN = b"orbitmind-custom-tle-handoff-session-v1\x00"
RECORD_SCHEMA_VERSION = "custom-tle-handoff-record-v1"
MAX_LOGICAL_RECORD_BYTES = 1_024


class HandoffPurpose(StrEnum):
    """The only operation authorized by a transient record."""

    CUSTOM_TLE_TRAJECTORY_REPLAY = "CUSTOM_TLE_TRAJECTORY_REPLAY"


class DiagnosticEventType(StrEnum):
    """Bounded memory-only lifecycle vocabulary."""

    CREATED = "created"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    REJECTED = "rejected"
    CAPACITY_REJECTED = "capacity_rejected"
    OWNER_MISMATCH = "owner_mismatch"
    MALFORMED_IDENTIFIER = "malformed_identifier"


class DiagnosticReason(StrEnum):
    """Fixed reasons that contain no request-derived values."""

    CREATED = "created"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    INVALID_IDENTIFIER = "invalid_identifier"
    UNAVAILABLE = "unavailable"
    OWNER_MISMATCH = "owner_mismatch"
    PURPOSE_MISMATCH = "purpose_mismatch"
    GLOBAL_CAPACITY = "global_capacity"
    SESSION_CAPACITY = "session_capacity"
    RECORD_TOO_LARGE = "record_too_large"
    COLLISION_LIMIT = "collision_limit"


class DiagnosticStatus(StrEnum):
    """Fixed non-authoritative diagnostic outcome."""

    RECORDED = "recorded"
    REJECTED = "rejected"


class HandoffUnavailableError(ValueError):
    """The opaque handoff cannot be consumed; message is intentionally fixed."""

    def __init__(self) -> None:
        super().__init__("temporary replay handoff unavailable")


class HandoffCapacityError(ValueError):
    """Bounded state cannot accept a record; message is intentionally fixed."""

    def __init__(self) -> None:
        super().__init__("temporary replay handoff capacity unavailable")


class HandoffRecordError(ValueError):
    """A record violates its fixed representation boundary."""

    def __init__(self) -> None:
        super().__init__("temporary replay handoff record rejected")


@dataclass(frozen=True)
class TransientHandoffLimits:
    """Immutable U4.3D capacity and lifetime contract."""

    handoff_ttl_seconds: float = 300.0
    session_ttl_seconds: float = 1_800.0
    maximum_records: int = 128
    maximum_records_per_session: int = 4
    maximum_sessions: int = 128
    maximum_logical_record_bytes: int = MAX_LOGICAL_RECORD_BYTES
    maximum_diagnostic_events: int = 256
    collision_retries: int = 3


@dataclass(frozen=True, repr=False)
class TransientHandoffInput:
    """Validated replay inputs awaiting a server-owned session binding."""

    safe_source_label: str
    source_checksum: str
    stable_source_reference: str
    tle_line1: str = field(repr=False)
    tle_line2: str = field(repr=False)
    observer_latitude_deg: float
    observer_longitude_deg: float
    observer_altitude_metres: float
    start_time_utc: datetime
    end_time_utc: datetime
    sample_interval_seconds: int
    maximum_samples: int

    def __repr__(self) -> str:
        return "TransientHandoffInput(<redacted>)"


@dataclass(frozen=True, repr=False)
class TransientCustomTleHandoffRecord:
    """Immutable sensitive record; raw orbital elements never appear in repr."""

    session_binding_digest: bytes = field(repr=False)
    purpose: str
    created_monotonic: float
    expires_monotonic: float
    session_expires_monotonic: float
    safe_source_label: str
    source_checksum: str
    stable_source_reference: str
    tle_line1: str = field(repr=False)
    tle_line2: str = field(repr=False)
    observer_latitude_deg: float
    observer_longitude_deg: float
    observer_altitude_metres: float
    start_time_utc: datetime
    end_time_utc: datetime
    sample_interval_seconds: int
    maximum_samples: int
    schema_version: str = RECORD_SCHEMA_VERSION

    def __repr__(self) -> str:
        return "TransientCustomTleHandoffRecord(<redacted>)"

    def logical_size_bytes(self) -> int:
        """Return the canonical encoded scalar size, never Python heap size."""

        texts = (
            self.purpose,
            self.schema_version,
            self.safe_source_label,
            self.tle_line1,
            self.tle_line2,
            self.source_checksum,
            self.stable_source_reference,
            _canonical_utc(self.start_time_utc),
            _canonical_utc(self.end_time_utc),
        )
        text_size = sum(len(value.encode("utf-8")) + 4 for value in texts)
        fixed_binary_size = 64 + 24 + 24 + 16
        return text_size + fixed_binary_size


@dataclass(frozen=True, repr=False)
class HandoffCreation:
    """One client-visible opaque token plus optional new cookie value."""

    handoff_token: str = field(repr=False)
    session_cookie_value: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return "HandoffCreation(<redacted>)"


@dataclass(frozen=True)
class TransientDiagnosticEvent:
    """Memory-only, non-audit lifecycle event."""

    event_type: DiagnosticEventType
    at: datetime
    purpose: HandoffPurpose
    status: DiagnosticStatus
    reason: DiagnosticReason


@dataclass(frozen=True, repr=False)
class _SessionEntry:
    binding_digest: bytes = field(repr=False)
    created_monotonic: float
    expires_monotonic: float

    def __repr__(self) -> str:
        return "_SessionEntry(<redacted>)"


class CustomTleTransientHandoffStore:
    """Thread-safe bounded state for one process and one local Workbench flow."""

    def __init__(
        self,
        *,
        limits: TransientHandoffLimits | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        utcnow: Callable[[], datetime] | None = None,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
        hmac_key: bytes | None = None,
    ) -> None:
        self._limits = limits or TransientHandoffLimits()
        self._monotonic = monotonic
        self._utcnow = utcnow or (lambda: datetime.now(UTC))
        self._random_bytes = random_bytes
        key = hmac_key if hmac_key is not None else random_bytes(32)
        if len(key) != 32:
            raise ValueError("transient handoff process key must contain 32 bytes")
        self._hmac_key = key
        self._sessions: dict[bytes, _SessionEntry] = {}
        self._records: dict[bytes, TransientCustomTleHandoffRecord] = {}
        self._events: deque[TransientDiagnosticEvent] = deque(
            maxlen=self._limits.maximum_diagnostic_events
        )
        self._lock = threading.Lock()
        self._closed = False

    @property
    def limits(self) -> TransientHandoffLimits:
        return self._limits

    def create(
        self,
        handoff_input: TransientHandoffInput,
        *,
        submitted_cookie: str | None,
    ) -> HandoffCreation:
        """Create one session-bound record atomically or retain no new state."""

        now = self._monotonic()
        event_at = self._utcnow().astimezone(UTC)
        session_candidates = tuple(
            _encode_random(self._random_bytes(HANDOFF_TOKEN_BYTES))
            for _ in range(self._limits.collision_retries)
        )
        token_candidates = tuple(
            _encode_random(self._random_bytes(HANDOFF_TOKEN_BYTES))
            for _ in range(self._limits.collision_retries)
        )
        with self._lock:
            self._require_open()
            self._remove_expired(now, event_at=event_at)
            binding, cookie_value, cookie_is_new = self._resolve_or_create_session(
                submitted_cookie,
                now=now,
                candidates=session_candidates,
                event_at=event_at,
            )
            try:
                return self._create_locked(
                    handoff_input,
                    binding=binding,
                    cookie_value=cookie_value,
                    cookie_is_new=cookie_is_new,
                    now=now,
                    token_candidates=token_candidates,
                    event_at=event_at,
                )
            except Exception:
                self._remove_new_session(binding, cookie_is_new)
                raise

    def _create_locked(
        self,
        handoff_input: TransientHandoffInput,
        *,
        binding: bytes,
        cookie_value: str,
        cookie_is_new: bool,
        now: float,
        token_candidates: tuple[str, ...],
        event_at: datetime,
    ) -> HandoffCreation:
        if len(self._records) >= self._limits.maximum_records:
            self._event(
                DiagnosticEventType.CAPACITY_REJECTED,
                DiagnosticReason.GLOBAL_CAPACITY,
                at=event_at,
            )
            raise HandoffCapacityError
        session_count = sum(
            hmac.compare_digest(record.session_binding_digest, binding)
            for record in self._records.values()
        )
        if session_count >= self._limits.maximum_records_per_session:
            self._event(
                DiagnosticEventType.CAPACITY_REJECTED,
                DiagnosticReason.SESSION_CAPACITY,
                at=event_at,
            )
            raise HandoffCapacityError

        session_entry = self._sessions.get(binding)
        if session_entry is None:
            raise HandoffCapacityError
        record = TransientCustomTleHandoffRecord(
            session_binding_digest=binding,
            purpose=HandoffPurpose.CUSTOM_TLE_TRAJECTORY_REPLAY.value,
            created_monotonic=now,
            expires_monotonic=now + self._limits.handoff_ttl_seconds,
            session_expires_monotonic=session_entry.expires_monotonic,
            safe_source_label=handoff_input.safe_source_label,
            source_checksum=handoff_input.source_checksum,
            stable_source_reference=handoff_input.stable_source_reference,
            tle_line1=handoff_input.tle_line1,
            tle_line2=handoff_input.tle_line2,
            observer_latitude_deg=handoff_input.observer_latitude_deg,
            observer_longitude_deg=handoff_input.observer_longitude_deg,
            observer_altitude_metres=handoff_input.observer_altitude_metres,
            start_time_utc=handoff_input.start_time_utc,
            end_time_utc=handoff_input.end_time_utc,
            sample_interval_seconds=handoff_input.sample_interval_seconds,
            maximum_samples=handoff_input.maximum_samples,
        )
        if record.logical_size_bytes() > self._limits.maximum_logical_record_bytes:
            self._event(
                DiagnosticEventType.REJECTED,
                DiagnosticReason.RECORD_TOO_LARGE,
                at=event_at,
            )
            raise HandoffRecordError
        _validate_record_fields(record)
        token = self._new_unique_token(token_candidates, event_at=event_at)
        token_digest = hashlib.sha256(token.encode("ascii")).digest()
        self._records[token_digest] = record
        self._event(DiagnosticEventType.CREATED, DiagnosticReason.CREATED, at=event_at)
        return HandoffCreation(
            handoff_token=token,
            session_cookie_value=cookie_value if cookie_is_new else None,
        )

    def consume(
        self,
        handoff_token: str,
        *,
        submitted_cookie: str | None,
    ) -> TransientCustomTleHandoffRecord:
        """Atomically validate and remove one record before replay begins."""

        if HANDOFF_TOKEN_PATTERN.fullmatch(handoff_token) is None:
            event_at = self._utcnow().astimezone(UTC)
            with self._lock:
                if not self._closed:
                    self._event(
                        DiagnosticEventType.MALFORMED_IDENTIFIER,
                        DiagnosticReason.INVALID_IDENTIFIER,
                        at=event_at,
                    )
            raise HandoffUnavailableError
        token_digest = hashlib.sha256(handoff_token.encode("ascii")).digest()
        binding = self._binding_for_valid_cookie(submitted_cookie)
        now = self._monotonic()
        event_at = self._utcnow().astimezone(UTC)
        with self._lock:
            self._require_open()
            self._remove_expired(now, event_at=event_at)
            record = self._records.get(token_digest)
            if record is None:
                self._event(
                    DiagnosticEventType.REJECTED,
                    DiagnosticReason.UNAVAILABLE,
                    at=event_at,
                )
                raise HandoffUnavailableError
            if record.purpose != HandoffPurpose.CUSTOM_TLE_TRAJECTORY_REPLAY.value:
                self._event(
                    DiagnosticEventType.REJECTED,
                    DiagnosticReason.PURPOSE_MISMATCH,
                    at=event_at,
                )
                raise HandoffUnavailableError
            if record.expires_monotonic <= now or record.session_expires_monotonic <= now:
                self._records.pop(token_digest, None)
                self._event(DiagnosticEventType.EXPIRED, DiagnosticReason.EXPIRED, at=event_at)
                raise HandoffUnavailableError
            session = self._sessions.get(binding) if binding is not None else None
            if (
                binding is None
                or session is None
                or session.expires_monotonic <= now
                or not hmac.compare_digest(record.session_binding_digest, binding)
            ):
                self._event(
                    DiagnosticEventType.OWNER_MISMATCH,
                    DiagnosticReason.OWNER_MISMATCH,
                    at=event_at,
                )
                raise HandoffUnavailableError
            consumed = self._records.pop(token_digest)
            self._event(DiagnosticEventType.CONSUMED, DiagnosticReason.CONSUMED, at=event_at)
            return consumed

    def clear(self) -> None:
        """Discard all process-local state at application shutdown."""

        with self._lock:
            self._records.clear()
            self._sessions.clear()
            self._events.clear()
            self._hmac_key = b""
            self._closed = True

    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    def diagnostic_events(self) -> tuple[TransientDiagnosticEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def _resolve_or_create_session(
        self,
        submitted_cookie: str | None,
        *,
        now: float,
        candidates: tuple[str, ...],
        event_at: datetime,
    ) -> tuple[bytes, str, bool]:
        binding = self._binding_for_valid_cookie(submitted_cookie)
        if binding is not None:
            existing = self._sessions.get(binding)
            if existing is not None and existing.expires_monotonic > now:
                return binding, submitted_cookie or "", False

        if len(self._sessions) >= self._limits.maximum_sessions:
            self._event(
                DiagnosticEventType.CAPACITY_REJECTED,
                DiagnosticReason.SESSION_CAPACITY,
                at=event_at,
            )
            raise HandoffCapacityError
        for cookie_value in candidates:
            if HANDOFF_TOKEN_PATTERN.fullmatch(cookie_value) is None:
                continue
            new_binding = self._session_binding(cookie_value)
            if new_binding not in self._sessions:
                self._sessions[new_binding] = _SessionEntry(
                    binding_digest=new_binding,
                    created_monotonic=now,
                    expires_monotonic=now + self._limits.session_ttl_seconds,
                )
                return new_binding, cookie_value, True
        self._event(DiagnosticEventType.REJECTED, DiagnosticReason.COLLISION_LIMIT, at=event_at)
        raise HandoffCapacityError

    def _new_unique_token(
        self,
        candidates: tuple[str, ...],
        *,
        event_at: datetime,
    ) -> str:
        for token in candidates:
            if HANDOFF_TOKEN_PATTERN.fullmatch(token) is None:
                continue
            digest = hashlib.sha256(token.encode("ascii")).digest()
            if digest not in self._records:
                return token
        self._event(DiagnosticEventType.REJECTED, DiagnosticReason.COLLISION_LIMIT, at=event_at)
        raise HandoffCapacityError

    def _binding_for_valid_cookie(self, cookie_value: str | None) -> bytes | None:
        if cookie_value is None or HANDOFF_TOKEN_PATTERN.fullmatch(cookie_value) is None:
            return None
        return self._session_binding(cookie_value)

    def _session_binding(self, cookie_value: str) -> bytes:
        return hmac.new(
            self._hmac_key,
            SESSION_HMAC_DOMAIN + cookie_value.encode("ascii"),
            hashlib.sha256,
        ).digest()

    def _remove_expired(self, now: float, *, event_at: datetime) -> None:
        expired_records = [
            digest
            for digest, record in self._records.items()
            if record.expires_monotonic <= now or record.session_expires_monotonic <= now
        ]
        for digest in expired_records:
            self._records.pop(digest, None)
            self._event(DiagnosticEventType.EXPIRED, DiagnosticReason.EXPIRED, at=event_at)
        expired_sessions = [
            digest for digest, session in self._sessions.items() if session.expires_monotonic <= now
        ]
        for digest in expired_sessions:
            self._sessions.pop(digest, None)

    def _event(
        self,
        event_type: DiagnosticEventType,
        reason: DiagnosticReason,
        *,
        at: datetime,
    ) -> None:
        self._events.append(
            TransientDiagnosticEvent(
                event_type=event_type,
                at=at,
                purpose=HandoffPurpose.CUSTOM_TLE_TRAJECTORY_REPLAY,
                status=(
                    DiagnosticStatus.RECORDED
                    if event_type
                    in {
                        DiagnosticEventType.CREATED,
                        DiagnosticEventType.CONSUMED,
                        DiagnosticEventType.EXPIRED,
                    }
                    else DiagnosticStatus.REJECTED
                ),
                reason=reason,
            )
        )

    def _remove_new_session(self, binding: bytes, cookie_is_new: bool) -> None:
        if cookie_is_new:
            self._sessions.pop(binding, None)

    def _require_open(self) -> None:
        if self._closed:
            raise HandoffUnavailableError


def _encode_random(value: bytes) -> str:
    if len(value) != HANDOFF_TOKEN_BYTES:
        return ""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _canonical_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_record_fields(record: TransientCustomTleHandoffRecord) -> None:
    text_limits = (
        (record.purpose, 32, False),
        (record.schema_version, 32, False),
        (record.safe_source_label, 80, True),
        (record.tle_line1, 100, True),
        (record.tle_line2, 100, True),
        (record.source_checksum, 64, True),
        (record.stable_source_reference, 80, True),
        (_canonical_utc(record.start_time_utc), 35, True),
        (_canonical_utc(record.end_time_utc), 35, True),
    )
    if any(
        len(value.encode("utf-8")) > limit or (ascii_only and not value.isascii()) or not value
        for value, limit, ascii_only in text_limits
    ):
        raise HandoffRecordError
    if record.purpose != HandoffPurpose.CUSTOM_TLE_TRAJECTORY_REPLAY.value:
        raise HandoffRecordError
    if re.fullmatch(r"[0-9a-f]{64}", record.source_checksum, flags=re.ASCII) is None:
        raise HandoffRecordError
    if (
        record.start_time_utc.tzinfo is None
        or record.start_time_utc.utcoffset() is None
        or record.end_time_utc.tzinfo is None
        or record.end_time_utc.utcoffset() is None
        or record.end_time_utc <= record.start_time_utc
    ):
        raise HandoffRecordError
    if not all(
        math.isfinite(value)
        for value in (
            record.created_monotonic,
            record.expires_monotonic,
            record.session_expires_monotonic,
            record.observer_latitude_deg,
            record.observer_longitude_deg,
            record.observer_altitude_metres,
        )
    ):
        raise HandoffRecordError
    if record.sample_interval_seconds <= 0 or record.maximum_samples <= 0:
        raise HandoffRecordError
