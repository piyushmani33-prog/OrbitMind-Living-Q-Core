"""Preview-only security and route coverage for the local camera sandbox."""

from __future__ import annotations

import inspect
import re
from html.parser import HTMLParser
from importlib import resources

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.app import CONTENT_SECURITY_POLICY
from orbitmind.api.routers import workbench
from orbitmind.api.routers.workbench import (
    CAMERA_PREVIEW_ASSET_PATH,
    CAMERA_PREVIEW_CONTENT_SECURITY_POLICY,
    CAMERA_PREVIEW_PERMISSIONS_POLICY,
)


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.elements.append((tag, dict(attrs)))

    def by_id(self, element_id: str) -> tuple[str, dict[str, str | None]]:
        return next(element for element in self.elements if element[1].get("id") == element_id)


def _camera_page(client: TestClient) -> tuple[str, _PageParser]:
    response = client.get("/workbench/camera")
    parser = _PageParser()
    parser.feed(response.text)
    return response.text, parser


def _camera_script(client: TestClient) -> str:
    response = client.get(CAMERA_PREVIEW_ASSET_PATH)
    assert response.status_code == 200
    return response.text


def _button_labels(body: str) -> list[str]:
    return [
        " ".join(re.sub(r"<[^>]+>", "", value).split())
        for value in re.findall(r"<button\b[^>]*>(.*?)</button>", body, flags=re.I | re.S)
    ]


def test_camera_preview_route_is_inactive_private_and_server_rendered(
    client: TestClient,
) -> None:
    response = client.get("/workbench/camera")
    body = response.text

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Local camera preview" in body
    assert "The camera stays off until" in body
    assert "Preview remains local in this browser" in body
    assert "Create temporary session" in body
    assert "expires after 15 minutes" in body
    assert "inert temporary proposal only" in body
    assert "Microphone is not used" in body
    assert "Enable camera" in _button_labels(body)
    assert "Stop camera" in _button_labels(body)
    assert "Capture frame" in _button_labels(body)
    assert 'id="camera-stop" type="button" disabled' in body
    assert 'id="camera-capture" type="button" disabled' in body
    assert 'id="camera-active-indicator" hidden' in body
    assert 'id="camera-device-field" for="camera-device" hidden' in body
    assert 'id="camera-device" disabled' in body
    assert 'href="/workbench"' in body
    assert "Back to Workbench" in body
    assert inspect.signature(workbench.camera_preview_sandbox).parameters == {}


def test_camera_preview_page_has_one_exact_script_and_no_external_resources(
    client: TestClient,
) -> None:
    body, parser = _camera_page(client)
    scripts = [attrs for tag, attrs in parser.elements if tag == "script"]

    assert scripts == [{"src": CAMERA_PREVIEW_ASSET_PATH, "defer": None}]
    assert body.count(f'<script src="{CAMERA_PREVIEW_ASSET_PATH}" defer></script>') == 1
    assert "<script>" not in body
    assert not re.search(r"\son[a-z]+\s*=", body, flags=re.I)
    assert "http://" not in body.lower()
    assert "https://" not in body.lower()
    assert "//cdn" not in body.lower()
    for tag, attrs in parser.elements:
        if tag in {"img", "iframe", "audio", "source", "object", "embed", "link"}:
            assert not attrs.get("src")
            assert not attrs.get("href")


