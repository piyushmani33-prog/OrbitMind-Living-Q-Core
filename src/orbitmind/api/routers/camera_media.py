"""Capability-scoped API for one bounded ephemeral camera frame."""

from __future__ import annotations

import json
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container
from orbitmind.camera.contracts import CAMERA_MAX_ENCODED_BYTES, CameraMediaType
from orbitmind.camera.csrf import (
    CAMERA_CSRF_NEXT_HEADER,
    CAMERA_CSRF_REQUEST_HEADER,
    CAMERA_PAGE_SESSION_COOKIE_NAME,
    CameraCsrfProtocolAuthority,
    CameraCsrfRejectedError,
    CameraCsrfRequestAuthority,
    CameraCsrfRotation,
    CameraCsrfRoute,
)
from orbitmind.camera.media import CameraMediaError
from orbitmind.camera.proposal import (
    CameraCreationProposalRequest,
    CameraProposalValidationError,
)
from orbitmind.camera.service import (
    CAMERA_MEDIA_CAPABILITY_HEADER,
    CameraMediaSessionCreation,
)

router = APIRouter(tags=["camera-media"])

ContainerDep = Annotated[AppContainer, Depends(get_container)]

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}
CAMERA_PROPOSAL_MAX_BODY_BYTES = 4096


@router.post("/workbench/camera/api/sessions")
async def create_camera_media_session(request: Request, container: ContainerDep) -> JSONResponse:
    declared_length_error = _declared_length_error(request)
    if declared_length_error is not None:
        return declared_length_error

    rotation = _validate_and_rotate(request, container, CameraCsrfRoute.CREATE_SESSION)
    if isinstance(rotation, JSONResponse):
        return rotation
    headers = _rotated_headers(rotation)
    try:
        media_type = _declared_media_type(request)
        content = await _read_bounded_body(request)
        created = container.require_camera_media_service().create(content, media_type)
    except CameraMediaError as exc:
        return _error_response(exc.code, exc.status_code, headers=headers)
    except Exception:
        return _error_response("temporary_storage_failed", 503, headers=headers)
    return JSONResponse(
        status_code=201,
        content=_creation_response(created),
        headers=headers,
    )


@router.get("/workbench/camera/api/sessions/{session_id}")
def get_camera_media_session(
    session_id: str,
    request: Request,
    container: ContainerDep,
) -> JSONResponse:
    try:
        metadata = container.require_camera_media_service().status(
            session_id,
            _header_values(request, CAMERA_MEDIA_CAPABILITY_HEADER),
        )
    except CameraMediaError as exc:
        return _error_response(exc.code, exc.status_code)
    return JSONResponse(content=metadata.to_response(), headers=dict(_NO_STORE_HEADERS))


@router.post("/workbench/camera/api/sessions/{session_id}/proposal")
async def create_camera_creation_proposal(
    session_id: str,
    request: Request,
    container: ContainerDep,
) -> JSONResponse:
    """Create one inert proposal attached to an authorized temporary media session."""

    registry = container.require_camera_page_csrf_registry()
    try:
        preflight = registry.validate_protocol_preflight(
            _protocol_authority(request, container, CameraCsrfRoute.CREATE_PROPOSAL)
        )
    except CameraCsrfRejectedError as exc:
        return _error_response(exc.code, exc.status_code)

    declared_length_error = _proposal_declared_length_error(request)
    if declared_length_error is not None:
        return declared_length_error

    try:
        rotation = registry.validate_and_rotate_after_preflight(
            preflight,
            expected_route=CameraCsrfRoute.CREATE_PROPOSAL,
            page_session_cookie=request.cookies.get(CAMERA_PAGE_SESSION_COOKIE_NAME),
            csrf_token_values=_header_values(request, CAMERA_CSRF_REQUEST_HEADER),
        )
    except CameraCsrfRejectedError as exc:
        return _error_response(exc.code, exc.status_code)
    headers = _rotated_headers(rotation)
    service = container.require_camera_media_service()
    capability_values = _header_values(request, CAMERA_MEDIA_CAPABILITY_HEADER)
    try:
        service.preflight_proposal(session_id, capability_values)
    except CameraMediaError as exc:
        return _error_response(exc.code, exc.status_code, headers=headers)

    try:
        proposal_request = await _read_proposal_request(request)
    except CameraProposalValidationError as exc:
        return _error_response(exc.code, 400, headers=headers)

    try:
        proposal = service.create_proposal(session_id, capability_values, proposal_request)
    except CameraMediaError as exc:
        return _error_response(exc.code, exc.status_code, headers=headers)
    return JSONResponse(status_code=201, content=proposal.to_response(), headers=headers)


@router.delete("/workbench/camera/api/sessions/{session_id}")
def discard_camera_media_session(
    session_id: str,
    request: Request,
    container: ContainerDep,
) -> Response:
    declared_length_error = _declared_length_error(request)
    if declared_length_error is not None:
        return declared_length_error

    rotation = _validate_and_rotate(request, container, CameraCsrfRoute.DISCARD_SESSION)
    if isinstance(rotation, JSONResponse):
        return rotation
    headers = _rotated_headers(rotation)
    try:
        container.require_camera_media_service().discard(
            session_id,
            _header_values(request, CAMERA_MEDIA_CAPABILITY_HEADER),
        )
    except CameraMediaError as exc:
        return _error_response(exc.code, exc.status_code, headers=headers)
    except Exception:
        return _error_response("deletion_failed", 500, headers=headers)
    return Response(status_code=204, headers=headers)


