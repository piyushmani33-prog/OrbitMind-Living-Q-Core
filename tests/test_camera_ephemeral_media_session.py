"""Security and lifecycle tests for bounded ephemeral camera media."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from starlette.requests import Request

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.routers import camera_media as camera_media_router
from orbitmind.api.routers.camera_media import _declared_length_error, _read_bounded_body
from orbitmind.camera import media as camera_media
from orbitmind.camera import proposal as camera_proposal
from orbitmind.camera import service as camera_service
from orbitmind.camera.contracts import CameraFrameFacts, CameraMediaType
from orbitmind.camera.csrf import (
    CAMERA_CSRF_META_NAME,
    CAMERA_CSRF_NEXT_HEADER,
    CAMERA_CSRF_REQUEST_HEADER,
    CAMERA_PAGE_SESSION_COOKIE_NAME,
    CameraCsrfProtocolAuthority,
    CameraCsrfRoute,
)
from orbitmind.camera.media import (
    CameraMediaError,
    CameraMediaNormalizer,
    NormalizedCameraFrame,
)
from orbitmind.camera.proposal import (
    CAMERA_CREATION_GOAL_LABELS,
    CAMERA_PROPOSAL_ANALYSIS_STATUS,
    CAMERA_PROPOSAL_CONTEXT_MAX_CODEPOINTS,
    CAMERA_PROPOSAL_EXECUTION_STATUS,
    CAMERA_PROPOSAL_STATE,
    CameraCreationGoal,
    CameraCreationProposalRequest,
    CameraProposalValidationError,
)
from orbitmind.camera.runtime import CAMERA_MEDIA_ROOT_NAME, CameraMediaRuntimeContext
from orbitmind.camera.service import (
    CAMERA_MEDIA_CAPABILITY_HEADER,
    CAMERA_MEDIA_MAX_ACTIVE_SESSIONS,
    CameraMediaService,
)
from orbitmind.core.config import Settings

_START = datetime(2026, 7, 17, 9, 30, tzinfo=UTC)
_BASE_URL = "http://127.0.0.1:8000"
_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)


class _Clock:
    def __init__(self) -> None:
        self.value = _START

    def __call__(self) -> datetime:
        return self.value


class _Secrets:
    def __init__(self, domain: bytes) -> None:
        self._domain = domain
        self._calls = 0
        self._lock = threading.Lock()

    def __call__(self) -> bytes:
        with self._lock:
            self._calls += 1
            return hashlib.sha256(self._domain + self._calls.to_bytes(8, "big")).digest()


class _SizedNormalizer(CameraMediaNormalizer):
    def __init__(self, size: int) -> None:
        self.size = size

    def normalize(
        self,
        content: bytes,
        declared_media_type: CameraMediaType,
    ) -> NormalizedCameraFrame:
        del content
        encoded = b"N" * self.size
        return NormalizedCameraFrame(
            content=encoded,
            facts=CameraFrameFacts(
                media_type=declared_media_type,
                width=1,
                height=1,
                encoded_size=len(encoded),
                content_checksum=hashlib.sha256(encoded).hexdigest(),
            ),
            extension=".jpg" if declared_media_type is CameraMediaType.JPEG else ".png",
        )


def _context(root: Path, clock: _Clock | None = None) -> CameraMediaRuntimeContext:
    active_clock = clock or _Clock()
    return CameraMediaRuntimeContext(
        runtime_temp_dir=root,
        media_root=root / CAMERA_MEDIA_ROOT_NAME,
        utcnow=active_clock,
        page_session_id_generator=_Secrets(b"page"),
        csrf_token_generator=_Secrets(b"csrf"),
        media_session_id_generator=_Secrets(b"media"),
        media_capability_generator=_Secrets(b"capability"),
        process_binding_key=hashlib.sha256(b"binding").digest(),
    )


def _service(
    tmp_path: Path,
    *,
    clock: _Clock | None = None,
    normalizer: CameraMediaNormalizer | None = None,
) -> CameraMediaService:
    service = CameraMediaService(_context(tmp_path / "runtime", clock), normalizer=normalizer)
    service.start()
    return service


@pytest.fixture
def media_client(settings: Settings, tmp_path: Path) -> tuple[TestClient, AppContainer]:
    container = AppContainer(
        settings=settings,
        camera_runtime_context=_context(tmp_path / "api-runtime"),
    )
    with TestClient(create_app(container), base_url=_BASE_URL) as client:
        yield client, container  # type: ignore[misc]


def _image(
    image_format: str,
    *,
    size: tuple[int, int] = (8, 6),
    mode: str = "RGB",
    exif: Image.Exif | None = None,
    pnginfo: PngImagePlugin.PngInfo | None = None,
    comment: bytes | None = None,
) -> bytes:
    image = Image.new(mode, size, (25, 80, 140, 180) if mode == "RGBA" else (25, 80, 140))
    try:
        output = BytesIO()
        options: dict[str, object] = {}
        if exif is not None:
            options["exif"] = exif
        if pnginfo is not None:
            options["pnginfo"] = pnginfo
        if comment is not None:
            options["comment"] = comment
        image.save(output, format=image_format, **options)
        return output.getvalue()
    finally:
        image.close()


def _animated_png() -> bytes:
    first = Image.new("RGB", (3, 2), "red")
    second = Image.new("RGB", (3, 2), "blue")
    try:
        output = BytesIO()
        first.save(
            output,
            format="PNG",
            save_all=True,
            append_images=[second],
            duration=20,
            loop=0,
        )
        return output.getvalue()
    finally:
        first.close()
        second.close()


def _page_authority(client: TestClient) -> tuple[str, str]:
    page = client.get("/workbench/camera")
    assert page.status_code == 200
    match = re.search(
        rf'<meta name="{CAMERA_CSRF_META_NAME}" content="([A-Za-z0-9_-]{{43}})">',
        page.text,
    )
    assert match is not None
    cookies = SimpleCookie()
    cookies.load(page.headers["set-cookie"])
    return match.group(1), cookies[CAMERA_PAGE_SESSION_COOKIE_NAME].value


def _modifying_headers(token: str, media_type: str = "image/png") -> dict[str, str]:
    return {
        "Origin": _BASE_URL,
        "Sec-Fetch-Site": "same-origin",
        CAMERA_CSRF_REQUEST_HEADER: token,
        "Content-Type": media_type,
    }


def _create(
    client: TestClient,
    token: str,
    *,
    media_type: str = "image/png",
    body: bytes | None = None,
) -> object:
    return client.post(
        "/workbench/camera/api/sessions",
        headers=_modifying_headers(token, media_type),
        content=_image("PNG") if body is None else body,
    )


def _proposal_headers(
    token: str, capability: str, content_type: str = "application/json"
) -> dict[str, str]:
    return {
        "Origin": _BASE_URL,
        "Sec-Fetch-Site": "same-origin",
        CAMERA_CSRF_REQUEST_HEADER: token,
        CAMERA_MEDIA_CAPABILITY_HEADER: capability,
        "Content-Type": content_type,
    }


def _propose(
    client: TestClient,
    token: str,
    created: dict[str, object],
    *,
    goal: str = "visual_reference",
    user_context: str | None = None,
    capability: str | None = None,
    content_type: str = "application/json",
    content: bytes | None = None,
) -> object:
    session_id = created["session_id"]
    session_capability = capability if capability is not None else created["session_capability"]
    assert isinstance(session_id, str)
    assert isinstance(session_capability, str)
    return client.post(
        f"/workbench/camera/api/sessions/{session_id}/proposal",
        headers=_proposal_headers(token, session_capability, content_type),
        content=content
        if content is not None
        else json.dumps({"goal": goal, "user_context": user_context}).encode("utf-8"),
    )


def _assert_no_store(response: object) -> None:
    headers = response.headers  # type: ignore[attr-defined]
    assert headers["cache-control"] == "no-store"
    assert headers["x-content-type-options"] == "nosniff"
    assert not any(name.casefold().startswith("access-control-") for name in headers)


def test_creation_proposal_contract_is_closed_normalized_and_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert [goal.value for goal in CameraCreationGoal] == [
        "visual_reference",
        "documentation",
        "transformation_request",
        "explanation_request",
        "other",
    ]
    assert dict(CAMERA_CREATION_GOAL_LABELS) == {
        CameraCreationGoal.VISUAL_REFERENCE: "Use as a visual reference",
        CameraCreationGoal.DOCUMENTATION: "Prepare documentation",
        CameraCreationGoal.TRANSFORMATION_REQUEST: "Prepare a transformation request",
        CameraCreationGoal.EXPLANATION_REQUEST: "Prepare an explanation request",
        CameraCreationGoal.OTHER: "Other",
    }
    request = CameraCreationProposalRequest.from_json_object(
        {"goal": "other", "user_context": "  cafe\u0301\r\nreference  "}
    )
    assert request.goal is CameraCreationGoal.OTHER
    assert request.user_context == "café\nreference"
    assert (
        CameraCreationProposalRequest.from_json_object(
            {"goal": "documentation", "user_context": " "}
        ).user_context
        == ""
    )
    assert (
        CameraCreationProposalRequest.from_json_object(
            {"goal": "documentation", "user_context": "\thello\t"}
        ).user_context
        == "hello"
    )
    assert (
        CameraCreationProposalRequest.from_json_object(
            {"goal": "documentation", "user_context": "\t"}
        ).user_context
        == ""
    )
    accepted = "x" * CAMERA_PROPOSAL_CONTEXT_MAX_CODEPOINTS
    assert (
        CameraCreationProposalRequest.from_json_object(
            {"goal": "documentation", "user_context": accepted}
        ).user_context
        == accepted
    )

    for payload, code in (
        ({"goal": "identify_person", "user_context": None}, "camera_proposal_goal_invalid"),
        ({"goal": "other", "user_context": None}, "camera_proposal_context_invalid"),
        ({"goal": "documentation", "user_context": "x" * 501}, "camera_proposal_context_invalid"),
        (
            {"goal": "documentation", "user_context": "bad\x00value"},
            "camera_proposal_context_invalid",
        ),
        (
            {"goal": "documentation", "user_context": "bad\tvalue"},
            "camera_proposal_context_invalid",
        ),
        (
            {"goal": "other", "user_context": "\t"},
            "camera_proposal_context_invalid",
        ),
        ({"goal": "documentation"}, "camera_proposal_request_invalid"),
        (
            {"goal": "documentation", "user_context": None, "extra": True},
            "camera_proposal_request_invalid",
        ),
    ):
        with pytest.raises(CameraProposalValidationError) as error:
            CameraCreationProposalRequest.from_json_object(payload)
        assert error.value.code == code

    service = _service(tmp_path / "proposal-identifiers")
    created = service.create(_image("PNG"), CameraMediaType.PNG)
    values = iter(("A" * 43, "B" * 43))
    monkeypatch.setattr(camera_proposal.secrets, "token_urlsafe", lambda size: next(values))
    first = service.create_proposal(
        created.metadata.session_id,
        (created.session_capability,),
        CameraCreationProposalRequest(CameraCreationGoal.VISUAL_REFERENCE, None),
    )
    assert first.proposal_id == "A" * 43
    assert first.proposal_id not in {created.metadata.session_id, created.session_capability}
    assert len(base64.urlsafe_b64decode(first.proposal_id + "=")) == 32
    assert first.state == CAMERA_PROPOSAL_STATE
    assert first.execution_status == CAMERA_PROPOSAL_EXECUTION_STATUS
    assert first.analysis_status == CAMERA_PROPOSAL_ANALYSIS_STATUS
    assert first.human_approval_required is True
    with pytest.raises(FrozenInstanceError):
        first.goal = CameraCreationGoal.OTHER  # type: ignore[misc]


def test_proposal_endpoint_rotates_authority_and_returns_exact_inert_metadata(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, container = media_client
    token, _cookie = _page_authority(client)
    created_response = _create(client, token)
    created = created_response.json()  # type: ignore[attr-defined]
    next_token = created_response.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    response = _propose(
        client,
        next_token,
        created,
        goal="documentation",
        user_context="  user supplied\r\ncontext  ",
    )

    assert response.status_code == 201  # type: ignore[attr-defined]
    _assert_no_store(response)
    assert CAMERA_CSRF_NEXT_HEADER in response.headers  # type: ignore[attr-defined]
    body = response.json()  # type: ignore[attr-defined]
    assert set(body) == {
        "analysis_status",
        "content_checksum",
        "contract_version",
        "created_at",
        "encoded_size",
        "execution_status",
        "expires_at",
        "goal",
        "height",
        "human_approval_required",
        "media_type",
        "proposal_id",
        "retention_status",
        "session_id",
        "state",
        "user_context",
        "width",
    }
    assert _SECRET_PATTERN.fullmatch(body["proposal_id"])
    assert body["proposal_id"] not in {created["session_id"], created["session_capability"]}
    assert body["session_id"] == created["session_id"]
    assert body["goal"] == "documentation"
    assert body["user_context"] == "user supplied\ncontext"
    assert body["state"] == CAMERA_PROPOSAL_STATE
    assert body["execution_status"] == CAMERA_PROPOSAL_EXECUTION_STATUS
    assert body["analysis_status"] == CAMERA_PROPOSAL_ANALYSIS_STATUS
    assert body["human_approval_required"] is True
    assert body["retention_status"] == "ephemeral"
    for field in (
        "expires_at",
        "media_type",
        "width",
        "height",
        "encoded_size",
        "content_checksum",
    ):
        assert body[field] == created[field]
    assert body["created_at"] <= body["expires_at"]
    assert "capability" not in body and "path" not in body and "filename" not in body
    record = container.require_camera_media_service()._records[created["session_id"]]
    assert record.proposal is not None


def test_proposal_route_is_strict_authorized_and_one_time(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)
    created_response = _create(client, token)
    created = created_response.json()  # type: ignore[attr-defined]
    token = created_response.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    oversized = _propose(client, token, created, content=b"x" * 4097)
    assert oversized.status_code == 413  # type: ignore[attr-defined]
    assert oversized.json()["detail"]["code"] == "camera_proposal_request_invalid"  # type: ignore[attr-defined]
    assert CAMERA_CSRF_NEXT_HEADER not in oversized.headers  # type: ignore[attr-defined]

    missing_origin = client.post(
        f"/workbench/camera/api/sessions/{created['session_id']}/proposal",
        headers={
            CAMERA_CSRF_REQUEST_HEADER: token,
            CAMERA_MEDIA_CAPABILITY_HEADER: created["session_capability"],
            "Content-Type": "application/json",
            "Sec-Fetch-Site": "same-origin",
        },
        content=b'{"goal":"documentation","user_context":null}',
    )
    assert missing_origin.status_code == 403
    assert CAMERA_CSRF_NEXT_HEADER not in missing_origin.headers

    invalid = _propose(
        client,
        token,
        created,
        content=b'{"goal":"documentation","goal":"other","user_context":null}',
    )
    assert invalid.status_code == 400  # type: ignore[attr-defined]
    assert invalid.json()["detail"]["code"] == "camera_proposal_request_invalid"  # type: ignore[attr-defined]
    _assert_no_store(invalid)
    token = invalid.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    non_exact_content_type = _propose(
        client,
        token,
        created,
        content_type="application/json; charset=utf-8",
    )
    assert non_exact_content_type.status_code == 400  # type: ignore[attr-defined]
    assert (
        non_exact_content_type.json()["detail"]["code"] == "camera_proposal_request_invalid"  # type: ignore[attr-defined]
    )
    token = non_exact_content_type.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    wrong_capability = _propose(client, token, created, capability="Z" * 43)
    assert wrong_capability.status_code == 403  # type: ignore[attr-defined]
    assert wrong_capability.json()["detail"]["code"] == "camera_session_forbidden"  # type: ignore[attr-defined]
    token = wrong_capability.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    missing_capability = client.post(
        f"/workbench/camera/api/sessions/{created['session_id']}/proposal",
        headers={
            "Origin": _BASE_URL,
            "Sec-Fetch-Site": "same-origin",
            CAMERA_CSRF_REQUEST_HEADER: token,
            "Content-Type": "application/json",
        },
        content=b'{"goal":"documentation","user_context":null}',
    )
    assert missing_capability.status_code == 403
    assert missing_capability.json()["detail"]["code"] == "camera_session_forbidden"
    token = missing_capability.headers[CAMERA_CSRF_NEXT_HEADER]

    created_proposal = _propose(client, token, created)
    assert created_proposal.status_code == 201  # type: ignore[attr-defined]
    token = created_proposal.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]
    repeated = _propose(client, token, created)
    assert repeated.status_code == 409  # type: ignore[attr-defined]
    assert repeated.json()["detail"]["code"] == "camera_proposal_already_exists"  # type: ignore[attr-defined]
    assert CAMERA_CSRF_NEXT_HEADER in repeated.headers  # type: ignore[attr-defined]

    base = f"/workbench/camera/api/sessions/{created['session_id']}/proposal"
    assert client.get(base).status_code == 405
    assert client.patch(base).status_code == 405
    assert client.delete(base).status_code == 405


def test_modifying_camera_routes_request_distinct_csrf_scopes(
    media_client: tuple[TestClient, AppContainer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, container = media_client
    registry = container.require_camera_page_csrf_registry()
    observed_routes: list[CameraCsrfRoute] = []
    original_preflight = registry.validate_protocol_preflight

    def observed_preflight(authority: CameraCsrfProtocolAuthority) -> object:
        observed_routes.append(authority.route)
        return original_preflight(authority)

    monkeypatch.setattr(registry, "validate_protocol_preflight", observed_preflight)
    token, _cookie = _page_authority(client)
    created_response = _create(client, token)
    created = created_response.json()  # type: ignore[attr-defined]
    token = created_response.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    proposed = _propose(client, token, created)
    assert proposed.status_code == 201  # type: ignore[attr-defined]
    token = proposed.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]
    headers = _modifying_headers(token)
    headers[CAMERA_MEDIA_CAPABILITY_HEADER] = created["session_capability"]
    discarded = client.delete(
        f"/workbench/camera/api/sessions/{created['session_id']}", headers=headers
    )

    assert discarded.status_code == 204
    assert observed_routes == [
        CameraCsrfRoute.CREATE_SESSION,
        CameraCsrfRoute.CREATE_PROPOSAL,
        CameraCsrfRoute.DISCARD_SESSION,
    ]


@pytest.mark.parametrize(
    ("header", "value"),
    [
        ("Host", "localhost:8000"),
        ("Origin", "http://localhost:8000"),
        ("Sec-Fetch-Site", "cross-site"),
    ],
)
def test_proposal_protocol_rejection_precedes_declared_oversize(
    media_client: tuple[TestClient, AppContainer],
    monkeypatch: pytest.MonkeyPatch,
    header: str,
    value: str,
) -> None:
    client, container = media_client
    token, _cookie = _page_authority(client)
    created_response = _create(client, token)
    created = created_response.json()  # type: ignore[attr-defined]
    token = created_response.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]
    reads = 0
    service_lookups = 0

    async def forbidden_reader(request: Request) -> CameraCreationProposalRequest:
        nonlocal reads
        del request
        reads += 1
        raise AssertionError("protocol rejection must not read a proposal body")

    original_service = container.require_camera_media_service

    def observed_service() -> CameraMediaService:
        nonlocal service_lookups
        service_lookups += 1
        return original_service()

    monkeypatch.setattr(camera_media_router, "_read_proposal_request", forbidden_reader)
    monkeypatch.setattr(container, "require_camera_media_service", observed_service)
    headers = _proposal_headers(token, created["session_capability"])
    headers[header] = value
    response = client.post(
        f"/workbench/camera/api/sessions/{created['session_id']}/proposal",
        headers=headers,
        content=b"x" * 4097,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "camera_request_csrf_invalid"}}
    assert CAMERA_CSRF_NEXT_HEADER not in response.headers
    assert reads == service_lookups == 0


def test_proposal_oversize_and_invalid_csrf_precede_body_and_service_lookup(
    media_client: tuple[TestClient, AppContainer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, container = media_client
    token, _cookie = _page_authority(client)
    created_response = _create(client, token)
    created = created_response.json()  # type: ignore[attr-defined]
    token = created_response.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]
    reads = 0
    service_lookups = 0

    async def forbidden_reader(request: Request) -> CameraCreationProposalRequest:
        nonlocal reads
        del request
        reads += 1
        raise AssertionError("request must not read a proposal body before CSRF acceptance")

    original_service = container.require_camera_media_service

    def observed_service() -> CameraMediaService:
        nonlocal service_lookups
        service_lookups += 1
        return original_service()

    monkeypatch.setattr(camera_media_router, "_read_proposal_request", forbidden_reader)
    monkeypatch.setattr(container, "require_camera_media_service", observed_service)
    oversized = client.post(
        f"/workbench/camera/api/sessions/{created['session_id']}/proposal",
        headers=_proposal_headers(token, created["session_capability"]),
        content=b"x" * 4097,
    )
    assert oversized.status_code == 413
    assert oversized.json() == {"detail": {"code": "camera_proposal_request_invalid"}}
    assert CAMERA_CSRF_NEXT_HEADER not in oversized.headers
    assert reads == service_lookups == 0

    invalid_csrf = client.post(
        f"/workbench/camera/api/sessions/{created['session_id']}/proposal",
        headers=_proposal_headers("Z" * 43, created["session_capability"]),
        content=b'{"goal":"documentation","user_context":null}',
    )
    assert invalid_csrf.status_code == 403
    assert invalid_csrf.json() == {"detail": {"code": "camera_request_csrf_invalid"}}
    assert CAMERA_CSRF_NEXT_HEADER not in invalid_csrf.headers
    assert reads == service_lookups == 0


def test_proposal_creation_uses_only_recorded_facts_and_parent_lifecycle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _Clock()
    service = _service(tmp_path, clock=clock)
    created = service.create(_image("PNG"), CameraMediaType.PNG)
    media_path = service.media_root / (created.metadata.session_id + ".png")
    before_stat = media_path.stat()
    before_checksum = hashlib.sha256(media_path.read_bytes()).hexdigest()
    request = CameraCreationProposalRequest(CameraCreationGoal.VISUAL_REFERENCE, None)
    original_open = Path.open

    def deny_media_open(path: Path, *args: object, **kwargs: object) -> object:
        if path == media_path:
            raise AssertionError("proposal creation must not open media")
        return original_open(path, *args, **kwargs)

    def deny_normalize(*args: object, **kwargs: object) -> NormalizedCameraFrame:
        raise AssertionError("proposal creation must not normalize media")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", deny_media_open)
        patch.setattr(service._normalizer, "normalize", deny_normalize)
        proposal = service.create_proposal(
            created.metadata.session_id,
            (created.session_capability,),
            request,
        )

    after_stat = media_path.stat()
    assert hashlib.sha256(media_path.read_bytes()).hexdigest() == before_checksum
    assert after_stat.st_size == before_stat.st_size
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
    assert proposal.content_checksum == created.metadata.content_checksum
    assert proposal.encoded_size == created.metadata.encoded_size
    assert proposal.expires_at == created.metadata.expires_at
    assert service.aggregate_normalized_bytes == created.metadata.encoded_size
    assert len(list(service.media_root.iterdir())) == 1
    assert "PIL" not in inspect.getsource(camera_proposal)

    service.discard(created.metadata.session_id, (created.session_capability,))
    assert created.metadata.session_id not in service._records
    assert not media_path.exists()

    expired = service.create(_image("PNG"), CameraMediaType.PNG)
    service.create_proposal(
        expired.metadata.session_id,
        (expired.session_capability,),
        request,
    )
    clock.value = _START + timedelta(seconds=900)
    with pytest.raises(CameraMediaError, match="session_expired"):
        service.preflight_proposal(expired.metadata.session_id, (expired.session_capability,))
    assert expired.metadata.session_id not in service._records

    shutdown = service.create(_image("PNG"), CameraMediaType.PNG)
    service.create_proposal(
        shutdown.metadata.session_id,
        (shutdown.session_capability,),
        request,
    )
    service.close()
    assert service._records == {}


def test_proposal_lifecycle_tracks_parent_removal_and_deletion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = CameraCreationProposalRequest(CameraCreationGoal.DOCUMENTATION, None)
    clock = _Clock()
    service = _service(tmp_path / "lazy", clock=clock)
    old = service.create(_image("PNG"), CameraMediaType.PNG)
    service.create_proposal(old.metadata.session_id, (old.session_capability,), request)
    clock.value = _START + timedelta(seconds=900)
    service.create(_image("PNG"), CameraMediaType.PNG)
    assert old.metadata.session_id not in service._records
    assert service.active_session_count == 1

    deletion_service = _service(tmp_path / "deletion")
    created = deletion_service.create(_image("PNG"), CameraMediaType.PNG)
    deletion_service.create_proposal(
        created.metadata.session_id,
        (created.session_capability,),
        request,
    )
    media_path = deletion_service.media_root / (created.metadata.session_id + ".png")
    original_unlink = Path.unlink

    def fail_registered(path: Path, *args: object, **kwargs: object) -> None:
        if path == media_path:
            raise PermissionError("simulated proposal parent deletion failure")
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_registered)
    with pytest.raises(CameraMediaError, match="deletion_failed"):
        deletion_service.discard(created.metadata.session_id, (created.session_capability,))
    retained = deletion_service._records[created.metadata.session_id]
    assert retained.proposal is not None
    assert retained.proposal.session_id == created.metadata.session_id


@pytest.mark.parametrize(
    ("media_type", "image_format"),
    [("image/jpeg", "JPEG"), ("image/png", "PNG")],
)
def test_post_creates_exact_metadata_and_one_capability_scoped_file(
    media_client: tuple[TestClient, AppContainer],
    media_type: str,
    image_format: str,
) -> None:
    client, container = media_client
    token, _cookie = _page_authority(client)
    response = _create(client, token, media_type=media_type, body=_image(image_format))

    assert response.status_code == 201  # type: ignore[attr-defined]
    _assert_no_store(response)
    body = response.json()  # type: ignore[attr-defined]
    assert set(body) == {
        "contract_version",
        "session_id",
        "session_capability",
        "state",
        "created_at",
        "expires_at",
        "media_type",
        "width",
        "height",
        "encoded_size",
        "content_checksum",
        "retention_status",
    }
    assert body["contract_version"] == 1
    assert body["state"] == "frame_captured_ephemeral"
    assert body["retention_status"] == "ephemeral"
    assert body["media_type"] == media_type
    assert _SECRET_PATTERN.fullmatch(body["session_id"])
    assert _SECRET_PATTERN.fullmatch(body["session_capability"])
    assert body["session_id"] != body["session_capability"]
    assert len(base64.urlsafe_b64decode(body["session_capability"] + "=")) == 32
    assert CAMERA_CSRF_NEXT_HEADER in response.headers  # type: ignore[attr-defined]

    service = container.require_camera_media_service()
    files = list(service.media_root.iterdir())
    assert len(files) == 1
    stored = files[0].read_bytes()
    assert files[0].name == body["session_id"] + (".jpg" if media_type == "image/jpeg" else ".png")
    assert body["encoded_size"] == len(stored)
    assert body["content_checksum"] == hashlib.sha256(stored).hexdigest()
    assert str(files[0]) not in repr(body)
    assert service.active_session_count == 1
    assert service.aggregate_normalized_bytes == len(stored)
    record = service._records[body["session_id"]]
    assert record.frame_persisted is False
    assert (
        record.capability_digest
        == hashlib.sha256(body["session_capability"].encode("ascii")).digest()
    )
    assert body["session_capability"] not in repr(service._records)
    assert "hmac.compare_digest" in inspect.getsource(camera_service)


@pytest.mark.parametrize(
    "failure",
    ["host", "origin", "fetch", "cookie", "csrf", "forwarded"],
)
def test_post_requires_exact_protocol_cookie_and_csrf_without_rotation(
    media_client: tuple[TestClient, AppContainer], failure: str
) -> None:
    client, container = media_client
    token, cookie = _page_authority(client)
    headers = _modifying_headers(token)
    if failure == "host":
        headers["Host"] = "localhost:8000"
    elif failure == "origin":
        headers["Origin"] = "http://localhost:8000"
    elif failure == "fetch":
        headers["Sec-Fetch-Site"] = "cross-site"
    elif failure == "csrf":
        headers.pop(CAMERA_CSRF_REQUEST_HEADER)
    elif failure == "forwarded":
        headers["X-Forwarded-Host"] = "127.0.0.1:8000"
    elif failure == "cookie":
        client.cookies.clear()

    response = client.post(
        "/workbench/camera/api/sessions",
        headers=headers,
        content=_image("PNG"),
    )

    assert cookie
    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "camera_request_csrf_invalid"}}
    assert CAMERA_CSRF_NEXT_HEADER not in response.headers
    assert container.require_camera_media_service().active_session_count == 0
    assert list(container.require_camera_media_service().media_root.iterdir()) == []
    _assert_no_store(response)


def test_csrf_rotates_before_media_processing_and_old_token_is_rejected(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)
    malformed = _create(client, token, media_type="image/jpeg", body=b"\xff\xd8\xffbroken")
    assert malformed.status_code == 400  # type: ignore[attr-defined]
    assert malformed.json() == {"detail": {"code": "image_decode_failed"}}  # type: ignore[attr-defined]
    next_token = malformed.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    stale = _create(client, token)
    assert stale.status_code == 403  # type: ignore[attr-defined]
    assert CAMERA_CSRF_NEXT_HEADER not in stale.headers  # type: ignore[attr-defined]
    accepted = _create(client, next_token)
    assert accepted.status_code == 201  # type: ignore[attr-defined]


def test_declared_oversize_is_rejected_before_csrf_and_same_token_remains_valid(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)
    headers = _modifying_headers(token)
    headers["Content-Length"] = "5000001"
    rejected = client.post(
        "/workbench/camera/api/sessions",
        headers=headers,
        content=b"x",
    )
    assert rejected.status_code == 413
    assert rejected.json() == {"detail": {"code": "image_too_large"}}
    assert CAMERA_CSRF_NEXT_HEADER not in rejected.headers
    assert _create(client, token).status_code == 201  # type: ignore[attr-defined]


def test_malformed_negative_content_length_is_rejected_without_body_or_rotation() -> None:
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/workbench/camera/api/sessions",
            "headers": [(b"content-length", b"-1")],
        }
    )
    response = _declared_length_error(request)
    assert response is not None
    assert response.status_code == 400
    assert CAMERA_CSRF_NEXT_HEADER not in response.headers


def test_unknown_length_overflow_stops_and_returns_rotated_token(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)

    def chunks() -> object:
        yield b"x" * 5_000_000
        yield b"y"

    response = client.post(
        "/workbench/camera/api/sessions",
        headers=_modifying_headers(token),
        content=chunks(),
    )
    assert response.status_code == 413
    assert response.json() == {"detail": {"code": "image_too_large"}}
    assert CAMERA_CSRF_NEXT_HEADER in response.headers

    bodies = iter((b"x" * 5_000_000, b"y", b"not-requested"))
    calls = 0

    async def receive() -> dict[str, object]:
        nonlocal calls
        calls += 1
        body = next(bodies)
        return {"type": "http.request", "body": body, "more_body": True}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": "/",
            "headers": [],
        },
        receive,
    )
    with pytest.raises(CameraMediaError, match="image_too_large"):
        asyncio.run(_read_bounded_body(request))
    assert calls == 2


def test_status_is_metadata_only_capability_scoped_and_does_not_rotate_csrf(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)
    first = _create(client, token)
    first_body = first.json()  # type: ignore[attr-defined]
    second = _create(client, first.headers[CAMERA_CSRF_NEXT_HEADER])  # type: ignore[attr-defined]
    second_body = second.json()  # type: ignore[attr-defined]
    route = f"/workbench/camera/api/sessions/{first_body['session_id']}"

    missing = client.get(route)
    wrong = client.get(route, headers={CAMERA_MEDIA_CAPABILITY_HEADER: "W" * 43})
    crossed = client.get(
        f"/workbench/camera/api/sessions/{second_body['session_id']}",
        headers={CAMERA_MEDIA_CAPABILITY_HEADER: first_body["session_capability"]},
    )
    status = client.get(
        route,
        headers={CAMERA_MEDIA_CAPABILITY_HEADER: first_body["session_capability"]},
    )

    assert missing.status_code == wrong.status_code == crossed.status_code == 403
    assert status.status_code == 200
    assert "session_capability" not in status.json()
    assert set(status.json()) == set(first_body) - {"session_capability"}
    assert CAMERA_CSRF_NEXT_HEADER not in status.headers
    assert "path" not in status.text.casefold()
    assert "filename" not in status.text.casefold()
    _assert_no_store(status)


def test_delete_requires_csrf_and_capability_rotates_and_only_succeeds_once(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, container = media_client
    token, _cookie = _page_authority(client)
    created = _create(client, token)
    body = created.json()  # type: ignore[attr-defined]
    route = f"/workbench/camera/api/sessions/{body['session_id']}"
    token_2 = created.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    csrf_only = client.delete(route, headers=_modifying_headers(token_2))
    assert csrf_only.status_code == 403
    assert csrf_only.json() == {"detail": {"code": "camera_session_forbidden"}}
    token_3 = csrf_only.headers[CAMERA_CSRF_NEXT_HEADER]

    capability_only = client.delete(
        route,
        headers={CAMERA_MEDIA_CAPABILITY_HEADER: body["session_capability"]},
    )
    assert capability_only.status_code == 403
    assert CAMERA_CSRF_NEXT_HEADER not in capability_only.headers

    headers = _modifying_headers(token_3)
    headers[CAMERA_MEDIA_CAPABILITY_HEADER] = body["session_capability"]
    discarded = client.delete(route, headers=headers)
    assert discarded.status_code == 204
    assert discarded.content == b""
    token_4 = discarded.headers[CAMERA_CSRF_NEXT_HEADER]
    assert container.require_camera_media_service().active_session_count == 0
    assert list(container.require_camera_media_service().media_root.iterdir()) == []

    headers = _modifying_headers(token_4)
    headers[CAMERA_MEDIA_CAPABILITY_HEADER] = body["session_capability"]
    repeated = client.delete(route, headers=headers)
    assert repeated.status_code == 404
    assert repeated.json() == {"detail": {"code": "camera_session_not_found"}}
    assert CAMERA_CSRF_NEXT_HEADER in repeated.headers


def test_capacity_and_deletion_failures_after_csrf_return_the_next_token(
    media_client: tuple[TestClient, AppContainer], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container = media_client
    token, _cookie = _page_authority(client)
    with monkeypatch.context() as scoped:
        scoped.setattr(camera_service, "CAMERA_MEDIA_MAX_ACTIVE_SESSIONS", 0)
        capacity = _create(client, token)
    assert capacity.status_code == 409  # type: ignore[attr-defined]
    assert capacity.json() == {  # type: ignore[attr-defined]
        "detail": {"code": "camera_ephemeral_capacity_exceeded"}
    }
    rotated = capacity.headers[CAMERA_CSRF_NEXT_HEADER]  # type: ignore[attr-defined]

    created = _create(client, rotated)
    body = created.json()  # type: ignore[attr-defined]
    final = next(container.require_camera_media_service().media_root.iterdir())
    original_unlink = Path.unlink

    def fail_registered(path: Path, *args: object, **kwargs: object) -> None:
        if path == final:
            raise PermissionError("simulated deletion failure")
        original_unlink(path, *args, **kwargs)

    headers = _modifying_headers(created.headers[CAMERA_CSRF_NEXT_HEADER])  # type: ignore[attr-defined]
    headers[CAMERA_MEDIA_CAPABILITY_HEADER] = body["session_capability"]
    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "unlink", fail_registered)
        failed = client.delete(
            f"/workbench/camera/api/sessions/{body['session_id']}",
            headers=headers,
        )
    assert failed.status_code == 500
    assert failed.json() == {"detail": {"code": "deletion_failed"}}
    assert CAMERA_CSRF_NEXT_HEADER in failed.headers
    assert container.require_camera_media_service().active_session_count == 1


def test_unexpected_post_rotation_failure_is_sanitized_and_preserves_next_token(
    media_client: tuple[TestClient, AppContainer], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, container = media_client
    token, _cookie = _page_authority(client)

    def fail_without_detail(content: bytes, media_type: CameraMediaType) -> object:
        del content, media_type
        raise RuntimeError("private-path-and-image-detail")

    monkeypatch.setattr(container.require_camera_media_service(), "create", fail_without_detail)
    response = _create(client, token)
    assert response.status_code == 503  # type: ignore[attr-defined]
    assert response.json() == {"detail": {"code": "temporary_storage_failed"}}  # type: ignore[attr-defined]
    assert "private-path-and-image-detail" not in response.text  # type: ignore[attr-defined]
    assert CAMERA_CSRF_NEXT_HEADER in response.headers  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "content_type",
    [
        "image/jpeg; charset=binary",
        "image/svg+xml",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
        "video/mp4",
        "audio/mpeg",
        "application/json",
        "multipart/form-data; boundary=x",
    ],
)
def test_unsupported_and_parameterized_content_types_are_rejected_after_rotation(
    media_client: tuple[TestClient, AppContainer], content_type: str
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)
    response = _create(client, token, media_type=content_type, body=b"payload")
    assert response.status_code == 415  # type: ignore[attr-defined]
    assert response.json() == {"detail": {"code": "image_type_invalid"}}  # type: ignore[attr-defined]
    assert CAMERA_CSRF_NEXT_HEADER in response.headers  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("declared", "actual"),
    [(CameraMediaType.JPEG, "PNG"), (CameraMediaType.PNG, "JPEG")],
)
def test_declared_and_decoded_media_type_must_agree(declared: CameraMediaType, actual: str) -> None:
    with pytest.raises(CameraMediaError, match="image_type_invalid") as error:
        CameraMediaNormalizer().normalize(_image(actual), declared)
    assert error.value.status_code == 415


@pytest.mark.parametrize(
    ("media_type", "content"),
    [
        (CameraMediaType.JPEG, b""),
        (CameraMediaType.JPEG, b"\xff\xd8\xffbroken"),
        (CameraMediaType.PNG, b"\x89PNG\r\n\x1a\nbroken"),
    ],
)
def test_zero_and_malformed_rasters_fail_with_sanitized_errors(
    media_type: CameraMediaType, content: bytes
) -> None:
    with pytest.raises(CameraMediaError) as error:
        CameraMediaNormalizer().normalize(content, media_type)
    assert error.value.code == "image_decode_failed"
    assert "broken" not in repr(error.value)


def test_zero_byte_api_body_is_rejected_after_csrf_rotation(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)
    response = _create(client, token, body=b"")
    assert response.status_code == 400  # type: ignore[attr-defined]
    assert response.json() == {"detail": {"code": "image_decode_failed"}}  # type: ignore[attr-defined]
    assert CAMERA_CSRF_NEXT_HEADER in response.headers  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("size", "accepted"),
    [((1920, 1), True), ((1, 1080), True), ((1921, 1), False), ((1, 1081), False)],
)
def test_dimension_boundaries(size: tuple[int, int], accepted: bool) -> None:
    content = _image("PNG", size=size)
    if accepted:
        normalized = CameraMediaNormalizer().normalize(content, CameraMediaType.PNG)
        assert (normalized.facts.width, normalized.facts.height) == size
    else:
        with pytest.raises(CameraMediaError, match="image_dimensions_invalid"):
            CameraMediaNormalizer().normalize(content, CameraMediaType.PNG)


def test_animation_and_non_jpeg_png_bodies_are_rejected_without_other_decoders() -> None:
    with pytest.raises(CameraMediaError, match="image_type_invalid"):
        CameraMediaNormalizer().normalize(_animated_png(), CameraMediaType.PNG)
    gif = _image("GIF")
    with pytest.raises(CameraMediaError, match="image_type_invalid"):
        CameraMediaNormalizer().normalize(gif, CameraMediaType.JPEG)


def test_decompression_bomb_warning_and_error_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = _image("PNG", size=(20, 20))
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 300)
    with pytest.raises(CameraMediaError, match="image_dimensions_invalid"):
        CameraMediaNormalizer().normalize(content, CameraMediaType.PNG)
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(CameraMediaError, match="image_dimensions_invalid") as error:
        CameraMediaNormalizer().normalize(content, CameraMediaType.PNG)
    assert "DecompressionBomb" not in repr(error.value)


def test_orientation_modes_metadata_and_authoritative_facts_are_normalized() -> None:
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "private-description"
    jpeg_original = _image("JPEG", size=(2, 3), exif=exif, comment=b"private-comment")
    png_info = PngImagePlugin.PngInfo()
    png_info.add_text("private-key", "private-value")
    png_original = _image("PNG", mode="RGBA", pnginfo=png_info)

    jpeg = CameraMediaNormalizer().normalize(jpeg_original, CameraMediaType.JPEG)
    png = CameraMediaNormalizer().normalize(png_original, CameraMediaType.PNG)

    assert (jpeg.facts.width, jpeg.facts.height) == (3, 2)
    assert jpeg.content != jpeg_original
    assert png.content != png_original
    for normalized, expected_format, expected_mode in (
        (jpeg, "JPEG", "RGB"),
        (png, "PNG", "RGBA"),
    ):
        with Image.open(BytesIO(normalized.content)) as image:
            image.load()
            assert image.format == expected_format
            assert image.mode == expected_mode
            assert getattr(image, "n_frames", 1) == 1
            assert "private-key" not in image.info
            assert "comment" not in image.info
            assert not image.getexif()
        assert normalized.facts.encoded_size == len(normalized.content)
        assert normalized.facts.content_checksum == hashlib.sha256(normalized.content).hexdigest()


def test_normalizer_has_no_subprocess_shell_or_network_boundary() -> None:
    source = inspect.getsource(camera_media)
    assert "subprocess" not in source
    assert "socket" not in source
    assert "http" not in source
    assert "shell" not in source
    assert "from PIL" in source


def test_startup_initializes_exact_root_removes_owned_stale_and_preserves_unknown(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path / "runtime")
    context.media_root.mkdir(parents=True)
    stale = context.media_root / ("A" * 43 + ".jpg")
    partial = context.media_root / ("B" * 43 + ".png.part")
    unknown = context.media_root / "operator-note.txt"
    stale.write_bytes(b"stale")
    partial.write_bytes(b"partial")
    unknown.write_text("preserve", encoding="utf-8")

    service = CameraMediaService(context)
    service.start()

    assert service.media_root == context.runtime_temp_dir / CAMERA_MEDIA_ROOT_NAME
    assert service.media_root.is_dir()
    assert not stale.exists()
    assert not partial.exists()
    assert unknown.read_text(encoding="utf-8") == "preserve"
    assert "getenv" not in inspect.getsource(camera_service)
    assert "getcwd" not in inspect.getsource(camera_service)


def test_root_as_file_and_reparse_root_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _context(tmp_path / "file-runtime")
    context.runtime_temp_dir.mkdir(parents=True)
    context.media_root.write_bytes(b"not-directory")
    with pytest.raises(RuntimeError, match="unsafe"):
        CameraMediaService(context).start()

    second = _context(tmp_path / "reparse-runtime")
    second.media_root.mkdir(parents=True)
    original = camera_service._is_reparse
    monkeypatch.setattr(
        camera_service,
        "_is_reparse",
        lambda path: path == second.media_root or original(path),
    )
    with pytest.raises(RuntimeError, match="unsafe"):
        CameraMediaService(second).start()


def test_atomic_write_uses_generated_contained_name_and_never_stores_original(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("discard-me", "private")
    original = _image("PNG", pnginfo=metadata)
    created = service.create(original, CameraMediaType.PNG)
    files = list(service.media_root.iterdir())
    assert len(files) == 1
    final = files[0]
    assert final.name == created.metadata.session_id + ".png"
    assert final.parent == service.media_root
    assert ".part" not in final.name
    assert final.read_bytes() != original
    assert not any(path.name.endswith(".part") for path in service.media_root.iterdir())
    assert created.session_capability not in final.name
    assert created.metadata.content_checksum not in final.name


def test_failed_atomic_replace_leaves_no_record_reservation_or_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, normalizer=_SizedNormalizer(32))
    original = Path.replace

    def fail_replace(source: Path, target: Path) -> Path:
        if source.name.endswith(".part"):
            raise OSError("simulated write failure")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(CameraMediaError, match="temporary_storage_failed"):
        service.create(b"ignored", CameraMediaType.PNG)
    assert service.active_session_count == 0
    assert service.aggregate_normalized_bytes == 0
    assert list(service.media_root.iterdir()) == []


def test_record_is_not_published_until_atomic_finalization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path, normalizer=_SizedNormalizer(32))
    entered = threading.Event()
    release = threading.Event()
    original = Path.replace

    def blocking_replace(source: Path, target: Path) -> Path:
        if source.name.endswith(".part"):
            entered.set()
            assert release.wait(5)
        return original(source, target)

    monkeypatch.setattr(Path, "replace", blocking_replace)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(service.create, b"ignored", CameraMediaType.PNG)
        assert entered.wait(5)
        assert service._records == {}
        assert len(list(service.media_root.glob("*.part"))) == 1
        release.set()
        created = future.result(timeout=5)
    assert created.metadata.session_id in service._records
    assert len(list(service.media_root.glob("*.part"))) == 0


def test_exact_expiry_removes_file_record_and_capacity_and_cannot_reopen(tmp_path: Path) -> None:
    clock = _Clock()
    service = _service(tmp_path, clock=clock)
    created = service.create(_image("PNG"), CameraMediaType.PNG)
    capability = (created.session_capability,)
    assert service.status(created.metadata.session_id, capability) == created.metadata

    clock.value = _START + timedelta(seconds=900)
    with pytest.raises(CameraMediaError, match="session_expired") as expired:
        service.status(created.metadata.session_id, capability)
    assert expired.value.status_code == 410
    assert service.active_session_count == 0
    assert service.aggregate_normalized_bytes == 0
    assert list(service.media_root.iterdir()) == []
    with pytest.raises(CameraMediaError, match="camera_session_not_found"):
        service.status(created.metadata.session_id, capability)


def test_create_lazily_reclaims_expired_capacity_without_evicting_valid_sessions(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    service = _service(tmp_path, clock=clock, normalizer=_SizedNormalizer(16))
    old = [service.create(b"x", CameraMediaType.PNG) for _ in range(8)]
    with pytest.raises(CameraMediaError, match="camera_ephemeral_capacity_exceeded"):
        service.create(b"x", CameraMediaType.PNG)
    clock.value = _START + timedelta(seconds=900)
    fresh = service.create(b"x", CameraMediaType.PNG)
    assert service.active_session_count == 1
    assert fresh.metadata.session_id not in {item.metadata.session_id for item in old}


def test_deletion_failure_is_honest_retains_record_and_releases_no_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path)
    created = service.create(_image("PNG"), CameraMediaType.PNG)
    final = next(service.media_root.iterdir())
    original = Path.unlink

    def fail_registered(path: Path, *args: object, **kwargs: object) -> None:
        if path == final:
            raise PermissionError("simulated deletion failure")
        original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_registered)
    with pytest.raises(CameraMediaError, match="deletion_failed"):
        service.discard(created.metadata.session_id, (created.session_capability,))
    assert service.active_session_count == 1
    assert service.aggregate_normalized_bytes == created.metadata.encoded_size
    assert final.exists()


def test_shutdown_removes_active_and_owned_partials_preserves_unknown_and_is_idempotent(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.create(_image("PNG"), CameraMediaType.PNG)
    partial = service.media_root / ("P" * 43 + ".jpg.part")
    unknown = service.media_root / "unknown.keep"
    partial.write_bytes(b"partial")
    unknown.write_bytes(b"unknown")

    first = service.close()
    second = service.close()

    assert first == second
    assert first.attempted_files == first.deleted_files == 1
    assert first.failed_files == first.failed_partial_files == 0
    assert first.removed_partial_files == 1
    assert service.closed
    assert service.active_session_count == 0
    assert service.aggregate_normalized_bytes == 0
    assert unknown.read_bytes() == b"unknown"
    assert not partial.exists()


def test_concurrent_creates_cannot_exceed_active_or_aggregate_capacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = _service(tmp_path / "active", normalizer=_SizedNormalizer(32))
    barrier = threading.Barrier(CAMERA_MEDIA_MAX_ACTIVE_SESSIONS + 1)

    def create_once() -> str:
        barrier.wait()
        try:
            return service.create(b"x", CameraMediaType.PNG).metadata.session_id
        except CameraMediaError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=9) as executor:
        outcomes = list(executor.map(lambda _index: create_once(), range(9)))
    assert service.active_session_count == 8
    assert outcomes.count("camera_ephemeral_capacity_exceeded") == 1
    assert len(set(outcomes) - {"camera_ephemeral_capacity_exceeded"}) == 8

    monkeypatch.setattr(camera_service, "CAMERA_MEDIA_MAX_AGGREGATE_BYTES", 100)
    aggregate = _service(tmp_path / "aggregate", normalizer=_SizedNormalizer(60))
    aggregate_barrier = threading.Barrier(2)

    def aggregate_create() -> str:
        aggregate_barrier.wait()
        try:
            aggregate.create(b"x", CameraMediaType.PNG)
            return "created"
        except CameraMediaError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        aggregate_outcomes = list(executor.map(lambda _index: aggregate_create(), range(2)))
    assert sorted(aggregate_outcomes) == ["camera_ephemeral_capacity_exceeded", "created"]
    assert aggregate.aggregate_normalized_bytes == 60
    assert aggregate.aggregate_normalized_bytes <= 100


def test_concurrent_discards_and_status_discard_race_are_session_isolated(tmp_path: Path) -> None:
    service = _service(tmp_path)
    created = service.create(_image("PNG"), CameraMediaType.PNG)
    barrier = threading.Barrier(2)

    def discard_once() -> str:
        barrier.wait()
        try:
            service.discard(created.metadata.session_id, (created.session_capability,))
            return "discarded"
        except CameraMediaError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _index: discard_once(), range(2)))
    assert sorted(outcomes) == ["camera_session_not_found", "discarded"]

    second = service.create(_image("PNG"), CameraMediaType.PNG)
    barrier = threading.Barrier(2)

    def status_once() -> str:
        barrier.wait()
        try:
            service.status(second.metadata.session_id, (second.session_capability,))
            return "status"
        except CameraMediaError as error:
            return error.code

    def discard_second() -> str:
        barrier.wait()
        service.discard(second.metadata.session_id, (second.session_capability,))
        return "discarded"

    with ThreadPoolExecutor(max_workers=2) as executor:
        status_future = executor.submit(status_once)
        discard_future = executor.submit(discard_second)
        race = {status_future.result(timeout=5), discard_future.result(timeout=5)}
    assert "discarded" in race
    assert race <= {"discarded", "status", "camera_session_not_found"}
    assert service.active_session_count == 0


def test_no_media_retrieval_multipart_or_filename_contract_exists(
    media_client: tuple[TestClient, AppContainer],
) -> None:
    client, _container = media_client
    token, _cookie = _page_authority(client)
    created = _create(client, token)
    body = created.json()  # type: ignore[attr-defined]
    base = f"/workbench/camera/api/sessions/{body['session_id']}"
    capability = {CAMERA_MEDIA_CAPABILITY_HEADER: body["session_capability"]}

    assert client.get(base + "/media", headers=capability).status_code == 404
    assert client.get(base + "/download", headers=capability).status_code == 404
    assert client.get(base + ".png", headers=capability).status_code == 404
    assert not any(
        getattr(route, "path", "").startswith("/workbench/camera/api")
        and getattr(route, "path", "")
        not in {
            "/workbench/camera/api/sessions",
            "/workbench/camera/api/sessions/{session_id}",
            "/workbench/camera/api/sessions/{session_id}/proposal",
        }
        for route in client.app.routes
    )
    assert "filename" not in created.text.casefold()  # type: ignore[attr-defined]
    assert "multipart" not in inspect.getsource(camera_service).casefold()
    assert "multipart" not in inspect.getsource(camera_media).casefold()
    method_not_allowed = client.put(base, headers=capability)
    _assert_no_store(method_not_allowed)
    assert method_not_allowed.status_code == 405


def test_lifespan_borrows_injected_containers_and_owner_shutdown_isolated(
    settings: Settings, tmp_path: Path
) -> None:
    first = AppContainer(
        settings=settings,
        camera_runtime_context=_context(tmp_path / "first-runtime"),
        caller_owns_lifecycle=True,
    )
    second = AppContainer(
        settings=settings,
        camera_runtime_context=_context(tmp_path / "second-runtime"),
        caller_owns_lifecycle=True,
    )
    first_service = first.require_camera_media_service()
    second_service = second.require_camera_media_service()
    first_registry = first.require_camera_page_csrf_registry()
    second_registry = second.require_camera_page_csrf_registry()
    assert first_service is not second_service
    assert first_registry is not second_registry
    assert first.caller_owns_lifecycle
    assert second.caller_owns_lifecycle

    try:
        with TestClient(create_app(first), base_url=_BASE_URL) as first_client:
            assert first_client.get("/health").status_code == 200
        assert not first_service.closed

        with TestClient(create_app(second), base_url=_BASE_URL) as second_client:
            assert second_client.get("/health").status_code == 200
        assert not second_service.closed

        created = first_service.create(_image("PNG"), CameraMediaType.PNG)
        media_path = first_service.media_root / (created.metadata.session_id + ".png")
        assert media_path.is_file()

        first.shutdown()
        first_report = first.camera_media_shutdown_report
        assert first_service.closed
        assert not media_path.exists()
        assert not second_service.closed
        with pytest.raises(RuntimeError, match="camera media service is closed"):
            first_service.start()

        with TestClient(create_app(second), base_url=_BASE_URL) as second_client:
            assert second_client.get("/health").status_code == 200
        assert not second_service.closed

        first.shutdown()
        assert first.camera_media_shutdown_report == first_report
    finally:
        first.shutdown()
        second.shutdown()


def test_container_shutdown_closes_media_before_csrf_and_preserves_database_cleanup(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    container = AppContainer(
        settings=settings,
        camera_runtime_context=_context(tmp_path / "ordered-runtime"),
    )
    container.init_storage()
    order: list[str] = []
    media_close = container.require_camera_media_service().close
    csrf_close = container.require_camera_page_csrf_registry().close

    def close_media() -> object:
        order.append("media")
        return media_close()

    def close_csrf() -> None:
        order.append("csrf")
        csrf_close()

    monkeypatch.setattr(container.require_camera_media_service(), "close", close_media)
    monkeypatch.setattr(container.require_camera_page_csrf_registry(), "close", close_csrf)
    container.shutdown()
    assert order == ["media", "csrf"]
