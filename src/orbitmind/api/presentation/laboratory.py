"""Presentation builders for the Laboratory Workbench.

Server-side, deterministic HTML/SVG projection of the laboratory catalog. All
displayed facts come from the ``LaboratoryCatalogProjection`` (registry data +
clearly-labelled static architectural metadata). No telemetry, no fake
activity, no external assets: system font stack, inline CSS, inline SVG, and
one reviewed same-origin controller script.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape

from orbitmind.api.presentation.trajectory_replay import script_safe_json
from orbitmind.laboratory.capabilities import CapabilityDeclaration
from orbitmind.laboratory.catalog import (
    LaboratoryCatalogProjection,
    PlannedLaboratoryProjection,
)
from orbitmind.laboratory.contracts import LaboratoryManifest

LABORATORY_ASSET_PATH = "/assets/laboratory.js"
LABORATORY_DATA_NODE_ID = "laboratory-data"
LABORATORY_FAVICON_DATA_URI = (
    "data:image/svg+xml,%3Csvg%20xmlns=%22http%3A%2F%2Fwww.w3.org%2F2000%2Fsvg%22"
    "%20viewBox=%220%200%2064%2064%22%3E%3Crect%20width=%2264%22%20height=%2264%22"
    "%20rx=%2212%22%20fill=%22%23060b16%22%2F%3E%3Ccircle%20cx=%2232%22%20cy=%2232%22"
    "%20r=%2220%22%20fill=%22%232f8fb0%22%20stroke=%22%236fd7ea%22%20stroke-width=%224%22"
    "%2F%3E%3Cpath%20d=%22M20%2032h24M32%2020v24%22%20stroke=%22%23e9f1fc%22"
    "%20stroke-width=%224%22%20stroke-linecap=%22round%22%2F%3E%3C%2Fsvg%3E"
)

_SVG_WIDTH = 1200
_SVG_HEIGHT = 640
_CENTER_X = 600.0
_CENTER_Y = 316.0
_INNER_RX, _INNER_RY = 252.0, 148.0
_OUTER_RX, _OUTER_RY = 442.0, 244.0

# Deterministic constellation placement (degrees on the orbit rings). The
# implemented laboratory sits alone on the inner ring; planned laboratories
# share the outer ring. Purely visual, derived from stable identifiers.
_INNER_ANGLES = {"development-laboratory": -28.0}
_OUTER_ANGLES = {
    "research-laboratory": 152.0,
    "quantum-laboratory": 42.0,
    "robotics-laboratory": 212.0,
    "space-laboratory": 90.0,
    "manufacturing-laboratory": -63.0,
}


@dataclass(frozen=True)
class _OfflineBoundaryContent:
    """Named presentation roles for the existing offline-boundary statements."""

    offline_local_work: str
    connected_window: str
    credential_isolation: str
    external_call_receipts: str


@dataclass(frozen=True)
class _ConstellationSemantics:
    """Shared, non-execution semantics for both constellation presentations."""

    implemented_foundation: str
    registered_non_executing: str
    planned_architecture: str
    approval_gated: str


_CONSTELLATION_SEMANTICS = _ConstellationSemantics(
    implemented_foundation="Implemented foundation — merged catalog foundation",
    registered_non_executing=(
        "Registered, non-executing laboratory — no Agent Runtime, autonomous development, "
        "or execution authority"
    ),
    planned_architecture=(
        "Planned architecture-only laboratory — non-operational; no runtime implementation"
    ),
    approval_gated="Approval-gated capability — declared metadata; no automatic permission",
)


def _attribute(value: object) -> str:
    """Escape a value for insertion into a quoted HTML or SVG attribute."""

    return escape(str(value), quote=True)


def _numeric_attribute(value: float) -> str:
    """Format a deterministic SVG coordinate for a quoted attribute."""

    return _attribute(f"{value:.1f}")


def _humanize(token: str) -> str:
    text = token.replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else text


def _node_position(laboratory_id: str) -> tuple[float, float]:
    if laboratory_id in _INNER_ANGLES:
        angle, rx, ry = _INNER_ANGLES[laboratory_id], _INNER_RX, _INNER_RY
    else:
        angle = _OUTER_ANGLES.get(laboratory_id, 0.0)
        rx, ry = _OUTER_RX, _OUTER_RY
    radians = math.radians(angle)
    return _CENTER_X + rx * math.cos(radians), _CENTER_Y - ry * math.sin(radians)


def _starfield() -> str:
    """Deterministic static starfield (seeded LCG; no animation, no randomness)."""
    state = 20260718
    stars: list[str] = []
    for _ in range(96):
        values: list[float] = []
        for _draw in range(3):
            state = (state * 1103515245 + 12345) % 2_147_483_648
            values.append(state / 2_147_483_648)
        x = round(values[0] * _SVG_WIDTH, 1)
        y = round(values[1] * _SVG_HEIGHT, 1)
        r = round(0.5 + values[2] * 1.1, 2)
        opacity = round(0.16 + values[2] * 0.38, 2)
        stars.append(
            f'<circle class="star" cx="{_numeric_attribute(x)}" '
            f'cy="{_numeric_attribute(y)}" r="{_attribute(r)}" '
            f'opacity="{_attribute(opacity)}"/>'
        )
    return "".join(stars)


def build_laboratory_payload_json(projection: LaboratoryCatalogProjection) -> str:
    """Script-safe JSON payload embedded for the reviewed controller script."""
    return script_safe_json(projection.model_dump(mode="json"))


def _registered_non_execution_state(manifest: LaboratoryManifest) -> str:
    """Derive the registered node state from the manifest's current authority facts."""

    if any(
        declaration.grants_permission or declaration.execution_authority.value != "none"
        for declaration in manifest.capabilities
    ):
        raise ValueError("Laboratory manifest cannot be rendered as non-executing")
    return "registered / non-executing"