def test_camera_preview_has_only_bounded_capture_controls(
    client: TestClient,
) -> None:
    body = client.get("/workbench/camera").text
    labels = {label.casefold() for label in _button_labels(body)}

    assert labels == {
        "capture frame",
        "create proposal",
        "create temporary session",
        "discard",
        "discard temporary server frame",
        "enable camera",
        "retake",
        "stop camera",
    }
    for forbidden in (
        "save",
        "analyze",
        "record",
        "submit",
        "execute",
        "generate",
        "download",
        "share",
        "copy image",
    ):
        assert forbidden not in labels
    assert '<input type="file"' not in body.lower()
    assert "multipart/form-data" not in body.lower()
    assert 'id="camera-capture-format"' in body
    assert body.count('<option value="image/jpeg">JPEG</option>') == 1
    assert body.count('<option value="image/png">PNG</option>') == 1
    assert 'id="camera-captured-image"' in body
    assert (
        'id="camera-captured-image"\n            alt="Captured still-frame preview" hidden' in body
    )
    assert 'id="camera-captured-panel"' in body
    assert 'aria-labelledby="camera-captured-heading" hidden' in body
    assert 'id="camera-capture-metadata" hidden' in body
    assert 'id="camera-retake" type="button" hidden' in body
    assert 'id="camera-discard" type="button" hidden' in body
    assert 'id="camera-create-session" type="button" disabled' in body
    assert 'id="camera-server-session-panel"' in body
    assert 'id="camera-proposal-controls" hidden' in body
    assert 'id="camera-proposal-goal" disabled' in body
    assert 'id="camera-proposal-context" maxlength="500"' in body
    assert 'id="camera-create-proposal" type="button" disabled' in body
    assert 'id="camera-proposal-panel"' in body
    assert body.count('<option value="visual_reference">Use as a visual reference</option>') == 1
    assert body.count('<option value="documentation">Prepare documentation</option>') == 1
    assert (
        body.count(
            '<option value="transformation_request">Prepare a transformation request</option>'
        )
        == 1
    )
    assert (
        body.count('<option value="explanation_request">Prepare an explanation request</option>')
        == 1
    )
    assert body.count('<option value="other">Other</option>') == 1
    assert 'id="camera-server-discard" type="button" hidden' in body
    assert "filename" not in body.casefold()


def test_camera_preview_accessibility_contract(client: TestClient) -> None:
    body, parser = _camera_page(client)
    enable = parser.by_id("camera-enable")[1]
    stop = parser.by_id("camera-stop")[1]
    capture = parser.by_id("camera-capture")[1]
    retake = parser.by_id("camera-retake")[1]
    discard = parser.by_id("camera-discard")[1]
    create_session = parser.by_id("camera-create-session")[1]
    create_proposal = parser.by_id("camera-create-proposal")[1]
    proposal_goal = parser.by_id("camera-proposal-goal")[1]
    proposal_context = parser.by_id("camera-proposal-context")[1]
    server_discard = parser.by_id("camera-server-discard")[1]
    status = parser.by_id("camera-status")[1]
    support = parser.by_id("camera-support-status")[1]
    video = parser.by_id("camera-preview")[1]
    captured_image = parser.by_id("camera-captured-image")[1]

    assert enable["type"] == "button"
    assert stop["type"] == "button"
    assert capture["type"] == "button"
    assert retake["type"] == "button"
    assert discard["type"] == "button"
    assert create_session["type"] == "button"
    assert create_proposal["type"] == "button"
    assert server_discard["type"] == "button"
    assert "disabled" in stop
    assert "disabled" in capture
    assert "hidden" in retake
    assert "hidden" in discard
    assert "disabled" in create_session
    assert "disabled" in create_proposal
    assert "disabled" in proposal_goal
    assert "disabled" in proposal_context
    assert proposal_context["maxlength"] == "500"
    assert "hidden" in server_discard
    assert status["role"] == "status"
    assert status["aria-live"] == "polite"
    assert status["aria-atomic"] == "true"
    assert support["aria-live"] == "polite"
    assert {"autoplay", "muted", "playsinline"}.issubset(video)
    assert video["aria-describedby"] == "camera-privacy-note camera-status"
    assert captured_image["alt"] == "Captured still-frame preview"
    assert "hidden" in captured_image
    assert "CAMERA ACTIVE" in body
    assert ":focus-visible" in body
    assert "prefers-reduced-motion: reduce" in body
    assert "min-height: 52px" in body


def test_camera_preview_route_uses_narrow_permissions_policy(client: TestClient) -> None:
    response = client.get("/workbench/camera")
    policy = response.headers["permissions-policy"]

    assert policy == CAMERA_PREVIEW_PERMISSIONS_POLICY
    assert "camera=(self)" in policy
    assert "microphone=()" in policy
    assert "camera=(*)" not in policy
    assert "*" not in policy
    assert "http://" not in policy
    assert "https://" not in policy


