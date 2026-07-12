"""Browser security headers and replay asset isolation coverage."""

from __future__ import annotations

import html
import json
import re
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.responses import Response

from orbitmind.api.app import CONTENT_SECURITY_POLICY, create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.presentation.trajectory_replay import script_safe_json
from orbitmind.api.routers import workbench
from orbitmind.sources.registry import SourceRegistry

EXPECTED_CSP = {
    "default-src": ("'none'",),
    "script-src": ("'self'",),
    "style-src": ("'unsafe-inline'",),
    "img-src": ("'self'", "data:"),
    "font-src": ("'none'",),
    "connect-src": ("'none'",),
    "object-src": ("'none'",),
    "base-uri": ("'none'",),
    "frame-ancestors": ("'none'",),
    "form-action": ("'self'",),
    "worker-src": ("'none'",),
    "media-src": ("'none'",),
    "manifest-src": ("'none'",),
}


def _iss_tle() -> tuple[str, str]:
    return SourceRegistry().get_tle("ISS")


def _catalog_form(**updates: str) -> dict[str, str]:
    form = {
        "source_mode": "catalog",
        "catalog_sample_id": "iss",
        "custom_label": "",
        "tle_line1": "",
        "tle_line2": "",
        "observer_latitude_deg": "0",
        "observer_longitude_deg": "0",
        "observer_altitude_metres": "0",
        "start_time_utc": "2019-12-09T17:00:00Z",
        "duration_hours": "1",
        "minimum_elevation_deg": "0",
    }
    form.update(updates)
    return form


def _custom_form(**updates: str) -> dict[str, str]:
    line1, line2 = _iss_tle()
    form = _catalog_form(
        source_mode="custom",
        catalog_sample_id="",
        custom_label="Review ISS",
        tle_line1=line1,
        tle_line2=line2,
    )
    form.update(updates)
    return form


def _parse_csp(value: str) -> dict[str, tuple[str, ...]]:
    directives: dict[str, tuple[str, ...]] = {}
    for raw_directive in value.split(";"):
        parts = raw_directive.strip().split()
        if not parts:
            continue
        directives[parts[0]] = tuple(parts[1:])
    return directives


def _payload(body: str) -> dict[str, Any]:
    match = re.search(
        r'<template id="trajectory-replay-data">(.*?)</template>',
        body,
        re.S,
    )
    assert match is not None
    return json.loads(html.unescape(match.group(1)))


def _extract_mission_id(body: str) -> str:
    match = re.search(r"<dt>mission_id</dt><dd>([0-9a-f-]+)</dd>", body)
    assert match is not None
    return match.group(1)


@pytest.mark.parametrize(
    "method,path,data,expected_status",
    [
        ("GET", "/workbench", None, 200),
        ("POST", "/workbench/run", _catalog_form(), 200),
        ("POST", "/workbench/run", _catalog_form(catalog_sample_id="unknown"), 422),
        ("POST", "/workbench/replay", _catalog_form(), 200),
        ("POST", "/workbench/replay", _catalog_form(catalog_sample_id="unknown"), 422),
        ("GET", "/review", None, 200),
    ],
)
def test_html_responses_receive_browser_security_headers(
    client: TestClient,
    method: str,
    path: str,
    data: dict[str, str] | None,
    expected_status: int,
) -> None:
    response = client.request(method, path, data=data)

    assert response.status_code == expected_status
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "geolocation=()" in response.headers["permissions-policy"]


def test_csp_directives_are_restrictive_and_do_not_allow_executable_inline_sources() -> None:
    directives = _parse_csp(CONTENT_SECURITY_POLICY)

    assert directives == EXPECTED_CSP
    script_values = directives["script-src"]
    assert "'unsafe-inline'" not in script_values
    assert "'unsafe-eval'" not in CONTENT_SECURITY_POLICY
    assert "*" not in script_values
    assert "data:" not in script_values
    assert "blob:" not in script_values
    assert all("://" not in value for values in directives.values() for value in values)


def test_replay_controller_asset_is_exact_allowlisted_resource(client: TestClient) -> None:
    first = client.get("/assets/trajectory-replay.js")
    second = client.get("/assets/trajectory-replay.js")
    unknown = client.get("/assets/unknown.js")
    traversal = client.get("/assets/..%2Frouters%2Fworkbench.py")
    directory = client.get("/assets/")
    packaged = resources.files("orbitmind.api.assets").joinpath("trajectory_replay.js")

    assert first.status_code == 200
    assert first.headers["content-type"] == "application/javascript; charset=utf-8"
    assert first.headers["x-content-type-options"] == "nosniff"
    assert first.headers["cache-control"] == "no-store"
    assert "content-security-policy" not in first.headers
    assert first.content == second.content
    assert "sourceMappingURL" not in first.text
    assert "C:\\" not in first.text
    assert "/home/" not in first.text
    assert _iss_tle()[0] not in first.text
    assert "Authorization: Bearer" not in first.text
    assert "sk-" not in first.text
    assert unknown.status_code == 404
    assert traversal.status_code == 404
    assert directory.status_code in {404, 405}
    assert packaged.is_file()
    assert packaged.read_bytes() == first.content