def _constellation_node_implemented(manifest: LaboratoryManifest) -> str:
    x, y = _node_position(manifest.laboratory_id)
    x_value = _numeric_attribute(x)
    y_value = _numeric_attribute(y)
    label_y = _numeric_attribute(y + 66)
    status_y = _numeric_attribute(y + 86)
    state_y = _numeric_attribute(y + 105)
    label = escape(manifest.display_name)
    status = escape(manifest.implementation_status.value)
    laboratory_id = _attribute(manifest.laboratory_id)
    registration_state = _registered_non_execution_state(manifest)
    accessible_label = _attribute(
        f"{manifest.display_name} — implemented catalog foundation; "
        f"{registration_state}. View details."
    )
    return f"""
    <a href="#lab-panel-{laboratory_id}"
       class="lab-node implemented" data-lab="{laboratory_id}"
       aria-label="{accessible_label}">
      <g>
        <circle class="node-halo" cx="{x_value}" cy="{y_value}" r="46"/>
        <circle class="node-core" cx="{x_value}" cy="{y_value}" r="30"/>
        <text class="node-label" x="{x_value}" y="{label_y}" text-anchor="middle">{label}</text>
        <text class="node-tag" x="{x_value}" y="{status_y}" text-anchor="middle">{status}</text>
        <text class="node-state" x="{x_value}" y="{state_y}"
              text-anchor="middle">{escape(registration_state)}</text>
      </g>
    </a>"""


def _constellation_node_planned(planned: PlannedLaboratoryProjection) -> str:
    x, y = _node_position(planned.laboratory_id)
    x_value = _numeric_attribute(x)
    y_value = _numeric_attribute(y)
    label_y = _numeric_attribute(y + 48)
    status_y = _numeric_attribute(y + 66)
    label = escape(planned.display_name)
    laboratory_id = _attribute(planned.laboratory_id)
    accessible_label = _attribute(
        f"{planned.display_name} — planned architecture-only laboratory; "
        "non-operational; no runtime implementation. View details."
    )
    return f"""
    <a href="#lab-panel-{laboratory_id}"
       class="lab-node planned" data-lab="{laboratory_id}"
       aria-label="{accessible_label}">
      <g>
        <circle class="node-core" cx="{x_value}" cy="{y_value}" r="22"/>
        <text class="node-label" x="{x_value}" y="{label_y}" text-anchor="middle">{label}</text>
        <text class="node-tag" x="{x_value}" y="{status_y}" text-anchor="middle">planned</text>
      </g>
    </a>"""


def _connector(laboratory_id: str, *, planned: bool) -> str:
    x, y = _node_position(laboratory_id)
    css = "link-planned" if planned else "link-implemented"
    return (
        f'<line class="{_attribute(css)}" x1="{_numeric_attribute(_CENTER_X)}" '
        f'y1="{_numeric_attribute(_CENTER_Y)}" x2="{_numeric_attribute(x)}" '
        f'y2="{_numeric_attribute(y)}"/>'
    )


def _mobile_constellation(projection: LaboratoryCatalogProjection) -> str:
    """Render the mobile constellation from the same projection as the desktop SVG."""

    semantics = _CONSTELLATION_SEMANTICS
    implemented = "".join(
        _mobile_constellation_implemented_card(manifest, semantics=semantics)
        for manifest in projection.laboratories
    )
    planned = "".join(
        _mobile_constellation_planned_card(item, semantics=semantics)
        for item in projection.planned_laboratories
    )
    return f"""
    <ol class="mobile-constellation" aria-label="Mobile laboratory constellation">
      <li class="mobile-constellation-card core">
        <span class="mobile-constellation-marker core" aria-hidden="true">O</span>
        <span class="mobile-constellation-copy">
          <strong>OrbitMind Core</strong>
          <span class="mobile-constellation-state">implemented foundation</span>
          <span>{escape(semantics.implemented_foundation)}</span>
        </span>
      </li>
      {implemented}
      {planned}
      <li class="mobile-constellation-card approval">
        <span class="mobile-constellation-marker approval" aria-hidden="true">!</span>
        <span class="mobile-constellation-copy">
          <strong>Approval-gated capability</strong>
          <span class="mobile-constellation-state">declared, never automatic</span>
          <span>{escape(semantics.approval_gated)}</span>
        </span>
      </li>
    </ol>"""


def _mobile_constellation_implemented_card(
    manifest: LaboratoryManifest, *, semantics: _ConstellationSemantics
) -> str:
    registration_state = _registered_non_execution_state(manifest)
    laboratory_id = _attribute(manifest.laboratory_id)
    accessible_label = _attribute(
        f"{manifest.display_name} — {semantics.implemented_foundation}; "
        f"{registration_state}. View details."
    )
    return f"""
      <a class="mobile-constellation-card lab-node implemented"
         href="#lab-panel-{laboratory_id}" data-lab="{laboratory_id}"
         aria-label="{accessible_label}">
        <span class="mobile-constellation-marker foundation" aria-hidden="true"></span>
        <span class="mobile-constellation-copy">
          <strong>{escape(manifest.display_name)}</strong>
          <span class="mobile-constellation-state">{escape(registration_state)}</span>
          <span>{escape(semantics.implemented_foundation)}</span>
        </span>
      </a>"""


