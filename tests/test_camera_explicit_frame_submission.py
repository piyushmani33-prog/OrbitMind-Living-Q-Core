"""Static browser-contract coverage for explicit ephemeral frame submission."""

from __future__ import annotations

from importlib import resources

from fastapi.testclient import TestClient

from orbitmind.api.app import CONTENT_SECURITY_POLICY
from orbitmind.api.routers.workbench import CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
from orbitmind.camera.csrf import (
    CAMERA_CSRF_META_NAME,
    CAMERA_CSRF_NEXT_HEADER,
    CAMERA_CSRF_REQUEST_HEADER,
)
from orbitmind.camera.service import CAMERA_MEDIA_CAPABILITY_HEADER


def _script() -> str:
    return (
        resources.files("orbitmind.api.assets")
        .joinpath("camera_preview.js")
        .read_text(encoding="utf-8")
    )


def _function(script: str, signature: str, next_signature: str) -> str:
    start = script.index(signature)
    end = script.index(next_signature, start)
    return script[start:end]


def test_camera_page_renders_one_private_csrf_meta_and_explicit_session_controls(
    client: TestClient,
) -> None:
    response = client.get("/workbench/camera")
    body = response.text

    assert response.status_code == 200
    assert body.count(f'<meta name="{CAMERA_CSRF_META_NAME}" ') == 1
    assert 'id="camera-create-session" type="button" disabled' in body
    assert 'id="camera-server-discard" type="button" hidden' in body
    assert "submission occurs only after" in body.casefold()
    assert "expires after 15 minutes" in body
    assert "not analyzed in" in body
    assert "inert temporary proposal only" in body
    for forbidden in (
        "Analyze",
        "Describe",
        "Save permanently",
        "Download",
        "Share",
        'type="file"',
    ):
        assert forbidden not in body


def test_camera_page_csp_allows_only_same_origin_camera_api_connections(client: TestClient) -> None:
    camera = client.get("/workbench/camera")

    assert camera.headers["content-security-policy"] == CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
    assert "connect-src 'self'" in CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
    assert "default-src 'none'" in CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
    assert "connect-src *" not in CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
    assert "wss:" not in CAMERA_PREVIEW_CONTENT_SECURITY_POLICY
    assert client.get("/workbench").headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert "connect-src 'none'" in CONTENT_SECURITY_POLICY


def test_camera_script_uses_one_private_token_and_exact_header_authorities() -> None:
    script = _script()

    assert f'const CSRF_META_NAME = "{CAMERA_CSRF_META_NAME}";' in script
    assert f'const CSRF_REQUEST_HEADER = "{CAMERA_CSRF_REQUEST_HEADER}";' in script
    assert f'const CSRF_NEXT_HEADER = "{CAMERA_CSRF_NEXT_HEADER}";' in script
    assert f'const CAPABILITY_HEADER = "{CAMERA_MEDIA_CAPABILITY_HEADER}";' in script
    assert "document.querySelectorAll('meta[name=\"' + CSRF_META_NAME + '\"]')" in script
    assert "metas.length !== 1" in script
    assert 'meta.setAttribute("content", "");' in script
    assert "meta.remove()" in script
    assert script.count('let csrfToken = "";') == 1
    assert "window.csrfToken" not in script
    assert "localStorage" not in script
    assert "sessionStorage" not in script
    assert "indexedDB" not in script
    assert "document.cookie" not in script
    assert "X-OrbitMind-CSRF-Next" not in script


def test_camera_script_posts_only_the_captured_blob_to_the_approved_endpoint() -> None:
    script = _script()
    submit = _function(
        script,
        "  async function createTemporarySession() {",
        "\n  async function discardTemporaryServerFrame()",
    )

    assert 'const SESSION_ENDPOINT = "/workbench/camera/api/sessions";' in script
    assert 'method: "POST"' in submit
    assert "body: capturedBlob" in submit
    assert '"Content-Type": capturedBlob.type' in submit
    assert "[CSRF_REQUEST_HEADER]: csrfToken" in submit
    assert 'credentials: "same-origin"' in submit
    assert 'cache: "no-store"' in submit
    assert 'redirect: "error"' in submit
    assert "FormData" not in script
    assert "XMLHttpRequest" not in script
    assert "toDataURL" not in script
    assert "FileReader" not in script
    assert "Content-Length" not in script
    assert '"Host"' not in submit
    assert '"Origin"' not in submit
    assert "fetch(SESSION_ENDPOINT" in submit
    assert "fetch(" not in script[: script.index("  async function createTemporarySession() {")]


def test_camera_script_strictly_rotates_authority_and_validates_post_success() -> None:
    script = _script()
    submit = _function(
        script,
        "  async function createTemporarySession() {",
        "\n  async function discardTemporaryServerFrame()",
    )

    assert "const OPAQUE_TOKEN_PATTERN = /^[A-Za-z0-9_-]{43}$/;" in script
    assert "function rotateCsrfAuthority(response)" in script
    assert "response.headers.get(CSRF_NEXT_HEADER)" in script
    assert 'csrfToken = "";' in script
    assert "function isApprovedSessionResponse(body)" in script
    assert "body.contract_version !== 1" in script
    assert 'body.state !== "frame_captured_ephemeral"' in script
    assert 'body.retention_status !== "ephemeral"' in script
    assert "body.width > MAX_CAPTURE_WIDTH" in script
    assert "body.height > MAX_CAPTURE_HEIGHT" in script
    assert "body.encoded_size > MAX_CAPTURE_BYTES" in script
    assert "CHECKSUM_PATTERN" in script
    assert "Date.parse(body.expires_at) <= Date.parse(body.created_at)" in script
    assert "privateSessionId = body.session_id;" in submit
    assert "privateSessionCapability = body.session_capability;" in submit
    assert "clearCapturedFrame();" in submit
    assert "enterAuthorityStale(" in submit
    assert "retry" not in submit.casefold()


