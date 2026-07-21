"""Camera compatibility adapter for the shared local page-CSRF registry."""

from __future__ import annotations

import hmac  # noqa: F401 - retained for Camera compatibility test instrumentation.
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import cast

from orbitmind.core.page_csrf import (
    PAGE_CSRF_MAX_ACTIVE_PER_SCOPE,
    PAGE_CSRF_OPAQUE_SECRET_BYTES,
    PAGE_CSRF_TTL_SECONDS,
    PageCsrfPolicy,
    PageCsrfProtocolAuthority,
    PageCsrfRegistry,
    PageCsrfRejectedError,
    PageCsrfScope,
    PageSessionUnavailableError,
    _is_opaque_secret,
)
from orbitmind.core.page_csrf import (
    SecretGenerator as SecretGenerator,
)
from orbitmind.core.page_csrf import (
    UtcClock as UtcClock,
)

CAMERA_PAGE_SESSION_TTL_SECONDS = PAGE_CSRF_TTL_SECONDS
CAMERA_PAGE_SESSION_MAX_ACTIVE = PAGE_CSRF_MAX_ACTIVE_PER_SCOPE
CAMERA_PAGE_SESSION_COOKIE_NAME = "OrbitMind-Camera-Page"
CAMERA_PAGE_SESSION_COOKIE_PATH = "/workbench/camera"
CAMERA_CSRF_META_NAME = "orbitmind-camera-csrf"
CAMERA_CSRF_REQUEST_HEADER = "X-OrbitMind-Camera-CSRF"
CAMERA_CSRF_NEXT_HEADER = "X-OrbitMind-Camera-CSRF-Next"
CAMERA_CSRF_ERROR_CODE = "camera_request_csrf_invalid"
CAMERA_OPAQUE_SECRET_BYTES = PAGE_CSRF_OPAQUE_SECRET_BYTES


class CameraCsrfRoute(StrEnum):
    """Exact modifying routes governed by the Camera page-session scope."""

    CREATE_SESSION = "/workbench/camera/api/sessions"
    DISCARD_SESSION = "/workbench/camera/api/sessions/{session_id}"
    CREATE_PROPOSAL = "/workbench/camera/api/sessions/{session_id}/proposal"


CAMERA_CSRF_POLICY = PageCsrfPolicy(
    scope=PageCsrfScope.CAMERA,
    route_type=CameraCsrfRoute,
    allowed_methods={
        CameraCsrfRoute.CREATE_SESSION: "POST",
        CameraCsrfRoute.DISCARD_SESSION: "DELETE",
        CameraCsrfRoute.CREATE_PROPOSAL: "POST",
    },
    page_binding_domain=b"orbitmind-camera-page-session-v1\x00",
    protocol_preflight_domain=b"orbitmind-camera-protocol-preflight-v1\x00",
)


class CameraCsrfRejectedError(Exception):
    """The stable sanitized Camera failure for a shared-CSRF rejection."""

    code = CAMERA_CSRF_ERROR_CODE
    status_code = 403

    def __init__(self) -> None:
        super().__init__(CAMERA_CSRF_ERROR_CODE)

    @property
    def detail(self) -> dict[str, str]:
        return {"code": CAMERA_CSRF_ERROR_CODE}


class CameraPageSessionUnavailableError(Exception):
    """The stable sanitized Camera failure for unavailable page-session issuance."""

    status_code = 503

    def __init__(self) -> None:
        super().__init__("camera_page_session_unavailable")


@dataclass(frozen=True, slots=True, repr=False)
class IssuedCameraPageSession:
    """Plaintext authority returned once to the Camera page response builder."""

    page_session_id: str
    csrf_token: str
    issued_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class CameraCsrfRequestAuthority:
    """Body-free inputs needed to authorize one modifying Camera request."""

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
    """Body-free protocol inputs used before Camera page-session CSRF authority."""

    method: str
    route: CameraCsrfRoute
    scheme: str
    host_values: tuple[str, ...]
    origin_values: tuple[str, ...]
    sec_fetch_site_values: tuple[str, ...]
    forwarded_header_names: tuple[str, ...]
    selected_port: int