def _mobile_constellation_planned_card(
    planned: PlannedLaboratoryProjection, *, semantics: _ConstellationSemantics
) -> str:
    laboratory_id = _attribute(planned.laboratory_id)
    accessible_label = _attribute(
        f"{planned.display_name} — {semantics.planned_architecture}. View details."
    )
    return f"""
      <a class="mobile-constellation-card lab-node planned"
         href="#lab-panel-{laboratory_id}" data-lab="{laboratory_id}"
         aria-label="{accessible_label}">
        <span class="mobile-constellation-marker planned" aria-hidden="true"></span>
        <span class="mobile-constellation-copy">
          <strong>{escape(planned.display_name)}</strong>
          <span class="mobile-constellation-state">planned / non-operational</span>
          <span>{escape(semantics.planned_architecture)}</span>
        </span>
      </a>"""


def _constellation(projection: LaboratoryCatalogProjection) -> str:
    center_x = _numeric_attribute(_CENTER_X)
    center_y = _numeric_attribute(_CENTER_Y)
    inner_rx = _numeric_attribute(_INNER_RX)
    inner_ry = _numeric_attribute(_INNER_RY)
    outer_rx = _numeric_attribute(_OUTER_RX)
    outer_ry = _numeric_attribute(_OUTER_RY)
    core_label_y = _numeric_attribute(_CENTER_Y - 2)
    core_sublabel_y = _numeric_attribute(_CENTER_Y + 16)
    semantics = _CONSTELLATION_SEMANTICS
    connectors = "".join(
        _connector(manifest.laboratory_id, planned=False) for manifest in projection.laboratories
    ) + "".join(
        _connector(planned.laboratory_id, planned=True)
        for planned in projection.planned_laboratories
    )
    nodes = "".join(
        _constellation_node_implemented(manifest) for manifest in projection.laboratories
    ) + "".join(_constellation_node_planned(planned) for planned in projection.planned_laboratories)
    strip_buttons = "".join(
        f'<button type="button" class="lab-select" data-lab="{_attribute(m.laboratory_id)}"'
        f' aria-pressed="false">{escape(m.display_name)}'
        f'<span class="strip-tag ok">foundation</span></button>'
        for m in projection.laboratories
    ) + "".join(
        f'<button type="button" class="lab-select" data-lab="{_attribute(p.laboratory_id)}"'
        f' aria-pressed="false">{escape(p.display_name)}'
        f'<span class="strip-tag warn">planned</span></button>'
        for p in projection.planned_laboratories
    )
    view_box = _attribute(f"0 0 {_SVG_WIDTH} {_SVG_HEIGHT}")
    mobile_constellation = _mobile_constellation(projection)
    return f"""
  <section class="panel constellation" aria-labelledby="constellation-heading">
    <h2 id="constellation-heading">Laboratory constellation</h2>
    <p class="section-note">A map of the OrbitMind Core and its laboratories. Only the
    Development Laboratory is registered (catalog foundation). Dashed nodes are planned
    concepts with <strong>no runtime implementation</strong> — they are not executable.</p>
    <svg viewBox="{view_box}" role="group"
         aria-labelledby="constellation-svg-title constellation-svg-desc">
      <title id="constellation-svg-title">Laboratory constellation map</title>
      <desc id="constellation-svg-desc">OrbitMind Core at the center; the implemented
      Development Laboratory on an inner orbit; five planned laboratories on an outer
      orbit, drawn dashed to show they have no runtime implementation.</desc>
      <defs>
        <radialGradient id="core-gradient" cx="50%" cy="42%" r="65%">
          <stop offset="0%" stop-color="#9be5f2"/>
          <stop offset="55%" stop-color="#2f8fb0"/>
          <stop offset="100%" stop-color="#14425d"/>
        </radialGradient>
        <radialGradient id="dev-gradient" cx="50%" cy="40%" r="70%">
          <stop offset="0%" stop-color="#8ff0d0"/>
          <stop offset="60%" stop-color="#2f9d7c"/>
          <stop offset="100%" stop-color="#14523f"/>
        </radialGradient>
      </defs>
      {_starfield()}
      <ellipse class="orbit" cx="{center_x}" cy="{center_y}"
               rx="{inner_rx}" ry="{inner_ry}"/>
      <ellipse class="orbit" cx="{center_x}" cy="{center_y}"
               rx="{outer_rx}" ry="{outer_ry}"/>
      {connectors}
      <g class="core-node" aria-hidden="true">
        <circle class="core-halo" cx="{center_x}" cy="{center_y}" r="64"/>
        <circle class="core-body" cx="{center_x}" cy="{center_y}" r="44"/>
        <text class="core-label" x="{center_x}" y="{core_label_y}"
              text-anchor="middle">OrbitMind</text>
        <text class="core-sublabel" x="{center_x}" y="{core_sublabel_y}"
              text-anchor="middle">Core</text>
      </g>
      {nodes}
    </svg>
    {mobile_constellation}
    <div class="legend" aria-label="Constellation legend">
      <span class="legend-item"><span class="legend-marker foundation" aria-hidden="true"></span>
        {escape(semantics.implemented_foundation)}</span>
      <span class="legend-item"><span class="legend-marker registered" aria-hidden="true">R</span>
        {escape(semantics.registered_non_executing)}</span>
      <span class="legend-item"><span class="legend-marker planned" aria-hidden="true"></span>
        {escape(semantics.planned_architecture)}</span>
      <span class="legend-item"><span class="legend-marker approval" aria-hidden="true">!</span>
        {escape(semantics.approval_gated)}</span>
    </div>
    <div class="lab-strip" role="group" aria-label="Select a laboratory">{strip_buttons}</div>
    <p class="focus-status" id="lab-focus-status" role="status" aria-live="polite"></p>
  </section>"""


def _chips(values: tuple[str, ...], *, css: str = "chip") -> str:
    return "".join(f'<span class="{css}">{escape(value)}</span>' for value in values)


def _dl(rows: tuple[tuple[str, str], ...]) -> str:
    items = "".join(
        f"<dt>{escape(term)}</dt><dd>{escape(definition)}</dd>" for term, definition in rows
    )
    return f'<dl class="fact-grid">{items}</dl>'