@pytest.mark.parametrize("path", ["/workbench", "/review"])
def test_unrelated_html_routes_continue_to_deny_camera_and_microphone(
    client: TestClient, path: str
) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert "camera=()" in response.headers["permissions-policy"]
    assert "microphone=()" in response.headers["permissions-policy"]
    assert "camera=(self)" not in response.headers["permissions-policy"]


def test_camera_preview_retains_restrictive_csp(client: TestClient) -> None:
    response = client.get("/workbench/camera")
    policy = response.headers["content-security-policy"]

    assert policy == CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
    assert policy == CONTENT_SECURITY_POLICY.replace(
        "img-src 'self' data:", "img-src 'self' blob:"
    ).replace("connect-src 'none'", "connect-src 'self'")
    assert "default-src 'none'" in policy
    assert "script-src 'self'" in policy
    assert "img-src 'self' blob:" in policy
    assert "connect-src 'self'" in policy
    assert "media-src 'none'" in policy
    assert "object-src 'none'" in policy
    assert "frame-ancestors 'none'" in policy
    assert "'unsafe-eval'" not in policy
    assert policy.count("blob:") == 1
    assert "data:" not in policy

    assert client.get("/workbench").headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "blob:" not in client.get("/review").headers["content-security-policy"]


def test_camera_preview_asset_is_exact_packaged_resource(client: TestClient) -> None:
    first = client.get(CAMERA_PREVIEW_ASSET_PATH)
    second = client.get(CAMERA_PREVIEW_ASSET_PATH)
    unknown = client.get("/assets/camera-preview-extra.js")
    traversal = client.get("/assets/..%2Frouters%2Fworkbench.py")
    packaged = resources.files("orbitmind.api.assets").joinpath("camera_preview.js")

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/javascript; charset=utf-8"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["cache-control"] == "no-store"
    assert first.content == second.content == packaged.read_bytes()
    assert unknown.status_code == 404
    assert traversal.status_code == 404
    assert "sourceMappingURL" not in first.text
    assert "C:\\" not in first.text
    assert "/home/" not in first.text