def test_missing_packaged_asset_failure_is_sanitized(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_package(_package: str) -> object:
        raise FileNotFoundError("E:/quantum-project/src/orbitmind/api/assets/secret.js")

    monkeypatch.setattr(workbench.resources, "files", missing_package)

    response = client.get("/assets/trajectory-replay.js")

    assert response.status_code == 500
    assert response.text == "Replay controller asset unavailable."
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "quantum-project" not in response.text
    assert "Traceback" not in response.text


def test_replay_html_uses_inert_payload_and_same_origin_controller(client: TestClient) -> None:
    response = client.post("/workbench/replay", data=_catalog_form())

    assert response.status_code == 200
    body = response.text
    assert '<template id="trajectory-replay-data">' in body
    assert body.count('<script src="/assets/trajectory-replay.js" defer></script>') == 1
    assert "<script>" not in body
    assert 'type="application/json"' not in body
    assert not re.search(r"\son[a-z]+\s*=", body, flags=re.I)
    assert "javascript:" not in body.lower()
    assert "data:text/javascript" not in body.lower()
    assert "blob:" not in body.lower()
    assert _iss_tle()[0] not in body
    assert "Play" in body
    assert 'aria-pressed="false"' in body
    assert "playback controls require local JavaScript" in " ".join(body.split())


def test_inert_payload_is_parseable_and_script_escape_safe(client: TestClient) -> None:
    probe_payload = script_safe_json(
        {
            "label": "</template><script>alert(1)</script>",
            "html": "<img src=x onerror=alert(1)>",
            "amp": "A&B",
            "line_sep": "\u2028",
            "para_sep": "\u2029",
        }
    )
    response = client.post("/workbench/replay", data=_catalog_form())
    body = response.text
    payload = _payload(body)

    assert json.loads(probe_payload)["label"] == "</template><script>alert(1)</script>"
    assert "</template>" not in probe_payload.lower()
    assert "<script" not in probe_payload.lower()
    assert "<img" not in probe_payload.lower()
    assert "&" not in probe_payload
    assert "\u2028" not in probe_payload
    assert "\u2029" not in probe_payload
    assert payload["sample_count"] == len(payload["samples"])
    flattened = [index for segment in payload["segments"] for index in segment]
    assert flattened == list(range(payload["sample_count"]))
    assert _iss_tle()[0] not in body
    assert "C:\\private" not in body
    assert "Authorization: Bearer" not in body


def test_replay_controller_javascript_boundary(client: TestClient) -> None:
    script = client.get("/assets/trajectory-replay.js").text
    forbidden_tokens = (
        "eval",
        "new Function",
        "document.write",
        "innerHTML",
        "insertAdjacentHTML",
        "fetch",
        "XMLHttpRequest",
        "WebSocket",
        "EventSource",
        "sendBeacon",
        "geolocation",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "SGP4",
        "Kepler",
        "Julian date",
        "GMST",
        "TEME",
        "ECEF",
        "WGS84 conversion",
        "interpolate",
    )
    for token in forbidden_tokens:
        assert token not in script


def test_replay_controller_guards_required_dom_before_registering_listeners(
    client: TestClient,
) -> None:
    script = client.get("/assets/trajectory-replay.js").text
    guard_start = script.index("  if (\n    !dataNode")
    guard_end = script.index("\n  let payload;", guard_start)
    guard = script[guard_start:guard_end]

    for element in (
        "dataNode",
        "marker",
        "slider",
        "playButton",
        "previousButton",
        "nextButton",
        "speedSelect",
        "errorBox",
    ):
        assert f"!{element}" in guard
    assert "return;" in guard
    assert guard_start > script.index('document.getElementById("trajectory-replay-error")')
    assert guard_end < script.index("function fail()")
    for listener in (
        'playButton.addEventListener("click"',
        'previousButton.addEventListener("click"',
        'nextButton.addEventListener("click"',
        'slider.addEventListener("input"',
        'speedSelect.addEventListener("change"',
    ):
        assert script.index(listener) > guard_end

    validation_start = script.index("  try {")
    enable_controls = script.index("  setControlsDisabled(false);")
    assert script.index("payload.sample_count < 2", validation_start) < enable_controls
    assert script.index("fail();", validation_start) < enable_controls
    assert script.index('speedSelect.addEventListener("change"') < enable_controls
    assert "setControlsDisabled(true);" in script

    replay = client.post("/workbench/replay", data=_catalog_form())
    assert replay.status_code == 200
    for control_id in (
        "replay-play",
        "replay-prev",
        "replay-slider",
        "replay-next",
        "replay-speed",
    ):
        assert re.search(rf'id="{control_id}"[^>]*\bdisabled\b', replay.text)


def test_html_content_type_with_surrounding_whitespace_receives_security_headers(
    container: AppContainer,
) -> None:
    app = create_app(container)

    def spaced_html() -> Response:
        return Response(
            content="<p>spaced HTML media type</p>",
            headers={"content-type": "  Text/HTML  ; charset=utf-8"},
        )

    app.add_api_route("/_test/spaced-html", spaced_html, methods=["GET"])
    with TestClient(app) as test_client:
        response = test_client.get("/_test/spaced-html")

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert "geolocation=()" in response.headers["permissions-policy"]


def test_json_and_file_responses_do_not_receive_html_csp(client: TestClient) -> None:
    json_response = client.get("/health")
    sample_response = client.post("/review/run")
    mission_id = _extract_mission_id(sample_response.text)
    artifact_response = client.get(f"/review/artifacts/{mission_id}/static_report.md")

    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert "content-security-policy" not in json_response.headers
    assert artifact_response.status_code == 200
    assert "OrbitMind Offline Sample Static Report" in artifact_response.text
    assert "content-security-policy" not in artifact_response.headers


def test_pyproject_package_data_includes_replay_asset() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["tool"]["setuptools"]["package-data"]["orbitmind"] == ["api/assets/*.js"]