def _capability_chips(capabilities: tuple[CapabilityDeclaration, ...]) -> str:
    return "".join(
        f'<span class="chip cap">{escape(_humanize(declaration.capability.value))}'
        f'<span class="chip-sub">{escape(_humanize(declaration.approval_posture.value))}'
        "</span></span>"
        for declaration in capabilities
    )


def _manifest_panel(manifest: LaboratoryManifest) -> str:
    lab_id = _attribute(manifest.laboratory_id)
    limitations = "".join(f"<li>{escape(statement)}</li>" for statement in manifest.limitations)
    verification = "".join(
        f"<li>{escape(statement)}</li>" for statement in manifest.verification_requirements
    )
    facts = _dl(
        (
            ("Identifier", manifest.laboratory_id),
            ("Laboratory version", manifest.laboratory_version),
            ("Domain", _humanize(manifest.domain.value)),
            ("Implementation status", _humanize(manifest.implementation_status.value)),
            ("Network posture", _humanize(manifest.network_posture.value)),
            ("Hardware posture", _humanize(manifest.hardware_posture.value)),
            ("Persistence posture", _humanize(manifest.persistence_posture.value)),
            ("Replay contract", _humanize(manifest.replay_support.value)),
            ("Deprecation state", _humanize(manifest.deprecation_state.value)),
            (
                "Resource bounds (declared)",
                f"max {manifest.resource_boundaries.max_concurrent_missions} concurrent "
                f"mission(s); max "
                f"{manifest.resource_boundaries.max_mission_wall_clock_seconds} s wall clock",
            ),
            ("Platform baseline", manifest.compatibility.platform_version_baseline),
        )
    )
    return f"""
    <article class="lab-panel implemented" id="lab-panel-{lab_id}" tabindex="-1"
             aria-labelledby="lab-title-{lab_id}">
      <header class="panel-head">
        <h3 id="lab-title-{lab_id}">{escape(manifest.display_name)}</h3>
        <span class="tag ok">catalog foundation</span>
        <span class="tag">v{escape(manifest.laboratory_version)}</span>
        <span class="tag">{escape(_humanize(manifest.domain.value))}</span>
      </header>
      <p class="panel-desc">{escape(manifest.description)}</p>
      {facts}
      <h4>Declared capabilities <span class="h4-note">(declaration ≠ permission)</span></h4>
      <div class="chip-row">{_capability_chips(manifest.capabilities)}</div>
      <h4>Approval gates this laboratory is bound by</h4>
      <div class="chip-row">{
        _chips(
            tuple(_humanize(gate.value) for gate in manifest.approval_gates), css="chip gate-chip"
        )
    }</div>
      <h4>Accepted goal categories (future governed work)</h4>
      <div class="chip-row">{
        _chips(tuple(_humanize(token) for token in manifest.accepted_goal_categories))
    }</div>
      <h4>Required deterministic services</h4>
      <div class="chip-row">{
        _chips(tuple(_humanize(token) for token in manifest.required_deterministic_services))
    }</div>
      <h4>Artifact and evidence categories (future outputs)</h4>
      <div class="chip-row">{
        _chips(tuple(_humanize(token) for token in manifest.produced_artifact_categories))
    }{_chips(tuple(_humanize(token) for token in manifest.produced_evidence_categories))}</div>
      <h4>Verification requirements</h4>
      <ul class="plain-list">{verification}</ul>
      <h4 class="warn-heading">Known limitations (what this laboratory is not)</h4>
      <ul class="limit-list">{limitations}</ul>
    </article>"""


def _planned_panel(planned: PlannedLaboratoryProjection) -> str:
    lab_id = _attribute(planned.laboratory_id)
    non_execution_note = (
        "Roadmap concept only: non-operational, not registered in the runtime registry, "
        "not executable, and it grants nothing. A future slice must bring a real reviewed "
        "manifest before this laboratory exists."
    )
    return f"""
    <article class="lab-panel planned" id="lab-panel-{lab_id}" tabindex="-1"
             aria-labelledby="lab-title-{lab_id}">
      <header class="panel-head">
        <h3 id="lab-title-{lab_id}">{escape(planned.display_name)}</h3>
        <span class="tag warn">{escape(planned.status)}</span>
        <span class="tag">{escape(_humanize(planned.domain.value))}</span>
      </header>
      <p class="panel-desc">{escape(planned.summary)}</p>
      <p class="panel-note">{non_execution_note}</p>
    </article>"""


def _focus_section(projection: LaboratoryCatalogProjection) -> str:
    panels = "".join(_manifest_panel(m) for m in projection.laboratories) + "".join(
        _planned_panel(p) for p in projection.planned_laboratories
    )
    return f"""
  <section class="panel" id="laboratory-focus" aria-labelledby="focus-heading">
    <h2 id="focus-heading">Selected laboratory</h2>
    <p class="section-note">Selection is local and read-only. Without JavaScript, every
    laboratory record is shown below.</p>
    {panels}
  </section>"""


def _mission_flow(projection: LaboratoryCatalogProjection) -> str:
    stages = "".join(
        f"""
      <li class="flow-stage {"exists" if stage.exists_today else "future"}">
        <span class="flow-state">{"exists today" if stage.exists_today else "future"}</span>
        <span class="flow-name">{escape(stage.stage)}</span>
        <span class="flow-desc">{escape(stage.description)}</span>
        <span class="flow-provider">{escape(stage.provided_by)}</span>
      </li>"""
        for stage in projection.mission_flow
    )
    return f"""
  <section class="panel" aria-labelledby="flow-heading">
    <h2 id="flow-heading">Governed mission flow</h2>
    <p class="section-note">The conceptual governed path every piece of laboratory work
    follows. Solid stages exist in OrbitMind today; dashed stages belong to future
    Laboratory or Agent-Runtime slices.</p>
    <ol class="flow-rail">{stages}</ol>
  </section>"""


