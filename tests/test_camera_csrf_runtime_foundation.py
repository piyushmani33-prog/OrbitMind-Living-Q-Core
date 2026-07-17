"""Deterministic security and lifecycle tests for the camera CSRF foundation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import cast

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.container import AppContainer
from orbitmind.api.routers.workbench import CAMERA_PREVIEW_ASSET_PATH
from orbitmind.camera import csrf as camera_csrf
from orbitmind.camera.csrf import (
    CAMERA_CSRF_ERROR_CODE,
    CAMERA_CSRF_META_NAME,
    CAMERA_CSRF_NEXT_HEADER,
    CAMERA_CSRF_REQUEST_HEADER,
    CAMERA_OPAQUE_SECRET_BYTES,
    CAMERA_PAGE_SESSION_COOKIE_NAME,
    CAMERA_PAGE_SESSION_COOKIE_PATH,
    CAMERA_PAGE_SESSION_MAX_ACTIVE,
    CAMERA_PAGE_SESSION_TTL_SECONDS,
    CameraCsrfProtocolAuthority,
    CameraCsrfRejectedError,
    CameraCsrfRequestAuthority,
    CameraCsrfRoute,
    CameraPageCsrfRegistry,
    CameraPageSessionUnavailableError,
    IssuedCameraPageSession,
)
from orbitmind.camera.runtime import CAMERA_MEDIA_ROOT_NAME, CameraMediaRuntimeContext
from orbitmind.core.config import Settings
from orbitmind.runtime import launcher as runtime_launcher
from orbitmind.runtime.configuration import PortConfigurationSource, RuntimeConfiguration
from orbitmind.runtime.paths import RuntimePaths

_START = datetime(2026, 7, 16, 8, 30, tzinfo=UTC)
_SECRET_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$", re.ASCII)
_BINDING_KEY = hashlib.sha256(b"camera-test-binding-key").digest()


class _Clock:
    def __init__(self) -> None:
        self.value = _START

    def __call__(self) -> datetime:
        return self.value


class _Secrets:
    def __init__(self, domain: bytes) -> None:
        self.domain = domain
        self.calls = 0

    def __call__(self) -> bytes:
        self.calls += 1
        return hashlib.sha256(self.domain + self.calls.to_bytes(8, "big")).digest()


def _registry() -> tuple[CameraPageCsrfRegistry, _Clock, _Secrets, _Secrets]:
    clock = _Clock()
    page_secrets = _Secrets(b"page")
    csrf_secrets = _Secrets(b"csrf")
    registry = CameraPageCsrfRegistry(
        clock=clock,
        page_session_id_generator=page_secrets,
        csrf_token_generator=csrf_secrets,
        process_binding_key=_BINDING_KEY,
    )
    return registry, clock, page_secrets, csrf_secrets


def _authority(
    issued: IssuedCameraPageSession,
    *,
    token: str | None = None,
) -> CameraCsrfRequestAuthority:
    return CameraCsrfRequestAuthority(
        method="POST",
        route=CameraCsrfRoute.CREATE_SESSION,
        scheme="http",
        host_values=("127.0.0.1:8000",),
        origin_values=("http://127.0.0.1:8000",),
        sec_fetch_site_values=("same-origin",),
        forwarded_header_names=(),
        page_session_cookie=issued.page_session_id,
        csrf_token_values=(issued.csrf_token if token is None else token,),
        selected_port=8000,
    )


def _protocol_authority(
    *,
    method: str = "POST",
    route: CameraCsrfRoute = CameraCsrfRoute.CREATE_SESSION,
) -> CameraCsrfProtocolAuthority:
    return CameraCsrfProtocolAuthority(
        method=method,
        route=route,
        scheme="http",
        host_values=("127.0.0.1:8000",),
        origin_values=("http://127.0.0.1:8000",),
        sec_fetch_site_values=("same-origin",),
        forwarded_header_names=(),
        selected_port=8000,
    )


def test_protocol_preflight_is_non_mutating_immutable_and_secret_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _clock, _page_secrets, csrf_secrets = _registry()
    issued = registry.issue()
    before_records = dict(registry._records)
    comparisons: list[tuple[bytes, bytes]] = []
    original_compare = camera_csrf.hmac.compare_digest

    def observed(left: bytes, right: bytes) -> bool:
        comparisons.append((left, right))
        return original_compare(left, right)

    monkeypatch.setattr(camera_csrf.hmac, "compare_digest", observed)
    proof = registry.validate_protocol_preflight(_protocol_authority())

    assert registry._records == before_records
    assert csrf_secrets.calls == 1
    assert comparisons == []
    assert issued.page_session_id not in repr(proof)
    assert issued.csrf_token not in repr(proof)
    with pytest.raises(FrozenInstanceError):
        proof._method = "DELETE"  # type: ignore[misc]
    with pytest.raises(TypeError):
        json.dumps(proof)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("host_values", ("localhost:8000",)),
        ("origin_values", ("http://localhost:8000",)),
        ("sec_fetch_site_values", ("cross-site",)),
    ],
)
def test_protocol_preflight_rejects_invalid_protocol_without_mutation(
    field: str, value: tuple[str, ...]
) -> None:
    registry, _clock, _page_secrets, csrf_secrets = _registry()
    registry.issue()
    before_records = dict(registry._records)

    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_protocol_preflight(replace(_protocol_authority(), **{field: value}))

    assert registry._records == before_records
    assert csrf_secrets.calls == 1


def test_protocol_preflight_proof_is_registry_method_route_and_integrity_bound() -> None:
    registry, _clock, _page_secrets, _csrf_secrets = _registry()
    issued = registry.issue()
    proof = registry.validate_protocol_preflight(_protocol_authority())
    other, _other_clock, _other_page_secrets, _other_csrf_secrets = _registry()

    with pytest.raises(CameraCsrfRejectedError):
        other.validate_and_rotate_after_preflight(
            proof,
            expected_route=CameraCsrfRoute.CREATE_SESSION,
            page_session_cookie=issued.page_session_id,
            csrf_token_values=(issued.csrf_token,),
        )
    for malformed in (
        None,
        object(),
        replace(proof, _method="DELETE"),
        replace(proof, _route=CameraCsrfRoute.DISCARD_SESSION),
        replace(proof, _expected_host="127.0.0.1:9999"),
        replace(proof, _integrity=b"invalid"),
    ):
        with pytest.raises(CameraCsrfRejectedError):
            registry.validate_and_rotate_after_preflight(
                malformed,
                expected_route=CameraCsrfRoute.CREATE_SESSION,
                page_session_cookie=issued.page_session_id,
                csrf_token_values=(issued.csrf_token,),
            )

    rotation = registry.validate_and_rotate_after_preflight(
        proof,
        expected_route=CameraCsrfRoute.CREATE_SESSION,
        page_session_cookie=issued.page_session_id,
        csrf_token_values=(issued.csrf_token,),
    )
    assert rotation.generation == 2
    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate_after_preflight(
            proof,
            expected_route=CameraCsrfRoute.CREATE_SESSION,
            page_session_cookie=issued.page_session_id,
            csrf_token_values=(issued.csrf_token,),
        )
    registry.close()
    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate_after_preflight(
            proof,
            expected_route=CameraCsrfRoute.CREATE_SESSION,
            page_session_cookie=issued.page_session_id,
            csrf_token_values=(rotation.csrf_token,),
        )


@pytest.mark.parametrize(
    ("proof_route", "method", "expected_route", "accepted"),
    [
        (CameraCsrfRoute.CREATE_SESSION, "POST", CameraCsrfRoute.CREATE_SESSION, True),
        (CameraCsrfRoute.CREATE_SESSION, "POST", CameraCsrfRoute.CREATE_PROPOSAL, False),
        (CameraCsrfRoute.CREATE_SESSION, "POST", CameraCsrfRoute.DISCARD_SESSION, False),
        (CameraCsrfRoute.CREATE_PROPOSAL, "POST", CameraCsrfRoute.CREATE_PROPOSAL, True),
        (CameraCsrfRoute.CREATE_PROPOSAL, "POST", CameraCsrfRoute.CREATE_SESSION, False),
        (CameraCsrfRoute.CREATE_PROPOSAL, "POST", CameraCsrfRoute.DISCARD_SESSION, False),
        (CameraCsrfRoute.DISCARD_SESSION, "DELETE", CameraCsrfRoute.DISCARD_SESSION, True),
        (CameraCsrfRoute.DISCARD_SESSION, "DELETE", CameraCsrfRoute.CREATE_SESSION, False),
        (CameraCsrfRoute.DISCARD_SESSION, "DELETE", CameraCsrfRoute.CREATE_PROPOSAL, False),
    ],
)
def test_preflight_proof_isolated_to_its_exact_route_scope(
    monkeypatch: pytest.MonkeyPatch,
    proof_route: CameraCsrfRoute,
    method: str,
    expected_route: CameraCsrfRoute,
    accepted: bool,
) -> None:
    registry, _clock, _page_secrets, csrf_secrets = _registry()
    issued = registry.issue()
    proof = registry.validate_protocol_preflight(
        _protocol_authority(method=method, route=proof_route)
    )
    before_records = dict(registry._records)

    def forbidden_session_lookup(page_session_id: str) -> bytes:
        del page_session_id
        raise AssertionError("cross-route rejection must precede session lookup")

    if not accepted:
        monkeypatch.setattr(registry, "_page_binding_for_validation", forbidden_session_lookup)
        with pytest.raises(CameraCsrfRejectedError):
            registry.validate_and_rotate_after_preflight(
                proof,
                expected_route=expected_route,
                page_session_cookie=issued.page_session_id,
                csrf_token_values=(issued.csrf_token,),
            )
        assert registry._records == before_records
        assert csrf_secrets.calls == 1
        return

    assert (
        registry.validate_and_rotate_after_preflight(
            proof,
            expected_route=expected_route,
            page_session_cookie=issued.page_session_id,
            csrf_token_values=(issued.csrf_token,),
        ).generation
        == 2
    )


def test_combined_helper_remains_a_protocol_preflight_compatibility_wrapper() -> None:
    registry, _clock, _page_secrets, _csrf_secrets = _registry()
    issued = registry.issue()

    rotation = registry.validate_and_rotate(_authority(issued))

    assert rotation.generation == 2
    assert registry._protocol_preflight_issuer is not _registry()[0]._protocol_preflight_issuer


def _context(temp_dir: Path, *, binding_key: bytes = _BINDING_KEY) -> CameraMediaRuntimeContext:
    return CameraMediaRuntimeContext(
        runtime_temp_dir=temp_dir,
        media_root=temp_dir / CAMERA_MEDIA_ROOT_NAME,
        utcnow=lambda: _START,
        page_session_id_generator=_Secrets(b"context-page"),
        csrf_token_generator=_Secrets(b"context-csrf"),
        media_session_id_generator=_Secrets(b"context-media"),
        media_capability_generator=_Secrets(b"context-capability"),
        process_binding_key=binding_key,
    )


def _meta_token(body: str) -> str:
    match = re.search(rf'<meta name="{CAMERA_CSRF_META_NAME}" content="([A-Za-z0-9_-]+)">', body)
    assert match is not None
    return match.group(1)


def test_camera_csrf_constants_are_exact() -> None:
    assert CAMERA_PAGE_SESSION_TTL_SECONDS == 900
    assert CAMERA_PAGE_SESSION_MAX_ACTIVE == 16
    assert CAMERA_PAGE_SESSION_COOKIE_NAME == "OrbitMind-Camera-Page"
    assert CAMERA_PAGE_SESSION_COOKIE_PATH == "/workbench/camera"
    assert CAMERA_CSRF_META_NAME == "orbitmind-camera-csrf"
    assert CAMERA_CSRF_REQUEST_HEADER == "X-OrbitMind-Camera-CSRF"
    assert CAMERA_CSRF_NEXT_HEADER == "X-OrbitMind-Camera-CSRF-Next"
    assert CAMERA_CSRF_ERROR_CODE == "camera_request_csrf_invalid"
    assert CAMERA_OPAQUE_SECRET_BYTES == 32


def test_issue_uses_independent_256_bit_secrets_and_stores_only_digests() -> None:
    registry, _clock, page_secrets, csrf_secrets = _registry()
    issued = registry.issue()

    assert page_secrets.calls == csrf_secrets.calls == 1
    assert issued.page_session_id != issued.csrf_token
    assert _SECRET_PATTERN.fullmatch(issued.page_session_id)
    assert _SECRET_PATTERN.fullmatch(issued.csrf_token)
    assert len(base64.urlsafe_b64decode(issued.page_session_id + "=")) == 32
    assert len(base64.urlsafe_b64decode(issued.csrf_token + "=")) == 32
    assert issued.expires_at - issued.issued_at == timedelta(seconds=900)

    expected_binding = hmac.digest(
        _BINDING_KEY,
        b"orbitmind-camera-page-session-v1\x00" + issued.page_session_id.encode("ascii"),
        "sha256",
    )
    record = registry._records[expected_binding]
    assert record.page_binding_digest == expected_binding
    assert record.csrf_token_digest == hashlib.sha256(issued.csrf_token.encode("ascii")).digest()
    assert issued.page_session_id not in repr(registry._records)
    assert issued.csrf_token not in repr(registry._records)
    assert issued.page_session_id.encode("ascii") not in record.page_binding_digest
    assert issued.csrf_token.encode("ascii") not in record.csrf_token_digest
    with pytest.raises(FrozenInstanceError):
        record.generation = 4  # type: ignore[misc]


def test_registry_capacity_does_not_evict_valid_sessions_and_lazy_expiry_reclaims() -> None:
    registry, clock, _page_secrets, _csrf_secrets = _registry()
    issued = [registry.issue() for _ in range(CAMERA_PAGE_SESSION_MAX_ACTIVE)]

    assert registry.active_session_count == CAMERA_PAGE_SESSION_MAX_ACTIVE
    with pytest.raises(CameraPageSessionUnavailableError):
        registry.issue()
    assert registry.active_session_count == CAMERA_PAGE_SESSION_MAX_ACTIVE
    assert issued[0].page_session_id not in repr(registry._records)

    clock.value = _START + timedelta(seconds=CAMERA_PAGE_SESSION_TTL_SECONDS)
    assert registry.active_session_count == 0
    assert registry.issue().issued_at == clock.value


def test_reload_invalidates_old_page_session_before_issuing_new_pair() -> None:
    registry, _clock, _page_secrets, _csrf_secrets = _registry()
    first = registry.issue()
    second = registry.issue(first.page_session_id)

    assert registry.active_session_count == 1
    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate(_authority(first))
    assert registry.validate_and_rotate(_authority(second)).generation == 2


def test_success_rotates_once_and_old_or_repeated_token_is_rejected() -> None:
    registry, _clock, _page_secrets, csrf_secrets = _registry()
    issued = registry.issue()

    rotation = registry.validate_and_rotate(_authority(issued))
    record = next(iter(registry._records.values()))

    assert rotation.generation == 2
    assert rotation.csrf_token != issued.csrf_token
    assert record.expires_at == issued.expires_at
    assert csrf_secrets.calls == 2
    with pytest.raises(CameraCsrfRejectedError) as failure:
        registry.validate_and_rotate(_authority(issued))
    assert failure.value.code == CAMERA_CSRF_ERROR_CODE
    assert csrf_secrets.calls == 2
    next_authority = _authority(issued, token=rotation.csrf_token)
    assert registry.validate_and_rotate(next_authority).generation == 3


def test_next_token_generation_failure_does_not_commit_partial_rotation() -> None:
    clock = _Clock()
    generated = iter(
        (
            hashlib.sha256(b"initial-token").digest(),
            b"invalid",
            hashlib.sha256(b"valid-next-token").digest(),
        )
    )
    registry = CameraPageCsrfRegistry(
        clock=clock,
        page_session_id_generator=_Secrets(b"page"),
        csrf_token_generator=lambda: next(generated),
        process_binding_key=_BINDING_KEY,
    )
    issued = registry.issue()

    with pytest.raises(CameraPageSessionUnavailableError):
        registry.validate_and_rotate(_authority(issued))

    record = next(iter(registry._records.values()))
    assert record.generation == 1
    assert record.csrf_token_digest == hashlib.sha256(issued.csrf_token.encode("ascii")).digest()
    assert registry.validate_and_rotate(_authority(issued)).generation == 2


def test_token_comparison_uses_constant_time_digest_comparison(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, _clock, _page_secrets, _csrf_secrets = _registry()
    issued = registry.issue()
    calls: list[tuple[bytes, bytes]] = []
    original = hmac.compare_digest

    def observed(left: bytes, right: bytes) -> bool:
        calls.append((left, right))
        return original(left, right)

    monkeypatch.setattr(camera_csrf.hmac, "compare_digest", observed)
    registry.validate_and_rotate(_authority(issued))

    assert len(calls) == 3
    assert all(len(left) == len(right) == hashlib.sha256().digest_size for left, right in calls)


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("scheme", "https"),
        ("host_values", ("localhost:8000",)),
        ("host_values", ("127.0.0.1:8001",)),
        ("host_values", ("127.0.0.1:8000", "127.0.0.1:8000")),
        ("origin_values", ()),
        ("origin_values", ("null",)),
        ("origin_values", ("http://127.0.0.1:8001",)),
        ("origin_values", ("http://127.0.0.1:8000", "http://127.0.0.1:8000")),
        ("sec_fetch_site_values", ()),
        ("sec_fetch_site_values", ("cross-site",)),
        ("sec_fetch_site_values", ("same-site",)),
        ("forwarded_header_names", ("Forwarded",)),
        ("forwarded_header_names", ("X-Forwarded-For",)),
        ("page_session_cookie", None),
        ("page_session_cookie", "wrong"),
        ("csrf_token_values", ()),
        ("csrf_token_values", ("wrong",)),
        ("csrf_token_values", ("a" * 43, "a" * 43)),
        ("method", "DELETE"),
        ("selected_port", 80),
        ("selected_port", True),
    ],
)
def test_protocol_and_authority_failures_share_one_sanitized_result(
    change: str, value: object
) -> None:
    registry, _clock, _page_secrets, _csrf_secrets = _registry()
    issued = registry.issue()
    authority = replace(_authority(issued), **{change: value})

    with pytest.raises(CameraCsrfRejectedError) as failure:
        registry.validate_and_rotate(authority)

    assert str(failure.value) == failure.value.code == CAMERA_CSRF_ERROR_CODE
    assert failure.value.status_code == 403
    assert failure.value.detail == {"code": CAMERA_CSRF_ERROR_CODE}
    assert issued.page_session_id not in str(failure.value)
    assert issued.csrf_token not in str(failure.value)
    assert not hasattr(authority, "body")


def test_cross_session_cookie_and_token_are_rejected() -> None:
    registry, _clock, _page_secrets, _csrf_secrets = _registry()
    first = registry.issue()
    second = registry.issue()

    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate(_authority(first, token=second.csrf_token))
    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate(_authority(second, token=first.csrf_token))


def test_exact_delete_route_and_method_are_allowed() -> None:
    registry, _clock, _page_secrets, _csrf_secrets = _registry()
    issued = registry.issue()
    authority = replace(
        _authority(issued),
        method="DELETE",
        route=CameraCsrfRoute.DISCARD_SESSION,
    )

    assert registry.validate_and_rotate(authority).generation == 2


def test_expiry_is_absolute_non_sliding_and_fails_at_exact_boundary() -> None:
    registry, clock, _page_secrets, csrf_secrets = _registry()
    issued = registry.issue()
    clock.value = issued.expires_at

    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate(_authority(issued))

    assert registry.active_session_count == 0
    assert csrf_secrets.calls == 1
    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate(_authority(issued))


def test_concurrent_reuse_accepts_exactly_one_generation_without_sleeps() -> None:
    registry, _clock, _page_secrets, csrf_secrets = _registry()
    issued = registry.issue()
    authority = _authority(issued)
    barrier = threading.Barrier(3)

    def attempt() -> str:
        barrier.wait()
        try:
            registry.validate_and_rotate(authority)
        except CameraCsrfRejectedError:
            return "rejected"
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt) for _ in range(2)]
        barrier.wait()
        results = [future.result() for future in futures]

    assert sorted(results) == ["accepted", "rejected"]
    assert csrf_secrets.calls == 2


def test_close_is_idempotent_clears_authority_and_restart_does_not_restore_it() -> None:
    first, _clock, _page_secrets, _csrf_secrets = _registry()
    issued = first.issue()
    first.close()
    first.close()

    assert first.closed
    assert first.active_session_count == 0
    assert first._records == {}
    assert first._process_binding_key == b""
    with pytest.raises(CameraPageSessionUnavailableError):
        first.issue()
    with pytest.raises(CameraCsrfRejectedError):
        first.validate_and_rotate(_authority(issued))

    second = CameraPageCsrfRegistry(
        clock=lambda: _START,
        page_session_id_generator=_Secrets(b"restart-page"),
        csrf_token_generator=_Secrets(b"restart-csrf"),
        process_binding_key=hashlib.sha256(b"new-process-key").digest(),
    )
    with pytest.raises(CameraCsrfRejectedError):
        second.validate_and_rotate(_authority(issued))


def test_runtime_context_derives_exact_normalized_child_without_filesystem_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    temp_dir = tmp_path / "runtime" / "temp"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "must-not-be-read"))

    context = _context(temp_dir)

    assert context.runtime_temp_dir == temp_dir.resolve()
    assert context.media_root == (temp_dir / CAMERA_MEDIA_ROOT_NAME).resolve()
    assert context.media_root.parent == context.runtime_temp_dir
    assert not temp_dir.exists()
    assert not context.media_root.exists()
    assert "camera-process" not in repr(context)


@pytest.mark.parametrize("kind", ["relative", "sibling", "parent", "file"])
def test_runtime_context_rejects_unsafe_or_non_directory_paths(tmp_path: Path, kind: str) -> None:
    temp_dir = tmp_path / "temp"
    media_root = temp_dir / CAMERA_MEDIA_ROOT_NAME
    if kind == "relative":
        temp_dir = Path("relative-temp")
        media_root = temp_dir / CAMERA_MEDIA_ROOT_NAME
    elif kind == "sibling":
        media_root = tmp_path / "camera-sessions"
    elif kind == "parent":
        media_root = tmp_path
    elif kind == "file":
        temp_dir.write_text("not a directory", encoding="utf-8")

    with pytest.raises(ValueError):
        CameraMediaRuntimeContext(
            runtime_temp_dir=temp_dir,
            media_root=media_root,
            utcnow=lambda: _START,
            page_session_id_generator=_Secrets(b"page"),
            csrf_token_generator=_Secrets(b"csrf"),
            media_session_id_generator=_Secrets(b"media"),
            media_capability_generator=_Secrets(b"capability"),
            process_binding_key=_BINDING_KEY,
        )


def test_app_container_owns_one_registry_and_shutdown_closes_only_its_registry(
    settings: Settings, tmp_path: Path
) -> None:
    first_context = _context(tmp_path / "first", binding_key=b"1" * 32)
    second_context = _context(tmp_path / "second", binding_key=b"2" * 32)
    first = AppContainer(settings=settings, camera_runtime_context=first_context)
    second = AppContainer(settings=settings, camera_runtime_context=second_context)

    first_registry = first.require_camera_page_csrf_registry()
    second_registry = second.require_camera_page_csrf_registry()
    assert first.camera_runtime_context is first_context
    assert second.camera_runtime_context is second_context
    assert first_registry is first.require_camera_page_csrf_registry()
    assert first_registry is not second_registry
    first_registry.issue()
    second_registry.issue()
    assert set(first_registry._records) != set(second_registry._records)

    first.shutdown()
    assert first_registry.closed
    assert not second_registry.closed
    second.shutdown()


def test_launcher_composition_injects_and_initializes_exact_runtime_media_root(
    settings: Settings, tmp_path: Path
) -> None:
    paths = RuntimePaths(tmp_path / "packaged-runtime")
    configuration = RuntimeConfiguration(
        settings=settings,
        port=8000,
        port_source=PortConfigurationSource.DEFAULT,
        open_browser=False,
        runtime_paths=paths,
    )
    app = runtime_launcher._build_application(configuration)

    with TestClient(app):
        container = cast(AppContainer, app.state.container)
        context = container.camera_runtime_context
        assert context is not None
        assert context.runtime_temp_dir == paths.temp_dir.resolve()
        assert context.media_root == (paths.temp_dir / CAMERA_MEDIA_ROOT_NAME).resolve()
        assert container.require_camera_page_csrf_registry().active_session_count == 0
        assert context.media_root.is_dir()
        assert list(context.media_root.iterdir()) == []

    assert container.require_camera_page_csrf_registry().closed
    assert context.media_root.is_dir()
    assert list(context.media_root.iterdir()) == []


def test_camera_page_issues_exact_cookie_meta_and_no_store(client: TestClient) -> None:
    response = client.get("/workbench/camera")
    token = _meta_token(response.text)
    cookies = response.headers.get_list("set-cookie")
    parsed = SimpleCookie()
    parsed.load(cookies[0])
    morsel = parsed[CAMERA_PAGE_SESSION_COOKIE_NAME]

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert len(cookies) == 1
    assert set(parsed) == {CAMERA_PAGE_SESSION_COOKIE_NAME}
    assert _SECRET_PATTERN.fullmatch(morsel.value)
    assert morsel["httponly"] is True
    assert morsel["samesite"] == "strict"
    assert morsel["path"] == CAMERA_PAGE_SESSION_COOKIE_PATH
    assert morsel["max-age"] == str(CAMERA_PAGE_SESSION_TTL_SECONDS)
    assert morsel["domain"] == ""
    assert morsel["secure"] == ""
    assert response.text.count(f'name="{CAMERA_CSRF_META_NAME}"') == 1
    assert _SECRET_PATTERN.fullmatch(token)
    assert token != morsel.value

    without_meta = re.sub(rf'<meta name="{CAMERA_CSRF_META_NAME}"[^>]+>\n?', "", response.text)
    assert token not in without_meta
    assert token not in str(response.url)
    assert token not in client.get(CAMERA_PREVIEW_ASSET_PATH).text
    lowered = response.text.casefold()
    assert '<input type="file"' not in lowered
    assert "multipart/form-data" not in lowered
    assert ">upload<" not in lowered


def test_camera_page_reload_invalidates_prior_cookie_and_unrelated_route_issues_none(
    client: TestClient, container: AppContainer
) -> None:
    first = client.get("/workbench/camera")
    first_token = _meta_token(first.text)
    first_cookie = SimpleCookie()
    first_cookie.load(first.headers["set-cookie"])
    first_page_id = first_cookie[CAMERA_PAGE_SESSION_COOKIE_NAME].value

    unrelated = client.get("/workbench")
    second = client.get("/workbench/camera")
    second_cookie = SimpleCookie()
    second_cookie.load(second.headers["set-cookie"])

    assert "set-cookie" not in unrelated.headers
    assert second_cookie[CAMERA_PAGE_SESSION_COOKIE_NAME].value != first_page_id
    assert _meta_token(second.text) != first_token
    registry = container.require_camera_page_csrf_registry()
    assert registry.active_session_count == 1
    stale = IssuedCameraPageSession(
        page_session_id=first_page_id,
        csrf_token=first_token,
        issued_at=_START,
        expires_at=_START + timedelta(seconds=900),
    )
    with pytest.raises(CameraCsrfRejectedError):
        registry.validate_and_rotate(_authority(stale))


def test_camera_page_capacity_failure_issues_no_cookie_or_token(
    client: TestClient, container: AppContainer
) -> None:
    registry = container.require_camera_page_csrf_registry()
    for _ in range(CAMERA_PAGE_SESSION_MAX_ACTIVE):
        registry.issue()
    client.cookies.clear()

    response = client.get("/workbench/camera")

    assert response.status_code == 503
    assert response.text == "Camera preview is temporarily unavailable."
    assert response.headers["cache-control"] == "no-store"
    assert "set-cookie" not in response.headers
    assert CAMERA_CSRF_META_NAME not in response.text
