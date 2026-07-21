"""Shared in-memory CSRF authority for local, server-rendered pages.

The registry is intentionally process-local.  It provides one reviewed
cryptographic implementation for multiple fixed local Workbench surfaces; it
does not authenticate a remote user or persist a browser session.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum

PAGE_CSRF_TTL_SECONDS = 900
PAGE_CSRF_MAX_ACTIVE_PER_SCOPE = 16
PAGE_CSRF_OPAQUE_SECRET_BYTES = 32
AUTHORITY_WORKBENCH_CSRF_FORM_FIELD = "authority_csrf_token"
AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_NAME = "OrbitMind-Authority-Page"
AUTHORITY_WORKBENCH_PAGE_SESSION_COOKIE_PATH = "/authority/workbench"

_OPAQUE_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)
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


class PageCsrfScope(StrEnum):
    """Fixed page surfaces isolated within one application-scoped registry."""

    CAMERA = "camera"
    AUTHORITY_WORKBENCH = "authority-workbench"


class AuthorityWorkbenchCsrfRoute(StrEnum):
    """Fixed Authority Workbench mutation routes governed by the shared registry."""

    CREATE_REQUEST = "/authority/workbench/requests"
    RECORD_DECISION = "/authority/workbench/requests/{request_id}/decide"
    ISSUE_GRANT = "/authority/workbench/requests/{request_id}/issue-grant"
    REVOKE_GRANT = "/authority/workbench/grants/{grant_id}/revoke"
    EVALUATE_GRANT = "/authority/workbench/grants/{grant_id}/evaluate"


@dataclass(frozen=True, slots=True)
class PageCsrfPolicy:
    """Fixed route and domain policy for one protected page scope."""

    scope: PageCsrfScope
    route_type: type[StrEnum]
    allowed_methods: Mapping[StrEnum, str]
    page_binding_domain: bytes
    protocol_preflight_domain: bytes


AUTHORITY_WORKBENCH_CSRF_POLICY = PageCsrfPolicy(
    scope=PageCsrfScope.AUTHORITY_WORKBENCH,
    route_type=AuthorityWorkbenchCsrfRoute,
    allowed_methods={
        AuthorityWorkbenchCsrfRoute.CREATE_REQUEST: "POST",
        AuthorityWorkbenchCsrfRoute.RECORD_DECISION: "POST",
        AuthorityWorkbenchCsrfRoute.ISSUE_GRANT: "POST",
        AuthorityWorkbenchCsrfRoute.REVOKE_GRANT: "POST",
        AuthorityWorkbenchCsrfRoute.EVALUATE_GRANT: "POST",
    },
    page_binding_domain=b"orbitmind-authority-workbench-page-session-v1\x00",
    protocol_preflight_domain=b"orbitmind-authority-workbench-protocol-preflight-v1\x00",
)


class PageCsrfRejectedError(Exception):
    """One sanitized failure for every shared CSRF or protocol rejection."""

    def __init__(self) -> None:
        super().__init__("page_request_csrf_invalid")


class PageSessionUnavailableError(Exception):
    """Sanitized failure when page-session issuance is unavailable."""

    def __init__(self) -> None:
        super().__init__("page_session_unavailable")


@dataclass(frozen=True, slots=True, repr=False)
class IssuedPageSession:
    """Plaintext authority returned once to a protected page response builder."""

    page_session_id: str
    csrf_token: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class PageCsrfRequestAuthority:
    """Body-free inputs needed to authorize one modifying page request."""

    scope: PageCsrfScope
    method: str
    route: StrEnum
    scheme: str
    host_values: tuple[str, ...]
    origin_values: tuple[str, ...]
    sec_fetch_site_values: tuple[str, ...]
    forwarded_header_names: tuple[str, ...]
    page_session_cookie: str | None
    csrf_token_values: tuple[str, ...]
    selected_port: int


@dataclass(frozen=True, slots=True, repr=False)
class PageCsrfProtocolAuthority:
    """Body-free protocol inputs used before page-session CSRF authority."""

    scope: PageCsrfScope
    method: str
    route: StrEnum
    scheme: str
    host_values: tuple[str, ...]
    origin_values: tuple[str, ...]
    sec_fetch_site_values: tuple[str, ...]
    forwarded_header_names: tuple[str, ...]
    selected_port: int


@dataclass(frozen=True, slots=True, repr=False)
class _PageCsrfProtocolPreflight:
    """Registry-bound, non-serializable proof of approved request protocol."""

    _issuer: object
    _scope: PageCsrfScope
    _method: str
    _route: StrEnum
    _expected_host: str
    _integrity: bytes


@dataclass(frozen=True, slots=True)
class PageCsrfRotation:
    """The one plaintext next token returned after atomic acceptance."""

    csrf_token: str
    generation: int


@dataclass(frozen=True, slots=True, repr=False)
class _PageSessionRecord:
    scope: PageCsrfScope
    page_binding_digest: bytes
    csrf_token_digest: bytes
    generation: int
    issued_at: datetime
    expires_at: datetime
    active: bool


class PageCsrfRegistry:
    """One bounded registry shared by fixed local page-CSRF scopes."""

    def __init__(
        self,
        *,
        clock: UtcClock,
        page_session_id_generator: SecretGenerator,
        csrf_token_generator: SecretGenerator,
        process_binding_key: bytes,
        policies: tuple[PageCsrfPolicy, ...],
    ) -> None:
        if type(process_binding_key) is not bytes or (
            len(process_binding_key) != PAGE_CSRF_OPAQUE_SECRET_BYTES
        ):
            raise ValueError("page CSRF process binding key must contain exactly 32 bytes")
        if not policies:
            raise ValueError("page CSRF registry requires at least one fixed policy")
        self._policies = _validated_policies(policies)
        self._clock = clock
        self._page_session_id_generator = page_session_id_generator
        self._csrf_token_generator = csrf_token_generator
        self._process_binding_key = bytes(process_binding_key)
        self._protocol_preflight_issuer = object()
        self._records: dict[bytes, _PageSessionRecord] = {}
        self._lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def active_session_count(self, scope: PageCsrfScope) -> int:
        now = self._utc_now()
        with self._lock:
            if self._closed:
                return 0
            self._remove_expired(now)
            return sum(record.scope is scope for record in self._records.values())

    def issue(
        self, scope: PageCsrfScope, previous_page_session_id: str | None = None
    ) -> IssuedPageSession:
        """Issue a fresh scoped pair and invalidate a submitted pair in that scope."""

        policy = self._policy_for_issue(scope)
        now = self._utc_now()
        with self._lock:
            if self._closed:
                raise PageSessionUnavailableError
            self._remove_expired(now)
            if previous_page_session_id is not None and _is_opaque_secret(previous_page_session_id):
                self._records.pop(self._page_binding(policy, previous_page_session_id), None)
            if (
                sum(record.scope is scope for record in self._records.values())
                >= PAGE_CSRF_MAX_ACTIVE_PER_SCOPE
            ):
                raise PageSessionUnavailableError

            page_session_id = _generate_opaque_secret(self._page_session_id_generator)
            csrf_token = _generate_opaque_secret(self._csrf_token_generator)
            binding = self._page_binding(policy, page_session_id)
            if binding in self._records:
                raise PageSessionUnavailableError
            expires_at = now + timedelta(seconds=PAGE_CSRF_TTL_SECONDS)
            self._records[binding] = _PageSessionRecord(
                scope=scope,
                page_binding_digest=binding,
                csrf_token_digest=_token_digest(csrf_token),
                generation=1,
                issued_at=now,
                expires_at=expires_at,
                active=True,
            )
            return IssuedPageSession(page_session_id, csrf_token, now, expires_at)

    def validate_protocol_preflight(
        self, authority: PageCsrfProtocolAuthority
    ) -> _PageCsrfProtocolPreflight:
        """Validate protocol inputs before parsing a protected request body."""

        if type(authority) is not PageCsrfProtocolAuthority:
            raise PageCsrfRejectedError
        policy = self._policy_for_protocol(authority.scope, authority.route)
        if type(authority.selected_port) is not int or not 1024 <= authority.selected_port <= 65535:
            raise PageCsrfRejectedError
        expected_host = f"127.0.0.1:{authority.selected_port}"
        if (
            authority.scheme != "http"
            or authority.host_values != (expected_host,)
            or any(_is_forwarded_header(name) for name in authority.forwarded_header_names)
        ):
            raise PageCsrfRejectedError
        if authority.origin_values != (f"http://{expected_host}",):
            raise PageCsrfRejectedError
        if authority.sec_fetch_site_values != ("same-origin",):
            raise PageCsrfRejectedError
        if policy.allowed_methods.get(authority.route) != authority.method:
            raise PageCsrfRejectedError
        return _PageCsrfProtocolPreflight(
            _issuer=self._protocol_preflight_issuer,
            _scope=authority.scope,
            _method=authority.method,
            _route=authority.route,
            _expected_host=expected_host,
            _integrity=self._protocol_preflight_integrity(
                policy, authority.method, authority.route, expected_host
            ),
        )

    def validate_and_rotate_after_preflight(
        self,
        preflight: object,
        *,
        expected_scope: PageCsrfScope,
        expected_route: StrEnum,
        page_session_cookie: str | None,
        csrf_token_values: tuple[str, ...],
    ) -> PageCsrfRotation:
        """Validate one scoped page-session token after an accepted preflight."""

        if type(preflight) is not _PageCsrfProtocolPreflight:
            raise PageCsrfRejectedError
        if preflight._issuer is not self._protocol_preflight_issuer:
            raise PageCsrfRejectedError
        if (
            type(preflight._scope) is not PageCsrfScope
            or type(preflight._method) is not str
            or type(preflight._expected_host) is not str
            or type(preflight._integrity) is not bytes
            or preflight._scope is not expected_scope
        ):
            raise PageCsrfRejectedError
        policy = self._policy_for_protocol(expected_scope, expected_route)
        if (
            type(preflight._route) is not policy.route_type
            or preflight._route is not expected_route
        ):
            raise PageCsrfRejectedError
        if policy.allowed_methods.get(expected_route) != preflight._method:
            raise PageCsrfRejectedError
        try:
            expected_integrity = self._protocol_preflight_integrity(
                policy, preflight._method, expected_route, preflight._expected_host
            )
        except UnicodeEncodeError as exc:
            raise PageCsrfRejectedError from exc
        if not hmac.compare_digest(preflight._integrity, expected_integrity):
            raise PageCsrfRejectedError
        if page_session_cookie is None or not _is_opaque_secret(page_session_cookie):
            raise PageCsrfRejectedError

        binding = self._page_binding_for_validation(policy, page_session_cookie)
        with self._lock:
            if self._closed:
                raise PageCsrfRejectedError
            record = self._records.get(binding)
            if record is None or record.scope is not expected_scope:
                raise PageCsrfRejectedError
            if len(csrf_token_values) != 1 or not _is_opaque_secret(csrf_token_values[0]):
                raise PageCsrfRejectedError
            presented_digest = _token_digest(csrf_token_values[0])
            if not hmac.compare_digest(presented_digest, record.csrf_token_digest):
                raise PageCsrfRejectedError
            now = self._utc_now()
            if now >= record.expires_at:
                self._records.pop(binding, None)
                raise PageCsrfRejectedError
            if not record.active or record.generation < 1:
                raise PageCsrfRejectedError
            next_token = _generate_opaque_secret(self._csrf_token_generator)
            next_digest = _token_digest(next_token)
            if hmac.compare_digest(next_digest, record.csrf_token_digest):
                raise PageCsrfRejectedError
            next_generation = record.generation + 1
            self._records[binding] = replace(
                record, csrf_token_digest=next_digest, generation=next_generation
            )
            return PageCsrfRotation(csrf_token=next_token, generation=next_generation)

    def validate_and_rotate(self, authority: PageCsrfRequestAuthority) -> PageCsrfRotation:
        """Preserve the combined validation convenience for compatible callers."""

        preflight = self.validate_protocol_preflight(
            PageCsrfProtocolAuthority(
                scope=authority.scope,
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
            expected_scope=authority.scope,
            expected_route=authority.route,
            page_session_cookie=authority.page_session_cookie,
            csrf_token_values=authority.csrf_token_values,
        )

    def close(self) -> None:
        """Idempotently clear all process-local page CSRF authority."""

        with self._lock:
            self._records.clear()
            self._process_binding_key = b""
            self._closed = True

    def _policy_for_issue(self, scope: PageCsrfScope) -> PageCsrfPolicy:
        if type(scope) is not PageCsrfScope or scope not in self._policies:
            raise PageSessionUnavailableError
        return self._policies[scope]

    def _policy_for_protocol(self, scope: object, route: object) -> PageCsrfPolicy:
        if type(scope) is not PageCsrfScope:
            raise PageCsrfRejectedError
        policy = self._policies.get(scope)
        if (
            policy is None
            or type(route) is not policy.route_type
            or route not in policy.allowed_methods
        ):
            raise PageCsrfRejectedError
        return policy

    def _page_binding_for_validation(self, policy: PageCsrfPolicy, page_session_id: str) -> bytes:
        with self._lock:
            if self._closed:
                raise PageCsrfRejectedError
            key = self._process_binding_key
        return hmac.digest(
            key, policy.page_binding_domain + page_session_id.encode("ascii"), "sha256"
        )

    def _page_binding(self, policy: PageCsrfPolicy, page_session_id: str) -> bytes:
        return hmac.digest(
            self._process_binding_key,
            policy.page_binding_domain + page_session_id.encode("ascii"),
            "sha256",
        )

    def _protocol_preflight_integrity(
        self, policy: PageCsrfPolicy, method: str, route: StrEnum, expected_host: str
    ) -> bytes:
        return hmac.digest(
            self._process_binding_key,
            policy.protocol_preflight_domain
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
            raise ValueError("page CSRF clock must return timezone-aware UTC")
        return now.astimezone(UTC)


def _validated_policies(
    policies: tuple[PageCsrfPolicy, ...],
) -> dict[PageCsrfScope, PageCsrfPolicy]:
    result: dict[PageCsrfScope, PageCsrfPolicy] = {}
    for policy in policies:
        if (
            type(policy) is not PageCsrfPolicy
            or type(policy.scope) is not PageCsrfScope
            or not isinstance(policy.route_type, type)
            or not issubclass(policy.route_type, StrEnum)
            or not policy.allowed_methods
            or type(policy.page_binding_domain) is not bytes
            or type(policy.protocol_preflight_domain) is not bytes
            or policy.scope in result
        ):
            raise ValueError("page CSRF policy is invalid")
        if any(
            type(route) is not policy.route_type or method not in {"POST", "DELETE"}
            for route, method in policy.allowed_methods.items()
        ):
            raise ValueError("page CSRF policy routes are invalid")
        result[policy.scope] = policy
    return result


def _generate_opaque_secret(generator: SecretGenerator) -> str:
    raw = generator()
    if type(raw) is not bytes or len(raw) != PAGE_CSRF_OPAQUE_SECRET_BYTES:
        raise PageSessionUnavailableError
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    if not _is_opaque_secret(encoded):
        raise PageSessionUnavailableError
    return encoded


def _is_opaque_secret(value: str) -> bool:
    return bool(_OPAQUE_SECRET_PATTERN.fullmatch(value))


def _token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def _is_forwarded_header(name: str) -> bool:
    lowered = name.lower()
    return lowered in _FORWARDED_HEADER_NAMES or lowered.startswith("x-forwarded-")
