"""Visual Laboratory Workbench tests: truthful, offline, accessible, read-only."""

from __future__ import annotations

import inspect
import json
import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.presentation import laboratory as laboratory_presentation
from orbitmind.laboratory.catalog import build_catalog_projection, build_default_registry

_PAGE_PATH = "/workbench/laboratory"
_ASSET_PATH = "/assets/laboratory.js"


def _page(client: TestClient) -> str:
    response = client.get(_PAGE_PATH)
    assert response.status_code == 200
    return response.text


def _embedded_payload(page: str) -> dict[str, object]:
    match = re.search(r'<template id="laboratory-data">(.*?)</template>', page, re.S)
    assert match, "the page must embed the registry payload template"
    payload = json.loads(match.group(1))
    assert isinstance(payload, dict)
    return payload


def test_page_loads_with_browser_security_headers(client: TestClient) -> None:
    response = client.get(_PAGE_PATH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    csp = response.headers["content-security-policy"]
    assert "script-src 'self'" in csp
    assert "connect-src 'none'" in csp
    assert response.headers["referrer-policy"] == "same-origin"
    assert response.headers["x-frame-options"] == "DENY"


def test_page_references_no_external_resource(client: TestClient) -> None:
    page = _page(client)
    assert "https://" not in page
    assert "http://" not in page
    assert "//cdn" not in page
    assert "@import" not in page
    assert "@font-face" not in page
    # Every url(...) reference must be a local SVG fragment (gradients), never a fetch.
    for url_reference in re.findall(r"url\((.)", page):
        assert url_reference == "#", "url() may only reference local SVG fragments"
    # The only script is the reviewed same-origin controller asset.
    scripts = re.findall(r"<script[^>]*>", page)
    assert scripts == [f'<script src="{_ASSET_PATH}" defer>']


def test_page_data_matches_the_read_api_exactly(client: TestClient) -> None:
    """The UI consumes the same projection the tested API serves — no second list."""
    page_payload = _embedded_payload(_page(client))
    api_payload = client.get("/api/v1/laboratories").json()
    assert page_payload == api_payload


def test_implemented_and_planned_laboratories_are_visually_distinct(
    client: TestClient,
) -> None:
    page = _page(client)
    assert 'class="lab-node implemented"' in page
    assert page.count('class="lab-node planned"') == 5
    assert page.count("planned — no runtime implementation") >= 6  # tag + 5 panels
    assert 'class="lab-panel implemented"' in page
    assert page.count('class="lab-panel planned"') == 5
    # Planned panels must state non-executability in plain text.
    assert "not registered in the runtime registry" in page.lower()
    assert "not executable" in page.lower()


def test_constellation_legend_uses_text_and_non_color_state_markers(client: TestClient) -> None:
    page = _page(client)

    for marker, label in (
        ("foundation", "Implemented foundation"),
        ("registered", "Registered, non-executing laboratory"),
        ("planned", "Planned architecture-only laboratory"),
        ("approval", "Approval-gated capability"),
    ):
        assert f'class="legend-marker {marker}"' in page
        assert label in page

    assert "registered / non-executing" in page
    assert re.search(r"no Agent Runtime,\s+autonomous development, or execution authority", page)
    assert "non-operational; no runtime implementation" in page
    assert "declared metadata; no automatic permission" in page


def test_mobile_constellation_is_a_readable_projection_of_the_catalog(client: TestClient) -> None:
    page = _page(client)
    projection = build_catalog_projection(build_default_registry())
    mobile = laboratory_presentation._mobile_constellation(projection)

    assert 'class="mobile-constellation"' in page
    assert 'aria-label="Mobile laboratory constellation"' in page
    assert mobile in page
    assert "font-size: 1rem;" in laboratory_presentation.LABORATORY_CSS
    assert laboratory_presentation.LABORATORY_CSS.count("font-size: 0.875rem;") >= 3
    assert ".constellation svg { display: none; }" in laboratory_presentation.LABORATORY_CSS
    assert page.count('class="mobile-constellation-card lab-node implemented"') == 1
    assert page.count('class="mobile-constellation-card lab-node planned"') == 5
    assert "OrbitMind Core" in mobile
    assert "registered / non-executing" in mobile
    assert "planned / non-operational" in mobile
    assert "Approval-gated capability" in mobile
    for manifest in projection.laboratories:
        assert manifest.laboratory_id in mobile
        assert manifest.display_name in mobile
    for planned in projection.planned_laboratories:
        assert planned.laboratory_id in mobile
        assert planned.display_name in mobile


def test_page_declares_a_deterministic_inline_favicon_without_a_route_dependency(
    client: TestClient,
) -> None:
    page = _page(client)
    favicon = re.search(r'<link rel="icon" type="image/svg\+xml" href="([^"]+)">', page)

    assert favicon is not None
    assert favicon.group(1).startswith("data:image/svg+xml,")
    assert "/favicon.ico" not in page
    assert "http://" not in favicon.group(1)
    assert "https://" not in favicon.group(1)
    assert "document.createElement" not in page
    assert unescape(favicon.group(1)) == laboratory_presentation.LABORATORY_FAVICON_DATA_URI


def test_svg_attribute_values_are_quote_aware_while_text_nodes_remain_text_escaped() -> None:
    projection = build_catalog_projection(build_default_registry())
    manifest = projection.laboratories[0].model_copy(
        update={"display_name": 'Development "Lab" & <Review>'}
    )

    node = laboratory_presentation._constellation_node_implemented(manifest)
    accessible_name = re.search(r'aria-label="([^"]+)"', node)

    assert accessible_name is not None
    assert "&quot;" in accessible_name.group(1)
    assert "&amp;" in accessible_name.group(1)
    assert "&lt;Review&gt;" in accessible_name.group(1)
    assert "<Review>" not in accessible_name.group(1)
    assert unescape(accessible_name.group(1)) == (
        'Development "Lab" & <Review> — implemented catalog foundation; '
        "registered / non-executing. View details."
    )
    assert ">Development &quot;Lab&quot; &amp; &lt;Review&gt;</text>" in node
    assert 'aria-label="Development "Lab"' not in node


def test_offline_boundary_uses_named_immutable_roles_without_order_dependence() -> None:
    projection = build_catalog_projection(build_default_registry())
    source = inspect.getsource(laboratory_presentation._offline_boundary)
    content = laboratory_presentation._offline_boundary_content(
        projection.offline_boundary_statements
    )
    reordered_projection = projection.model_copy(
        update={
            "offline_boundary_statements": tuple(reversed(projection.offline_boundary_statements))
        }
    )

    assert "statements[" not in source
    assert laboratory_presentation._OfflineBoundaryContent.__dataclass_params__.frozen
    assert content.offline_local_work.startswith("Deterministic local work")
    assert content.connected_window.startswith("Network sources")
    assert content.credential_isolation.startswith("Credentials are never stored")
    assert content.external_call_receipts.startswith("When a connected window")
    assert laboratory_presentation._offline_boundary(reordered_projection) == (
        laboratory_presentation._offline_boundary(projection)
    )
    with pytest.raises(ValueError, match="external_call_receipts"):
        laboratory_presentation._offline_boundary_content(
            projection.offline_boundary_statements[:-1]
        )


def test_no_operational_overclaim_labels(client: TestClient) -> None:
    page_lower = _page(client).lower()
    for forbidden in (
        ">online<",
        ">running<",
        ">operational<",
        ">autonomous<",
        ">connected<",
        ">intelligent<",
        "agent is active",
        "live telemetry feed",
        "system health",
    ):
        assert forbidden not in page_lower, forbidden


def test_capability_permission_separation_is_visible(client: TestClient) -> None:
    page = _page(client)
    assert "Declaring a capability does not grant permission" in page
    assert "Capability and authority matrix" in page
    assert page.count("none connected") >= 8  # tool + adapter columns for 4 capabilities
    assert "Execution authority" in page


def test_approval_gates_and_safety_plane_are_present(client: TestClient) -> None:
    page = _page(client)
    assert "Safety and governance plane" in page
    assert page.count("human approval required") >= 16
    for gate in (
        "Network access",
        "External ai",
        "Repository write",
        "Quantum hardware",
        "Physical hardware",
        "Camera or microphone",
        "Merge",
        "Deployment",
        "Publishing",
        "Knowledge upgrade",
        "Runtime upgrade",
    ):
        assert gate in page, gate


def test_mission_flow_marks_existing_versus_future_stages(client: TestClient) -> None:
    page = _page(client)
    assert "Governed mission flow" in page
    assert page.count('class="flow-stage exists"') == 9
    assert page.count('class="flow-stage future"') == 2
    assert "Capability Request" in page
    assert "Replay or Re-evaluation" in page


def test_evidence_and_replay_view_is_architecture_labelled(client: TestClient) -> None:
    page = _page(client)
    assert "Evidence and replay" in page
    assert "Architecture projection" in page
    assert "No mission evidence is fabricated" in page
    assert "never conflated" in page
    for link in ("Checksum", "Provenance", "Approvals", "Replay classification"):
        assert link in page, link


def test_offline_connected_boundary_is_present(client: TestClient) -> None:
    page = _page(client)
    assert "Offline / connected boundary" in page
    assert "Offline by default" in page
    assert "Connected only by explicit permission" in page
    assert "disabled by default" in page.lower()


def test_no_execution_controls_or_forms(client: TestClient) -> None:
    page = _page(client)
    assert "<form" not in page
    assert "<input" not in page
    # The only buttons are the read-only laboratory selection strip.
    buttons = re.findall(r"<button[^>]*>", page)
    assert buttons, "the selection strip must render buttons"
    for button in buttons:
        assert 'type="button"' in button
        assert "lab-select" in button


def test_keyboard_operable_selection_and_focus_targets(client: TestClient) -> None:
    page = _page(client)
    assert page.count('aria-pressed="false"') == 6  # six selection buttons
    assert 'role="group" aria-label="Select a laboratory"' in page
    assert page.count('tabindex="-1"') == 6  # six focusable panels
    assert 'aria-live="polite"' in page
    # Constellation nodes are native links with accessible names.
    for match in re.findall(r'<a href="#lab-panel-[^"]+"', page):
        assert match.startswith('<a href="#lab-panel-')
    assert page.count("aria-label=") >= 8


def test_accessibility_landmarks_and_svg_labels(client: TestClient) -> None:
    page = _page(client)
    assert "<main>" in page
    assert page.count("<section") >= 6
    assert 'aria-labelledby="constellation-svg-title constellation-svg-desc"' in page
    assert "<title id=" in page
    assert "<desc id=" in page
    assert "prefers-reduced-motion" in page  # reduced-motion CSS support
    assert '<html lang="en">' in page
    assert '<meta name="viewport"' in page


def test_no_browser_storage_or_injection_paths_in_controller(client: TestClient) -> None:
    asset = client.get(_ASSET_PATH)
    assert asset.status_code == 200
    assert asset.headers["content-type"].startswith("application/javascript")
    script = asset.text
    for forbidden in (
        "innerHTML",
        "outerHTML",
        "document.write",
        "insertAdjacentHTML",
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "document.cookie",
        "fetch(",
        "XMLHttpRequest",
        "WebSocket",
        "eval(",
        "new Function",
        "import(",
    ):
        assert forbidden not in script, forbidden
    assert '"use strict"' in script
    assert "prefers-reduced-motion" in script


def test_controller_validates_schema_and_fails_safe(client: TestClient) -> None:
    script = client.get(_ASSET_PATH).text
    assert 'schema_version !== "laboratory-catalog-v1"' in script
    # Truthfulness guard: DOM/payload mismatch leaves the un-filtered view.
    assert "payloadIds" in script and "panelIds" in script


def test_page_is_deterministic_across_requests(client: TestClient) -> None:
    assert _page(client) == _page(client)