def _capability_matrix(projection: LaboratoryCatalogProjection) -> str:
    rows = "".join(
        f"""
        <tr>
          <th scope="row">{escape(_humanize(declaration.capability.value))}</th>
          <td>declared</td>
          <td>{escape(_humanize(declaration.approval_posture.value))}</td>
          <td>{escape(_humanize(declaration.determinism.value))}</td>
          <td>none connected</td>
          <td>none connected</td>
          <td>none</td>
        </tr>"""
        for manifest in projection.laboratories
        for declaration in manifest.capabilities
    )
    return f"""
  <section class="panel" aria-labelledby="matrix-heading">
    <h2 id="matrix-heading">Capability and authority matrix</h2>
    <aside class="principle" role="note">
      <strong>{escape(projection.capability_principle.split(".")[0])}.</strong>
      Capability declarations are catalog metadata. Permission, tool availability,
      adapter availability and execution authority are separate facts — and in this
      foundation slice they are all <strong>none</strong>.
    </aside>
    <div class="table-scroll">
      <table>
        <caption>Development Laboratory — declared capabilities versus actual authority</caption>
        <thead>
          <tr>
            <th scope="col">Capability</th>
            <th scope="col">Declaration</th>
            <th scope="col">Approval posture</th>
            <th scope="col">Determinism</th>
            <th scope="col">Tool</th>
            <th scope="col">Adapter</th>
            <th scope="col">Execution authority</th>
          </tr>
        </thead>
        <tbody>{rows}
        </tbody>
      </table>
    </div>
  </section>"""


def _evidence_chain(projection: LaboratoryCatalogProjection) -> str:
    links = "".join(
        f"""
      <li class="chain-link">
        <span class="chain-name">{escape(link.link)}</span>
        <span class="chain-desc">{escape(link.description)}</span>
        <span class="chain-provider">{escape(link.provided_by)}</span>
      </li>"""
        for link in projection.evidence_chain
    )
    return f"""
  <section class="panel" aria-labelledby="evidence-heading">
    <h2 id="evidence-heading">Evidence and replay</h2>
    <p class="section-note"><strong>Architecture projection</strong> — this describes the
    existing OrbitMind evidence chain that any future laboratory result must travel.
    No mission evidence is fabricated or displayed here.</p>
    <ol class="chain">{links}</ol>
    <p class="section-note">Deterministic replay and non-deterministic re-evaluation are
    distinct classifications and are never conflated.</p>
  </section>"""


def _safety_plane(projection: LaboratoryCatalogProjection) -> str:
    gates = "".join(
        f"""
      <li class="gate">
        <span class="gate-name">{escape(_humanize(boundary.gate.value))}</span>
        <span class="gate-state">{escape(boundary.current_state)}</span>
        <span class="gate-tag">human approval required</span>
      </li>"""
        for boundary in projection.safety_boundaries
    )
    return f"""
  <section class="panel" aria-labelledby="safety-heading">
    <h2 id="safety-heading">Safety and governance plane</h2>
    <p class="section-note">Sensitive boundaries and their state in this runtime. Every
    one requires explicit human approval; none is granted to any laboratory.</p>
    <ul class="gate-grid">{gates}</ul>
  </section>"""


def _offline_boundary_content(statements: tuple[str, ...]) -> _OfflineBoundaryContent:
    """Resolve the current catalog statements by semantic role, not tuple position."""

    def statement_for(*, prefix: str, role: str) -> str:
        matches = tuple(statement for statement in statements if statement.startswith(prefix))
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one offline-boundary statement for {role}")
        return matches[0]

    return _OfflineBoundaryContent(
        offline_local_work=statement_for(
            prefix="Deterministic local work", role="offline_local_work"
        ),
        connected_window=statement_for(prefix="Network sources", role="connected_window"),
        credential_isolation=statement_for(
            prefix="Credentials are never stored", role="credential_isolation"
        ),
        external_call_receipts=statement_for(
            prefix="When a connected window", role="external_call_receipts"
        ),
    )


def _offline_boundary(projection: LaboratoryCatalogProjection) -> str:
    content = _offline_boundary_content(projection.offline_boundary_statements)
    offline_items = "".join(
        f"<li>{escape(statement)}</li>"
        for statement in (content.offline_local_work, content.credential_isolation)
    )
    connected_items = "".join(
        f"<li>{escape(statement)}</li>"
        for statement in (content.connected_window, content.external_call_receipts)
    )
    return f"""
  <section class="panel" aria-labelledby="boundary-heading">
    <h2 id="boundary-heading">Offline / connected boundary</h2>
    <div class="boundary-grid">
      <div class="boundary offline">
        <h3>Offline by default</h3>
        <ul class="plain-list">{offline_items}</ul>
      </div>
      <div class="boundary connected">
        <h3>Connected only by explicit permission</h3>
        <ul class="plain-list">{connected_items}</ul>
      </div>
    </div>
  </section>"""