def test_camera_script_keeps_session_capability_private_and_discards_explicitly() -> None:
    script = _script()
    discard = _function(
        script,
        "  async function discardTemporaryServerFrame() {",
        "\n  async function switchCamera",
    )

    assert script.count('let privateSessionId = "";') == 1
    assert script.count('let privateSessionCapability = "";') == 1
    assert "window.privateSessionId" not in script
    assert "window.privateSessionCapability" not in script
    assert "serverSessionPanel.hidden" in script
    assert "renderServerMetadata(authoritativeMetadata);" in script
    assert 'method: "DELETE"' in discard
    assert "encodeURIComponent(sessionId)" in discard
    assert "[CSRF_REQUEST_HEADER]: csrfToken" in discard
    assert "[CAPABILITY_HEADER]: capability" in discard
    assert "body:" not in discard
    assert "response.status === 204" in discard
    assert 'responseBody !== ""' in discard
    assert "clearServerSession();" in discard
    assert "camera_session_not_found" in discard
    assert "deletion_failed" in discard
    assert 'fetch(SESSION_ENDPOINT + "/"' in discard
    assert "GET" not in script
    assert "poll" not in script.casefold()


def test_camera_script_has_one_modifying_lock_and_navigation_fail_closed_cleanup() -> None:
    script = _script()

    assert script.count("let modifyingRequestInFlight = false;") == 1
    assert "modifyingRequestInFlight ||" in script
    assert "modifyingRequestInFlight = true;" in script
    assert "modifyingRequestInFlight = false;" in script
    assert 'window.addEventListener("pagehide"' in script
    assert "teardownForNavigation();" in script
    assert "clearServerSession();" in script
    assert "clearCsrfAuthority();" in script
    assert 'window.addEventListener("pageshow"' in script
    assert "event.persisted === true" in script
    assert "Reload required before camera submission can continue." in script
    assert "sendBeacon" not in script
    assert "WebSocket" not in script
    assert "EventSource" not in script
    assert "RTCPeerConnection" not in script


def test_camera_script_creates_one_explicit_inert_proposal_with_strict_response_checks() -> None:
    script = _script()
    proposal = _function(
        script,
        "  async function createProposal() {",
        "\n  async function discardTemporaryServerFrame()",
    )

    assert 'const PROPOSAL_ENDPOINT_SUFFIX = "/proposal";' in script
    assert "const MAX_PROPOSAL_CONTEXT_CODEPOINTS = 500;" in script
    assert "const PROPOSAL_GOALS = Object.freeze([" in script
    assert '"visual_reference"' in script
    assert '"documentation"' in script
    assert '"transformation_request"' in script
    assert '"explanation_request"' in script
    assert '"other"' in script
    assert "function normalizedProposalContext(value)" in script
    assert '.normalize("NFC")' in script
    assert "Array.from(normalized).length > MAX_PROPOSAL_CONTEXT_CODEPOINTS" in script
    assert "function isApprovedProposalResponse(body, goal, userContext)" in script
    assert 'body.state === "proposal_only"' in script
    assert 'body.execution_status === "not_authorized"' in script
    assert 'body.analysis_status === "not_performed"' in script
    assert "body.human_approval_required === true" in script
    assert "body.content_checksum === authoritativeMetadata.content_checksum" in script
    assert "body.expires_at === authoritativeMetadata.expires_at" in script
    assert 'method: "POST"' in proposal
    assert "encodeURIComponent(sessionId) + PROPOSAL_ENDPOINT_SUFFIX" in proposal
    assert '"Content-Type": "application/json"' in proposal
    assert "[CSRF_REQUEST_HEADER]: csrfToken" in proposal
    assert "[CAPABILITY_HEADER]: capability" in proposal
    assert "body: JSON.stringify({ goal: goal, user_context: userContext })" in proposal
    assert "capturedBlob" not in proposal
    assert "Blob" not in proposal
    assert proposal.index("rotateCsrfAuthority(response)") < proposal.index(
        "response.status !== 201"
    )
    assert (
        "Proposal result is unknown. Reload the page. The temporary session will expire "
        "automatically." in script
    )
    assert script.count("PROPOSAL_ENDPOINT_SUFFIX") == 2
    assert "innerHTML" not in script
    assert "proposalContextValue.textContent" in script
    assert "privateProposal = body;" in proposal
    assert 'createProposalButton.addEventListener("click"' in script
    assert "setInterval" not in script
    assert "setTimeout" not in script


def test_camera_script_clears_private_proposal_on_parent_discard_and_navigation() -> None:
    script = _script()
    discard = _function(
        script,
        "  async function discardTemporaryServerFrame() {",
        "\n  async function switchCamera",
    )
    teardown = _function(
        script,
        "  function teardownForNavigation() {",
        "\n  enableButton.addEventListener",
    )

    assert "function clearProposal()" in script
    assert "privateProposal = null;" in script
    assert "clearProposal();" in _function(
        script,
        "  function clearServerSession() {",
        "\n  function clearProposal()",
    )
    assert "clearServerSession();" in discard
    assert "The temporary frame and proposal were discarded." in discard
    assert "clearServerSession();" in teardown
    assert "clearCsrfAuthority();" in teardown
    assert "event.persisted === true" in script
    assert "sendBeacon" not in script