@dataclass(frozen=True, slots=True)
class CameraCsrfRotation:
    """The one plaintext next Camera token returned after atomic acceptance."""

    csrf_token: str
    generation: int


class CameraPageCsrfRegistry:
    """Compatibility adapter over the one shared application page-CSRF registry."""

    def __init__(
        self,
        *,
        clock: UtcClock | None = None,
        page_session_id_generator: SecretGenerator | None = None,
        csrf_token_generator: SecretGenerator | None = None,
        process_binding_key: bytes | None = None,
        shared_registry: PageCsrfRegistry | None = None,
    ) -> None:
        if shared_registry is None:
            if (
                clock is None
                or page_session_id_generator is None
                or csrf_token_generator is None
                or process_binding_key is None
            ):
                raise ValueError("camera CSRF registry requires all local dependencies")
            shared_registry = PageCsrfRegistry(
                clock=clock,
                page_session_id_generator=page_session_id_generator,
                csrf_token_generator=csrf_token_generator,
                process_binding_key=process_binding_key,
                policies=(CAMERA_CSRF_POLICY,),
            )
        self._registry = shared_registry

    @property
    def closed(self) -> bool:
        return self._registry.closed

    @property
    def active_session_count(self) -> int:
        return self._registry.active_session_count(PageCsrfScope.CAMERA)

    @property
    def _records(self) -> dict[bytes, object]:
        return cast(dict[bytes, object], self._registry._records)

    @property
    def _protocol_preflight_issuer(self) -> object:
        return self._registry._protocol_preflight_issuer

    @property
    def _process_binding_key(self) -> bytes:
        return self._registry._process_binding_key

    def issue(self, previous_page_session_id: str | None = None) -> IssuedCameraPageSession:
        try:
            issued = self._registry.issue(PageCsrfScope.CAMERA, previous_page_session_id)
        except PageSessionUnavailableError as exc:
            raise CameraPageSessionUnavailableError from exc
        return IssuedCameraPageSession(
            page_session_id=issued.page_session_id,
            csrf_token=issued.csrf_token,
            issued_at=issued.issued_at,
            expires_at=issued.expires_at,
        )

    def validate_protocol_preflight(self, authority: CameraCsrfProtocolAuthority) -> object:
        try:
            return self._registry.validate_protocol_preflight(
                PageCsrfProtocolAuthority(
                    scope=PageCsrfScope.CAMERA,
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
        except (AttributeError, PageCsrfRejectedError) as exc:
            raise CameraCsrfRejectedError from exc

    def validate_and_rotate_after_preflight(
        self,
        preflight: object,
        *,
        expected_route: CameraCsrfRoute,
        page_session_cookie: str | None,
        csrf_token_values: tuple[str, ...],
    ) -> CameraCsrfRotation:
        # Preserve the Camera contract that an exact-route mismatch fails before
        # it can inspect a submitted page-session value.
        if getattr(preflight, "_route", None) is not expected_route:
            raise CameraCsrfRejectedError
        if page_session_cookie is not None and _is_opaque_secret(page_session_cookie):
            self._page_binding_for_validation(page_session_cookie)
        try:
            rotation = self._registry.validate_and_rotate_after_preflight(
                preflight,
                expected_scope=PageCsrfScope.CAMERA,
                expected_route=expected_route,
                page_session_cookie=page_session_cookie,
                csrf_token_values=csrf_token_values,
            )
        except PageSessionUnavailableError as exc:
            raise CameraPageSessionUnavailableError from exc
        except PageCsrfRejectedError as exc:
            raise CameraCsrfRejectedError from exc
        return CameraCsrfRotation(csrf_token=rotation.csrf_token, generation=rotation.generation)

    def validate_and_rotate(self, authority: CameraCsrfRequestAuthority) -> CameraCsrfRotation:
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
        self._registry.close()

    def _page_binding_for_validation(self, page_session_id: str) -> bytes:
        try:
            return self._registry._page_binding_for_validation(CAMERA_CSRF_POLICY, page_session_id)
        except PageCsrfRejectedError as exc:
            raise CameraCsrfRejectedError from exc

    def _page_binding(self, page_session_id: str) -> bytes:
        return self._registry._page_binding(CAMERA_CSRF_POLICY, page_session_id)