def render_laboratory_page(projection: LaboratoryCatalogProjection, *, version: str) -> str:
    """Render the complete Laboratory Workbench page (self-contained, offline)."""
    payload_json = build_laboratory_payload_json(projection)
    body = f"""
  <header class="hero">
    <p class="eyebrow">Governed scientific operating environment</p>
    <h1>OrbitMind Laboratory</h1>
    <p class="hero-lede">A truthful control-room view of the laboratory catalog: what is
    implemented, what is planned, and which authority nothing has. Every fact on this
    page comes from the deterministic laboratory registry and labelled architectural
    metadata — there is no live telemetry and no agent activity.</p>
    <div class="badges">
      <span class="badge ok">Offline-first</span>
      <span class="badge ok">Deterministic registry</span>
      <span class="badge warn">Foundation v1 — no agent runtime</span>
      <span class="badge">Platform v{escape(version)}</span>
    </div>
  </header>
  {_constellation(projection)}
  {_focus_section(projection)}
  {_mission_flow(projection)}
  {_capability_matrix(projection)}
  {_evidence_chain(projection)}
  {_safety_plane(projection)}
  {_offline_boundary(projection)}
  <footer class="page-footer">
    <p>All data on this page is served from the deterministic laboratory registry and
    clearly-labelled architectural metadata. Nothing here implies autonomous agents,
    live telemetry, hardware access or external AI.</p>
    <p class="footer-link"><a href="/workbench">Mission Workbench</a> ·
      <a href="/review">Reviewer sandbox</a></p>
  </footer>
  <template id="{_attribute(LABORATORY_DATA_NODE_ID)}">{payload_json}</template>
  <script src="{_attribute(LABORATORY_ASSET_PATH)}" defer></script>"""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/svg+xml" href="{_attribute(LABORATORY_FAVICON_DATA_URI)}">
  <title>OrbitMind Laboratory</title>
  <style>{LABORATORY_CSS}</style>
</head>
<body class="laboratory">
  <main>{body}</main>
