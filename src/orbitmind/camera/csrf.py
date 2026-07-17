"""In-memory CSRF authority for modifying local camera requests."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

CAMERA_PAGE_SESSION_TTL_SECONDS = 900
CAMERA_PAGE_SESSION_MAX_ACTIVE = 16
CAMERA_PAGE_SESSION_COOKIE_NAME = "OrbitMind-Camera-Page"
CAMERA_PAGE_SESSION_COOKIE_PATH = "/workbench/camera"
CAMERA_CSRF_META_NAME = "orbitmind-camera-csrf"
CAMERA_CSRF_REQUEST_HEADER = "X-OrbitMind-Camera-CSRF"
CAMERA_CSRF_NEXT_HEADER = "X-OrbitMind-Camera-CSRF-Next"
CAMERA_CSRF_ERROR_CODE = "camera_request_csrf_invalid"
CAMERA_OPAQUE_SECRET_BYTES = 32

_OPAQUE_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)
_PAGE_BINDING_DOMAIN = b"orbitmind-camera-page-session-v1\x00"
_FORWARDED_HEADER_NAMES = frozenset(
    {
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-port",
        "x-forwarded-proto",
        "x-forwarded-server",
    }
)

UtcClock = Callable[[], datetime]
SecretGenerator = Callable[[], bytes]


class CameraCsrfRoute(StrEnum):
    """Exact modifying routes governed by camera page-session authority."""

    CREATE_SESSION = "/workbench/camera/api/sessions"
    DISCARD_SESSION = "/workbench/camera/api/sessions/{session_id}"
    CREATE_PROPOSAL = "/workbench/camera/api/sessions/{session_id}/proposal"


_ALLOWED_METHODS = {
    CameraCsrfRoute.CREATE_SESSION: "POST",
    CameraCsrfRoute.DISCARD_SESSION: "DELETE",
    CameraCsrfRoute.CREATE_PROPOSAL: "POST",
}


class CameraCsrfRejectedError(Exception):
    """One sanitized failure for every CSRF or protocol rejection."""

    code = CAMERA_CSRF_ERROR_CODE
    status_code = 403

    def __init__(self) -> None:
        super().__init__(CAMERA_CSRF_ERROR_CODE)

    @property
    def detail(self) -> dict[str, str]:
        return {"code": CAMERA_CSRF_ERROR_CODE}


class CameraPageSessionUnavailableError(Exception):
    """Sanitized failure when page-session issuance is unavailable."""

    status_code = 503

    def __init__(self) -> None:
        super().__init__("camera_page_session_unavailable")


@dataclass(frozen=True, slots=True, repr=False)
class IssuedCameraPageSession:
    """Plaintext authority returned once to the camera page response builder."""

    page_session_id: str
    csrf_token: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class CameraCsrfRequestAuthority:
    """Body-free inputs needed to authorize one modifying camera request."""

    method: str
    route: CameraCsrfRoute
    scheme: str
    host_values: tuple[str, ...]
    origin_values: tuple[str, ...]
    sec_fetch_site_values: tuple[str, ...]
    forwarded_header_names: tuple[str, ...]
    page_session_cookie: str | None
    csrf_token_values: tuple[str, ...]
    selected_port: int


@dataclass(frozen=True, slots=True, repr=False)
class CameraCsrfProtocolAuthority:
    """Body-free protocol inputs used before page-session CSRF authority."""

    method: str
    route: CameraCsrfRoute
    scheme: str
    host_values: tuple[str, ...]
    origin_values: tuple[str, ...]
    sec_fetch_site_values: tuple[str, ...]
    forwarded_header_names: tuple[str, ...]
    selected_port: int


@dataclass(frozen=True, slots=True, repr=False)
class _CameraCsrfProtocolPreflight:
    """Registry-bound, non-serializable proof of approved request protocol."""

    _issuer: object
    _method: str
    _route: CameraCsrfRoute
    _expected_host: str
    _integrity: bytes


@dataclass(frozen=True, slots=True, repr=False)
class CameraCsrfRotation:
    """The one plaintext next token returned after atomic acceptance."""

    csrf_token: str
    generation: int


@dataclass(frozen=True, slots=True, repr=False)
class _CameraPageSessionRecord:
    page_binding_digest: bytes
    csrf_token_digest: bytes
    generation: int
    issued_at: datetime
    expires_at: datetime
    active: bool


class CameraPageCsrfRegistry:
    """Bounded application-scoped camera page-session registry."""

    def __init__(
        self,
        *,
        clock: UtcClock,
        page_session_id_generator: SecretGenerator,
        csrf_token_generator: SecretGenerator,
        process_binding_key: bytes,
    ) -> None:
        if type(process_binding_key) is not bytes or (
            len(process_binding_key) != CAMERA_OPAQUE_SECRET_BYTES
        ):
            raise ValueError("camera process binding key must contain exactly 32 bytes")
        self._clock = clock
        self._page_session_id_generator = page_session_id_generator
        self._csrf_token_generator = csrf_token_generator
        self._process_binding_key = bytes(process_binding_key)
        self._protocol_preflight_issuer = object()
        self._records: dict[bytes, _CameraPageSessionRecord] = {}
        self._lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    @property
    def active_session_count(self) -> int:
        now = self._utc_now()
        with self._lock:
            if self._closed:
                return 0
            self._remove_expired(now)
            return len(self._records)

    def issue(self, previous_page_session_id: str | None = None) -> IssuedCameraPageSession:
        """Issue one fresh page-session pair and invalidate a submitted prior pair."""

        now = self._utc_now()
        with self._lock:
            if self._closed:
                raise CameraPageSessionUnavailableError
            self._remove_expired(now)
            if previous_page_session_id is not None and _is_opaque_secret(previous_page_session_id):
                previous_binding = self._page_binding(previous_page_session_id)
                self._records.pop(previous_binding, None)
            if len(self._records) >= CAMERA_PAGE_SESSION_MAX_ACTIVE:
                raise CameraPageSessionUnavailableError

            page_session_id = _generate_opaque_secret(self._page_session_id_generator)
            csrf_token = _generate_opaque_secret(self._csrf_token_generator)
            binding = self._page_binding(page_session_id)
            token_digest = _token_digest(csrf_token)
            if binding in self._records:
                raise CameraPageSessionUnavailableError

            expires_at = now + timedelta(seconds=CAMERA_PAGE_SESSION_TTL_SECONDS)
            self._records[binding] = _CameraPageSessionRecord(
                page_binding_digest=binding,
                csrf_token_digest=token_digest,
                generation=1,
                issued_at=now,
                expires_at=expires_at,
                active=True,
            )
            return IssuedCameraPageSession(
                page_session_id=page_session_id,
                csrf_token=csrf_token,
                issued_at=now,
                expires_at=expires_at,
            )

    def validate_protocol_preflight(
        self, authority: CameraCsrfProtocolAuthority
    ) -> _CameraCsrfProtocolPreflight:
        """Validate non-mutating request protocol and issue a registry-bound proof."""

        if type(authority.selected_port) is not int or not 1024 <= authority.selected_port <= 65535:
            raise CameraCsrfRejectedError
        expected_host = f"127.0.0.1:{authority.selected_port}"
        if (
            authority.scheme != "http"
            or authority.host_values != (expected_host,)
            or any(_is_forwarded_header(name) for name in authority.forwarded_header_names)
        ):
            raise CameraCsrfRejectedError

        expected_origin = f"http://{expected_host}"
        if authority.origin_values != (expected_origin,):
            raise CameraCsrfRejectedError
        if authority.sec_fetch_site_values != ("same-origin",):
            raise CameraCsrfRejectedError
        if _ALLOWED_METHODS.get(authority.route) != authority.method:
            raise CameraCsrfRejectedError

        return _CameraCsrfProtocolPreflight(
            _issuer=self._protocol_preflight_issuer,
            _method=authority.method,
            _route=authority.route,
            _expected_host=expected_host,
            _integrity=self._protocol_preflight_integrity(
                authority.method,
                authority.route,
                expected_host,
            ),
        )

    def validate_and_rotate_after_preflight(
        self,
        preflight: object,
        *,
        expected_route: CameraCsrfRoute,
        page_session_cookie: str | None,
        csrf_token_values: tuple[str, ...],
    ) -> CameraCsrfRotation:
        """Validate page-session CSRF authority after one accepted protocol preflight."""

        if type(preflight) is not _CameraCsrfProtocolPreflight:
            raise CameraCsrfRejectedError
        if preflight._issuer is not self._protocol_preflight_issuer:
            raise CameraCsrfRejectedError
        if (
            type(preflight._method) is not str
            or type(preflight._route) is not CameraCsrfRoute
            or type(preflight._expected_host) is not str
            or type(preflight._integrity) is not bytes
        ):
            raise CameraCsrfRejectedError
        if type(expected_route) is not CameraCsrfRoute or preflight._route is not expected_route:
            raise CameraCsrfRejectedError
        if _ALLOWED_METHODS.get(expected_route) != preflight._method:
            raise CameraCsrfRejectedError
        try:
            expected_integrity = self._protocol_preflight_integrity(
                preflight._method,
                preflight._route,
                preflight._expected_host,
            )
        except UnicodeEncodeError as exc:
            raise CameraCsrfRejectedError from exc
        if not hmac.compare_digest(preflight._integrity, expected_integrity):
            raise CameraCsrfRejectedError

        page_session_id = page_session_cookie
        if page_session_id is None or not _is_opaque_secret(page_session_id):
            raise CameraCsrfRejectedError

        binding = self._page_binding_for_validation(page_session_id)
        with self._lock:
            if self._closed:
                raise CameraCsrfRejectedError
            record = self._records.get(binding)
            if record is None:
                raise CameraCsrfRejectedError

            if len(csrf_token_values) != 1:
                raise CameraCsrfRejectedError
            presented_token = csrf_token_values[0]
            if not _is_opaque_secret(presented_token):
                raise CameraCsrfRejectedError
            presented_digest = _token_digest(presented_token)
            if not hmac.compare_digest(presented_digest, record.csrf_token_digest):
                raise CameraCsrfRejectedError

            now = self._utc_now()
            if now >= record.expires_at:
                self._records.pop(binding, None)
                raise CameraCsrfRejectedError
            if not record.active or record.generation < 1:
                raise CameraCsrfRejectedError

            next_token = _generate_opaque_secret(self._csrf_token_generator)
            next_digest = _token_digest(next_token)
            if hmac.compare_digest(next_digest, record.csrf_token_digest):
                raise CameraCsrfRejectedError
            next_generation = record.generation + 1
            self._records[binding] = replace(
                record,
                csrf_token_digest=next_digest,
                generation=next_generation,
            )
            return CameraCsrfRotation(
                csrf_token=next_token,
                generation=next_generation,
            )

    def validate_and_rotate(self, authority: CameraCsrfRequestAuthority) -> CameraCsrfRotation:
        """Preserve the combined camera modifying-request validation contract."""

        preflight = self.validate_protocol_preflight(
            CameraCsrfProtocolAuthority(
                method=authority.method,
                route=authority.route,
                scheme=authority.scheme,
                host_values=authority.host_values,
                origin_values=authority.origin_values,
                sec_fetch_site_values=authority.sec_fetch_site_values,
                forwarded_header_names=authority.forwarded_header_names,
                selected_port=authority.selected_port,
            )
        )
        return self.validate_and_rotate_after_preflight(
            preflight,
            expected_route=authority.route,
            page_session_cookie=authority.page_session_cookie,
            csrf_token_values=authority.csrf_token_values,
        )

    def close(self) -> None:
        """Idempotently clear all application-scoped camera CSRF authority."""

        with self._lock:
            self._records.clear()
            self._process_binding_key = b""
            self._closed = True

    def _page_binding_for_validation(self, page_session_id: str) -> bytes:
        with self._lock:
            if self._closed:
                raise CameraCsrfRejectedError
            key = self._process_binding_key
        return hmac.digest(key, _PAGE_BINDING_DOMAIN + page_session_id.encode("ascii"), "sha256")

    def _page_binding(self, page_session_id: str) -> bytes:
        return hmac.digest(
            self._process_binding_key,
            _PAGE_BINDING_DOMAIN + page_session_id.encode("ascii"),
            "sha256",
        )

    def _protocol_preflight_integrity(
        self,
        method: str,
        route: CameraCsrfRoute,
        expected_host: str,
    ) -> bytes:
        return hmac.digest(
            self._process_binding_key,
            b"orbitmind-camera-protocol-preflight-v1\x00"
            + method.encode("ascii")
            + b"\x00"
            + route.value.encode("ascii")
            + b"\x00"
            + expected_host.encode("ascii"),
            "sha256",
        )

    def _remove_expired(self, now: datetime) -> None:
        expired = [binding for binding, record in self._records.items() if now >= record.expires_at]
        for binding in expired:
            self._records.pop(binding, None)

    def _utc_now(self) -> datetime:
        now = self._clock()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("camera CSRF clock must return timezone-aware UTC")
        return now.astimezone(UTC)


def _generate_opaque_secret(generator: SecretGenerator) -> str:
    raw = generator()
    if type(raw) is not bytes or len(raw) != CAMERA_OPAQUE_SECRET_BYTES:
        raise CameraPageSessionUnavailableError
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if not _is_opaque_secret(encoded):
        raise CameraPageSessionUnavailableError
    return encoded


def _is_opaque_secret(value: str) -> bool:
    return bool(_OPAQUE_SECRET_PATTERN.fullmatch(value))


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def _is_forwarded_header(name: str) -> bool:
    lowered = name.lower()
    return lowered in _FORWARDED_HEADER_NAMES or lowered.startswith("x-forwarded-")