def test_missing_camera_asset_failure_is_sanitized(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing_package(_package: str) -> object:
        raise FileNotFoundError("E:/private/camera/device-secret.js")

    monkeypatch.setattr(workbench.resources, "files", missing_package)
    response = client.get(CAMERA_PREVIEW_ASSET_PATH)

    assert response.status_code == 500
    assert response.text == "Camera preview asset unavailable."
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "private" not in response.text
    assert "Traceback" not in response.text


def test_camera_preview_backend_surface_is_get_only(client: TestClient) -> None:
    camera_routes = [
        route
        for route in workbench.router.routes
        if getattr(route, "path", "") in {"/workbench/camera", CAMERA_PREVIEW_ASSET_PATH}
    ]

    assert len(camera_routes) == 2
    assert all(getattr(route, "methods", set()) == {"GET"} for route in camera_routes)
    assert client.post("/workbench/camera").status_code == 405
    assert client.post(CAMERA_PREVIEW_ASSET_PATH).status_code == 405
    assert not any(
        any(method in {"POST", "PUT", "PATCH", "DELETE"} for method in route.methods or set())
        and (
            route.path.startswith("/workbench/camera")
            or route.path.startswith("/api/camera")
            or route.path.startswith("/camera")
        )
        for route in workbench.router.routes
        if hasattr(route, "methods") and hasattr(route, "path")
    )


def test_existing_workbench_remains_functional(client: TestClient) -> None:
    response = client.get("/workbench")

    assert response.status_code == 200
    assert "OrbitMind Mission Workbench" in response.text
    assert CAMERA_PREVIEW_ASSET_PATH not in response.text


def test_camera_script_gates_permission_and_enumeration(client: TestClient) -> None:
    script = _camera_script(client)
    start_begin = script.index("  async function startCamera(deviceId) {")
    start_end = script.index("\n  function validatedCaptureDimensions", start_begin)
    start_function = script[start_begin:start_end]
    populate_begin = script.index("  async function populateDeviceChoices() {")
    populate_end = script.index("\n  async function startCamera", populate_begin)
    populate_function = script[populate_begin:populate_end]

    assert script.count("navigator.mediaDevices.getUserMedia(constraints)") == 1
    assert "navigator.mediaDevices.getUserMedia(constraints)" in start_function
    assert "navigator.mediaDevices.getUserMedia(" not in script[:start_begin]
    assert script.count("navigator.mediaDevices.enumerateDevices()") == 1
    assert "navigator.mediaDevices.enumerateDevices()" in populate_function
    assert script.index('setState("active"') < script.index("await populateDeviceChoices()")
    assert 'enableButton.addEventListener("click"' in script
    assert 'deviceSelect.addEventListener("change"' in script
    assert "audio: false" in script
    assert "video: deviceId ? { deviceId: { exact: deviceId } } : true" in script
    assert "deviceSelect.value = selectedDeviceId;" in script
    assert "window.isSecureContext" in script


def test_camera_script_has_one_private_stream_and_complete_cleanup(
    client: TestClient,
) -> None:
    script = _camera_script(client)

    assert "let activeStream = null;" in script
    assert "window.activeStream" not in script
    assert "window.stream" not in script
    assert "stream.getTracks().forEach" in script
    assert "track.stop();" in script
    assert "track.removeEventListener" in script
    assert "video.pause();" in script
    assert "video.srcObject = null;" in script
    assert 'window.addEventListener("pagehide"' in script
    assert 'track.addEventListener("ended"' in script
    assert 'fail("camera_disconnected")' in script
    switch_begin = script.index("  async function switchCamera(deviceId) {")
    switch_end = script.index("\n  async function retakeFrame", switch_begin)
    switch_function = script[switch_begin:switch_end]
    assert "clearPreview(false);" in switch_function
    assert switch_function.index("clearPreview(false);") < switch_function.index(
        "await startCamera(deviceId);"
    )
    assert 'stopButton.addEventListener("click"' in script


def test_camera_script_uses_only_sanitized_failure_codes(client: TestClient) -> None:
    script = _camera_script(client)

    for code in (
        "camera_not_supported",
        "camera_permission_denied",
        "camera_not_found",
        "camera_in_use",
        "camera_disconnected",
        "camera_start_failed",
    ):
        assert code in script
    for raw_detail in (
        "error.message",
        "error.stack",
        "String(error)",
        "console.log",
        "console.error",
        "device.deviceId +",
        "option.textContent = device.deviceId",
    ):
        assert raw_detail not in script
    assert ".slice(0, 128)" in script
    assert "[\\u0000-\\u001f\\u007f-\\u009f]" in script


def test_camera_script_contains_no_network_recording_storage_or_semantic_api(
    client: TestClient,
) -> None:
    script = _camera_script(client)
    forbidden = (
        "toDataURL",
        "File",
        "FileReader",
        "FormData",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "RTCPeerConnection",
        "MediaRecorder",
        "getDisplayMedia",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "caches.",
        "serviceWorker",
        "clipboard",
        "geolocation",
        "audio: true",
        "microphone",
        "agent",
        "model",
        "download",
        "ocr",
        "face detection",
        "object detection",
    )

    for token in forbidden:
        assert token not in script


def test_camera_script_has_bounded_one_frame_capture_contract(client: TestClient) -> None:
    script = _camera_script(client)
    capture_begin = script.index("  async function captureFrame() {")
    capture_end = script.index("\n  async function switchCamera", capture_begin)
    capture_function = script[capture_begin:capture_end]

    assert script.count('document.createElement("canvas")') == 1
    assert 'document.createElement("canvas")' in capture_function
    assert script.count("context.drawImage(") == 1
    assert script.count("canvas.toBlob(") == 1
    assert "toDataURL" not in script
    assert "FileReader" not in script
    assert 'Object.freeze(["image/jpeg", "image/png"])' in script
    assert "const JPEG_QUALITY = 0.90;" in script
    assert 'mediaType === "image/jpeg" ? JPEG_QUALITY : undefined' in script
    assert "const MAX_CAPTURE_WIDTH = 1920;" in script
    assert "const MAX_CAPTURE_HEIGHT = 1080;" in script
    assert "const MAX_CAPTURE_BYTES = 5000000;" in script
    assert (
        "Math.min(1, MAX_CAPTURE_WIDTH / sourceWidth, MAX_CAPTURE_HEIGHT / sourceHeight)" in script
    )
    assert "Math.floor(sourceWidth * scale)" in script
    assert "Math.floor(sourceHeight * scale)" in script
    assert "video.videoWidth" in script
    assert "video.videoHeight" in script
    assert "Number.isInteger(sourceWidth)" in script
    assert "Number.isInteger(sourceHeight)" in script
    assert 'captureButton.addEventListener("click"' in script
    assert script.count("void captureFrame();") == 1
    assert "requestAnimationFrame" not in script
    assert "setInterval" not in script


def test_camera_script_owns_one_blob_and_one_object_url(client: TestClient) -> None:
    script = _camera_script(client)

    assert script.count("let capturedBlob = null;") == 1
    assert script.count('let capturedObjectUrl = "";') == 1
    assert "window.capturedBlob" not in script
    assert "window.capturedObjectUrl" not in script
    assert script.count("URL.createObjectURL(blob)") == 1
    assert "capturedImage.src = capturedObjectUrl;" in script
    assert "URL.revokeObjectURL(objectUrl);" in script
    assert 'capturedImage.removeAttribute("src");' in script
    assert "capturedBlob = null;" in script
    assert 'capturedObjectUrl = "";' in script
    assert "canvas.width = 0;" in script
    assert "canvas.height = 0;" in script
    assert "context.clearRect(0, 0, canvas.width, canvas.height);" in script


def test_camera_script_capture_success_and_failure_release_camera(client: TestClient) -> None:
    script = _camera_script(client)
    capture_begin = script.index("  async function captureFrame() {")
    capture_end = script.index("\n  async function switchCamera", capture_begin)
    capture_function = script[capture_begin:capture_end]
    fail_begin = script.index("  function fail(code) {")
    fail_end = script.index("\n  function stopCamera", fail_begin)
    fail_function = script[fail_begin:fail_end]

    assert capture_function.index(
        "showCapturedFrame(blob, newObjectUrl, dimensions);"
    ) < capture_function.index("clearPreview(false);")
    assert capture_function.index("clearPreview(false);") < capture_function.index(
        'setState(\n        "captured"'
    )
    assert "clearPreview(true);" in fail_function
    assert "clearCapturedFrame();" in fail_function
    assert 'throw captureError("image_dimensions_invalid")' in script
    assert 'throw captureError("capture_failed")' in capture_function
    assert 'throw captureError("image_type_invalid")' in capture_function
    assert 'throw captureError("image_too_large")' in capture_function
    assert "blob.type !== mediaType" in capture_function
    assert "fail(captureErrorCode(error));" in capture_function


def test_camera_script_retake_discard_and_pagehide_are_explicit_and_ephemeral(
    client: TestClient,
) -> None:
    script = _camera_script(client)
    retake_begin = script.index("  async function retakeFrame() {")
    retake_end = script.index("\n  function discardFrame", retake_begin)
    retake_function = script[retake_begin:retake_end]
    discard_begin = retake_end
    discard_end = script.index("\n  function teardown", discard_begin)
    discard_function = script[discard_begin:discard_end]
    teardown_begin = discard_end
    teardown_end = script.index("\n  enableButton.addEventListener", teardown_begin)
    teardown_function = script[teardown_begin:teardown_end]

    assert retake_function.index("clearCapturedFrame();") < retake_function.index(
        "await startCamera(deviceId);"
    )
    assert "startCamera" not in discard_function
    assert "clearCapturedFrame();" in discard_function
    assert "clearPreview(true);" in discard_function
    assert "clearCapturedFrame();" in teardown_function
    assert "clearPreview(true);" in teardown_function
    assert 'window.addEventListener("pagehide"' in script
    assert 'retakeButton.addEventListener("click"' in script
    assert 'discardButton.addEventListener("click"' in script