</body>
</html>
"""


LABORATORY_CSS = """
    :root {
      --bg: #060b16;
      --bg-raise: #0a1424;
      --panel: #0c1830;
      --panel-soft: #101f3a;
      --ink: #e9f1fc;
      --muted: #a9bbd6;
      --line: rgba(137, 176, 232, 0.22);
      --line-soft: rgba(137, 176, 232, 0.12);
      --accent: #6fd7ea;
      --accent-deep: #2f8fb0;
      --ok: #6fdcae;
      --warn: #eec585;
      --warn-strong: #f0b25c;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body.laboratory {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(1100px 500px at 12% -140px, rgba(64, 140, 200, 0.16), transparent 60%),
        radial-gradient(900px 480px at 88% -60px, rgba(111, 215, 234, 0.08), transparent 55%),
        var(--bg);
      line-height: 1.55;
    }
    main {
      width: min(1240px, calc(100% - 32px));
      margin: 0 auto;
      padding: 40px 0 64px;
    }
    h1, h2, h3, h4 { margin: 0; line-height: 1.2; font-weight: 700; }
    h1 { font-size: clamp(1.9rem, 4vw, 2.6rem); letter-spacing: 0.01em; }
    h2 { font-size: 1.2rem; letter-spacing: 0.04em; text-transform: uppercase;
         color: var(--accent); }
    h3 { font-size: 1.05rem; }
    h4 { font-size: 0.92rem; margin-top: 20px; letter-spacing: 0.03em;
         text-transform: uppercase; color: var(--muted); }
    .h4-note { text-transform: none; letter-spacing: 0; color: var(--warn); }
    p { margin: 10px 0 0; color: var(--muted); }
    a { color: var(--accent); }
    :focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 3px;
      border-radius: 4px;
    }
    .hero {
      background: linear-gradient(180deg, rgba(20, 40, 76, 0.55), rgba(10, 20, 38, 0.4));
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 34px 34px 30px;
      margin-bottom: 22px;
    }
    .eyebrow {
      margin: 0 0 10px;
      color: var(--accent);
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      text-transform: uppercase;
    }
    .hero-lede { max-width: 70ch; }
    .badges { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 18px; }
    .badge {
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 0.82rem;
      font-weight: 700;
      padding: 5px 12px;
    }
    .badge.ok { border-color: rgba(111, 220, 174, 0.5); color: var(--ok); }
    .badge.warn { border-color: rgba(240, 178, 92, 0.55); color: var(--warn); }
    .panel {
      background: linear-gradient(180deg, rgba(16, 31, 58, 0.5), rgba(10, 20, 38, 0.35));
      border: 1px solid var(--line-soft);
      border-radius: 14px;
      padding: 26px 28px;
      margin-bottom: 22px;
    }
    .section-note { max-width: 84ch; font-size: 0.95rem; }
    /* --- Constellation ------------------------------------------------- */
    .constellation svg { display: block; width: 100%; height: auto; margin-top: 14px; }
    .mobile-constellation { display: none; }
    .star { fill: #cfe4ff; }
    .orbit { fill: none; stroke: var(--line-soft); stroke-dasharray: 3 7; }
    .link-implemented { stroke: rgba(111, 215, 234, 0.5); stroke-width: 1.6; }
    .link-planned { stroke: rgba(169, 187, 214, 0.28); stroke-width: 1.2;
                    stroke-dasharray: 5 7; }
    .core-halo { fill: rgba(111, 215, 234, 0.1); }
    .core-body { fill: url(#core-gradient); stroke: rgba(155, 229, 242, 0.6);
                 stroke-width: 1.5; }
    .core-label, .core-sublabel { fill: #06121f; font-weight: 800; font-size: 15px; }
    .core-sublabel { font-size: 12px; font-weight: 700; }
    .lab-node { cursor: pointer; }
    .lab-node .node-label { fill: var(--ink); font-size: 15px; font-weight: 700; }
    .lab-node .node-tag { fill: var(--muted); font-size: 11.5px; letter-spacing: 0.08em;
                           text-transform: uppercase; }
    .lab-node .node-state { fill: var(--ok); font-size: 10px; font-weight: 800;
                             letter-spacing: 0.05em; text-transform: uppercase; }
    .lab-node.implemented .node-halo { fill: rgba(111, 220, 174, 0.12); }
    .lab-node.implemented .node-core {
      fill: url(#dev-gradient);
      stroke: rgba(143, 240, 208, 0.8);
      stroke-width: 2;
      transition: stroke-width 160ms ease;
    }
    .lab-node.planned .node-core {
      fill: rgba(12, 24, 48, 0.6);
      stroke: rgba(169, 187, 214, 0.55);
      stroke-width: 1.6;
      stroke-dasharray: 5 5;
      transition: stroke-width 160ms ease;
    }
    .lab-node.planned .node-tag { fill: var(--warn); }
    .lab-node:hover .node-core, .lab-node:focus-visible .node-core,
    .lab-node[data-selected="true"] .node-core { stroke-width: 3.5; }
    .lab-node[data-selected="true"] .node-label { fill: var(--accent); }
    .lab-node:focus-visible { outline: none; }
    .lab-node:focus-visible .node-core { stroke: var(--accent); }
    .legend { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 10px;
              color: var(--muted); font-size: 0.88rem; }
    .legend-item { display: inline-flex; align-items: center; gap: 8px; max-width: 34ch; }
    .legend-marker { width: 20px; height: 20px; display: inline-grid; place-items: center;
                     flex: 0 0 auto; color: var(--ink); font-size: 0.74rem; font-weight: 900; }
    .legend-marker.foundation { border: 2px solid rgba(143, 240, 208, 0.8);
                                border-radius: 50%; background: rgba(111, 220, 174, 0.35); }
    .legend-marker.registered { border: 2px solid var(--accent); border-radius: 4px; }
    .legend-marker.planned { border: 2px dashed rgba(169, 187, 214, 0.8); border-radius: 50%; }
    .legend-marker.approval { border: 2px solid var(--warn); border-radius: 50%;
                              color: var(--warn); }
    .mobile-constellation-card {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(10, 21, 40, 0.55);
      color: var(--ink);
      gap: 12px;
      text-decoration: none;
    }
    .mobile-constellation-card.core { border-color: rgba(111, 215, 234, 0.55); }
    .mobile-constellation-card.implemented { border-color: rgba(111, 220, 174, 0.55); }
    .mobile-constellation-card.planned { border-style: dashed; }
    .mobile-constellation-card.approval { border-color: rgba(240, 178, 92, 0.6); }
    .mobile-constellation-marker {
      width: 28px;
      height: 28px;
      display: inline-grid;
      place-items: center;
      flex: 0 0 auto;
      border: 2px solid var(--line);
      color: var(--ink);
      font-size: 0.875rem;
      font-weight: 900;
    }
    .mobile-constellation-marker.core { border-color: var(--accent); border-radius: 50%; }
    .mobile-constellation-marker.foundation {
      border-color: var(--ok);
      border-radius: 50%;
      background: rgba(111, 220, 174, 0.25);
    }
    .mobile-constellation-marker.planned { border-style: dashed; border-radius: 50%; }
    .mobile-constellation-marker.approval { border-color: var(--warn); border-radius: 50%; }
    .mobile-constellation-copy { display: grid; gap: 2px; min-width: 0; }
    .mobile-constellation-copy strong { font-size: 1rem; line-height: 1.25; }
    .mobile-constellation-copy > span { color: var(--muted); font-size: 0.875rem; }
    .mobile-constellation-copy .mobile-constellation-state {
      color: var(--ok);
      font-size: 0.875rem;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }
    .mobile-constellation-card.planned .mobile-constellation-state,
    .mobile-constellation-card.approval .mobile-constellation-state { color: var(--warn); }
    .lab-strip { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
    .lab-select {
      appearance: none;
      background: rgba(12, 24, 48, 0.7);
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-size: 0.9rem;
      font-weight: 700;
      padding: 9px 14px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: border-color 160ms ease, background 160ms ease;
    }
    .lab-select:hover { border-color: var(--accent); }
    .lab-select[aria-pressed="true"] {
      background: rgba(111, 215, 234, 0.14);
      border-color: var(--accent);
    }
    .strip-tag { font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase;
                 color: var(--muted); }
    .strip-tag.ok { color: var(--ok); }
    .strip-tag.warn { color: var(--warn); }
    .focus-status { min-height: 1.2em; font-size: 0.9rem; }
    /* --- Focus panels --------------------------------------------------- */
    .lab-panel {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: rgba(10, 21, 40, 0.55);
      padding: 22px 24px;
      margin-top: 16px;
    }
    .lab-panel.planned { border-style: dashed; }
    .panel-head { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
    .panel-desc { max-width: 84ch; }
    .panel-note { font-size: 0.92rem; color: var(--warn); }
    .tag {
      border: 1px solid var(--line);
      border-radius: 999px;
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      padding: 3px 10px;
      white-space: nowrap;
    }
    .tag.ok { border-color: rgba(111, 220, 174, 0.5); color: var(--ok); }
    .tag.warn { border-color: rgba(240, 178, 92, 0.55); color: var(--warn); }
    .fact-grid {
      display: grid;
      grid-template-columns: minmax(170px, 0.4fr) minmax(0, 1fr);
      gap: 8px 18px;
      margin: 18px 0 0;
    }
    .fact-grid dt { color: var(--muted); font-weight: 700; font-size: 0.9rem; }
    .fact-grid dd { margin: 0; font-size: 0.95rem; }
    .chip-row { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .chip {
      border: 1px solid var(--line);
      border-radius: 8px;
      font-size: 0.85rem;
      padding: 5px 10px;
      color: var(--ink);
      background: rgba(16, 31, 58, 0.6);
    }
    .chip.cap { display: inline-flex; flex-direction: column; gap: 2px; }
    .chip-sub { color: var(--warn); font-size: 0.74rem; letter-spacing: 0.05em;
                text-transform: uppercase; }
    .chip.gate-chip { border-color: rgba(240, 178, 92, 0.4); }
    .plain-list, .limit-list { margin: 10px 0 0; padding-left: 20px; color: var(--muted); }
    .plain-list li, .limit-list li { margin-top: 6px; font-size: 0.95rem; }
    .warn-heading { color: var(--warn); }
    .limit-list { border-left: 3px solid rgba(240, 178, 92, 0.55); padding-left: 24px;
                  list-style: none; }
    /* --- Mission flow ---------------------------------------------------- */
    .flow-rail {
      list-style: none;
      counter-reset: stage;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 12px;
      margin: 18px 0 0;
      padding: 0;
    }
    .flow-stage {
      counter-increment: stage;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(10, 21, 40, 0.55);
      padding: 14px 16px;
      display: grid;
      gap: 4px;
      position: relative;
    }
    .flow-stage::before {
      content: counter(stage, decimal-leading-zero);
      position: absolute;
      top: 12px;
      right: 14px;
      color: var(--line);
      font-weight: 800;
      font-size: 0.85rem;
    }
    .flow-stage.future { border-style: dashed; }
    .flow-state { font-size: 0.72rem; font-weight: 800; letter-spacing: 0.1em;
                  text-transform: uppercase; }
    .flow-stage.exists .flow-state { color: var(--ok); }
    .flow-stage.future .flow-state { color: var(--warn); }
    .flow-name { font-weight: 700; }
    .flow-desc { color: var(--muted); font-size: 0.88rem; }
    .flow-provider { color: var(--muted); font-size: 0.78rem; opacity: 0.85; }
    /* --- Capability matrix ----------------------------------------------- */
    .principle {
      border: 1px solid rgba(240, 178, 92, 0.5);
      border-left-width: 4px;
      border-radius: 10px;
      background: rgba(240, 178, 92, 0.07);
      color: var(--ink);
      padding: 14px 18px;
      margin-top: 14px;
      font-size: 0.98rem;
    }
    .table-scroll { overflow-x: auto; margin-top: 16px; }
    table { border-collapse: collapse; width: 100%; min-width: 720px; }
    caption { caption-side: top; text-align: left; color: var(--muted);
              font-size: 0.9rem; padding-bottom: 10px; }
    th, td { border: 1px solid var(--line-soft); padding: 9px 12px; text-align: left;
             font-size: 0.9rem; }
    thead th { color: var(--accent); text-transform: uppercase; font-size: 0.76rem;
               letter-spacing: 0.08em; }
    tbody th { color: var(--ink); }
    tbody td { color: var(--muted); }
    /* --- Evidence chain --------------------------------------------------- */
    .chain {
      list-style: none;
      counter-reset: link;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      gap: 12px;
      margin: 18px 0 0;
      padding: 0;
    }
    .chain-link {
      counter-increment: link;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: rgba(10, 21, 40, 0.55);
      padding: 13px 15px;
      display: grid;
      gap: 4px;
    }
    .chain-link::before {
      content: counter(link) " / 10";
      color: var(--accent);
      font-size: 0.72rem;
      font-weight: 800;
      letter-spacing: 0.1em;
    }
    .chain-name { font-weight: 700; }
    .chain-desc { color: var(--muted); font-size: 0.86rem; }
    .chain-provider { color: var(--muted); font-size: 0.76rem; opacity: 0.85; }
    /* --- Safety plane ------------------------------------------------------ */
    .gate-grid {
      list-style: none;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
      gap: 12px;
      margin: 18px 0 0;
      padding: 0;
    }
    .gate {
      border: 1px solid rgba(240, 178, 92, 0.35);
      border-radius: 10px;
      background: rgba(10, 21, 40, 0.55);
      padding: 13px 15px;
      display: grid;
      gap: 5px;
    }
    .gate-name { font-weight: 700; }
    .gate-state { color: var(--muted); font-size: 0.86rem; }
    .gate-tag { color: var(--warn); font-size: 0.72rem; font-weight: 800;
                letter-spacing: 0.09em; text-transform: uppercase; }
    /* --- Offline boundary --------------------------------------------------- */
    .boundary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
      margin-top: 16px;
    }
    .boundary { border-radius: 12px; padding: 18px 20px; }
    .boundary.offline { border: 1px solid rgba(111, 220, 174, 0.45); }
    .boundary.connected { border: 1px dashed rgba(240, 178, 92, 0.5); }
    .boundary h3 { font-size: 0.95rem; text-transform: uppercase;
                   letter-spacing: 0.06em; }
    .boundary.offline h3 { color: var(--ok); }
    .boundary.connected h3 { color: var(--warn); }
    .page-footer { color: var(--muted); font-size: 0.9rem; padding: 4px 6px 0; }
    .footer-link { margin-top: 10px; }
    /* --- JS-enhanced selection (progressive enhancement) -------------------- */
    .js-enhanced .lab-panel[hidden] { display: none; }
    /* --- Responsive ---------------------------------------------------------- */
    @media (max-width: 1024px) {
      main { padding-top: 28px; }
      .panel { padding: 20px; }
    }
    @media (max-width: 640px) {
      .hero { padding: 22px 18px; }
      .panel { padding: 16px 14px; }
      .fact-grid { grid-template-columns: 1fr; gap: 2px 0; }
      .fact-grid dd { margin-bottom: 8px; }
      .flow-rail, .chain, .gate-grid { grid-template-columns: 1fr; }
      .constellation svg { display: none; }
      .mobile-constellation {
        display: grid;
        gap: 10px;
        list-style: none;
        margin: 16px 0 0;
        padding: 0;
      }
      .mobile-constellation-card { display: flex; align-items: flex-start; padding: 13px 14px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        transition: none !important;
        animation: none !important;
        scroll-behavior: auto !important;
      }
    }
"""