def _validate_and_rotate(
    request: Request,
    container: AppContainer,
    route: CameraCsrfRoute,
) -> CameraCsrfRotation | JSONResponse:
    protocol = _protocol_authority(request, container, route)
    authority = CameraCsrfRequestAuthority(
        method=protocol.method,
        route=protocol.route,
        scheme=protocol.scheme,
        host_values=protocol.host_values,
        origin_values=protocol.origin_values,
        sec_fetch_site_values=protocol.sec_fetch_site_values,
        forwarded_header_names=protocol.forwarded_header_names,
        page_session_cookie=request.cookies.get(CAMERA_PAGE_SESSION_COOKIE_NAME),
        csrf_token_values=_header_values(request, CAMERA_CSRF_REQUEST_HEADER),
        selected_port=protocol.selected_port,
    )
    try:
        return container.require_camera_page_csrf_registry().validate_and_rotate(authority)
    except CameraCsrfRejectedError as exc:
        return _error_response(exc.code, exc.status_code)


def _protocol_authority(
    request: Request,
    container: AppContainer,
    route: CameraCsrfRoute,
) -> CameraCsrfProtocolAuthority:
    return CameraCsrfProtocolAuthority(
        method=request.method,
        route=route,
        scheme=request.url.scheme,
        host_values=_header_values(request, "Host"),
        origin_values=_header_values(request, "Origin"),
        sec_fetch_site_values=_header_values(request, "Sec-Fetch-Site"),
        forwarded_header_names=_forwarded_header_names(request),
        selected_port=container.settings.custom_tle_handoff_port,
    )


def _declared_length_error(request: Request) -> JSONResponse | None:
    values = _header_values(request, "Content-Length")
    if not values:
        return None
    if len(values) != 1 or not values[0].isascii() or not values[0].isdecimal():
        return _error_response("camera_invalid_state", 400)
    if int(values[0], 10) > CAMERA_MAX_ENCODED_BYTES:
        return _error_response("image_too_large", 413)
    return None


def _proposal_declared_length_error(request: Request) -> JSONResponse | None:
    values = _header_values(request, "Content-Length")
    if not values:
        return None
    if len(values) != 1 or not values[0].isascii() or not values[0].isdecimal():
        return _error_response("camera_proposal_request_invalid", 400)
    if int(values[0], 10) > CAMERA_PROPOSAL_MAX_BODY_BYTES:
        return _error_response("camera_proposal_request_invalid", 413)
    return None


def _declared_media_type(request: Request) -> CameraMediaType:
    values = _header_values(request, "Content-Type")
    if len(values) != 1:
        raise CameraMediaError("image_type_invalid", 415)
    try:
        return CameraMediaType(values[0])
    except ValueError as exc:
        raise CameraMediaError("image_type_invalid", 415) from exc


async def _read_bounded_body(request: Request) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > CAMERA_MAX_ENCODED_BYTES:
            raise CameraMediaError("image_too_large", 413)
        content.extend(chunk)
    if not content:
        raise CameraMediaError("image_decode_failed", 400)
    return bytes(content)


async def _read_proposal_request(request: Request) -> CameraCreationProposalRequest:
    if _header_values(request, "Content-Type") != ("application/json",):
        raise CameraProposalValidationError("camera_proposal_request_invalid")

    content = bytearray()
    try:
        async for chunk in request.stream():
            if len(content) + len(chunk) > CAMERA_PROPOSAL_MAX_BODY_BYTES:
                raise CameraProposalValidationError("camera_proposal_request_invalid")
            content.extend(chunk)
        decoded = bytes(content).decode("utf-8")
        payload = json.loads(
            decoded,
            object_pairs_hook=_json_object_without_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, CameraProposalValidationError):
            raise
        raise CameraProposalValidationError("camera_proposal_request_invalid") from exc
    return CameraCreationProposalRequest.from_json_object(payload)


def _json_object_without_duplicate_keys(pairs: list[tuple[object, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if type(key) is not str or key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"unsupported JSON constant: {value}")


def _header_values(request: Request, name: str) -> tuple[str, ...]:
    expected = name.casefold().encode("ascii")
    headers = cast(list[tuple[bytes, bytes]], request.scope.get("headers", []))
    return tuple(value.decode("latin-1") for key, value in headers if key.lower() == expected)


def _forwarded_header_names(request: Request) -> tuple[str, ...]:
    headers = cast(list[tuple[bytes, bytes]], request.scope.get("headers", []))
    return tuple(
        key.decode("latin-1")
        for key, _value in headers
        if key.lower() == b"forwarded" or key.lower().startswith(b"x-forwarded-")
    )


def _rotated_headers(rotation: CameraCsrfRotation) -> dict[str, str]:
    return {**_NO_STORE_HEADERS, CAMERA_CSRF_NEXT_HEADER: rotation.csrf_token}


def _creation_response(created: CameraMediaSessionCreation) -> dict[str, object]:
    response = created.metadata.to_response()
    response["session_capability"] = created.session_capability
    return response


def _error_response(
    code: str,
    status_code: int,
    *,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": {"code": code}},
        headers=dict(_NO_STORE_HEADERS if headers is None else headers),
    )
