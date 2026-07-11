"""Private browser reviewer sandbox for the bundled offline sample."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse

from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container
from orbitmind.core.errors import NotFoundError, OrbitMindError, ValidationError
from orbitmind.core.ids import is_valid_uuid
from orbitmind.observation_geometry.models import ComputedVisibilityInterval
from orbitmind.sample import (
    MAX_OBSERVE_WINDOW_HOURS,
    BundledObservationRun,
    BundledOfflineCatalogEntry,
    SampleRunResult,
    get_bundled_offline_catalog,
    get_bundled_offline_catalog_entry,
    resolve_bundled_observation_sample,
    run_bundled_observation,
    run_custom_tle_sample,
    run_sample,
)
from orbitmind.space.models import OrbitalStateSample

router = APIRouter(tags=["review"])

ContainerDep = Annotated[AppContainer, Depends(get_container)]

ALLOWED_REVIEW_ARTIFACT_FILENAMES = frozenset(
    {
        "altitude_vs_time.png",
        "altitude_vs_time.json",
        "ground_track.png",
        "ground_track.json",
        "static_report.json",
        "static_report.md",
    }
)

SAFETY_BOUNDARY_ITEMS = (
    "bundled stale sample/test-only data only",
    "not live tracking",
    "no provider fetch",
    "no command readiness, approval, or certification",
    "no quantum advantage claim",
    "not production/public-alpha workflow",
)
CUSTOM_TLE_SAFETY_BOUNDARY_ITEMS = (
    "user-provided offline TLE only",
    "not live tracking",
    "no provider fetch",
    "no CelesTrak fetch",
    "no command readiness, approval, or certification",
    "no quantum advantage claim",
    "not production/public-alpha workflow",
)
MAX_CUSTOM_TLE_BODY_BYTES = 2_048
CATALOG_SAFETY_BOUNDARY_ITEMS = (
    "bundled sample/test-only data only",
    "not live tracking",
    "no provider fetch",
    "no CelesTrak fetch",
    "no covariance available",
    "no collision probability computed",
    "no command readiness, approval, or certification",
    "no quantum advantage claim",
    "not production/public-alpha workflow",
)
MAX_CATALOG_BODY_BYTES = 256
MAX_OBSERVE_BODY_BYTES = 1_024
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")

OBSERVE_SAFETY_BOUNDARY_ITEMS = (
    "bundled offline sample/test-only data only",
    "no provider fetch",
    "no CelesTrak fetch",
    "not live certified tracking",
    "not collision warning",
    "no maneuver recommendation",
    "no command readiness, approval, or certification",
    "orbital data freshness and uncertainty are shown",
    "no probability of collision computed",
    "not production/public-alpha workflow",
)


@dataclass(frozen=True)
class ObserveForm:
    """Bounded server-rendered observer request parsed from a local HTML form."""

    satellite_identifier: str
    observer_latitude_deg: float
    observer_longitude_deg: float
    observer_altitude_km: float
    time_window_hours: int


PAGE_CSS = """
    :root {
      color-scheme: light;
      --bg: #f5f7fa;
      --panel: #ffffff;
      --panel-soft: #eef4f8;
      --ink: #17202a;
      --muted: #536172;
      --line: #d8e0e8;
      --accent: #22577a;
      --accent-strong: #163c55;
      --good-bg: #e8f7ef;
      --good-ink: #17613a;
      --warn-bg: #fff5dc;
      --warn-ink: #765312;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
        "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      line-height: 1.55;
    }
    main {
      width: min(1120px, calc(100% - 32px));
      margin: 0 auto;
      padding: 40px 0 56px;
    }
    .hero {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 28px;
      margin-bottom: 20px;
    }
    .eyebrow {
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 0.84rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    h1, h2, h3 { margin: 0; line-height: 1.2; }
    h1 { font-size: 2.2rem; }
    h2 { font-size: 1.1rem; margin-bottom: 14px; }
    h3 { font-size: 1rem; margin-bottom: 8px; }
    p { color: var(--muted); margin: 10px 0 0; }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 20px;
    }
    .card.soft { background: var(--panel-soft); }
    .button {
      appearance: none;
      border: 0;
      border-radius: 8px;
      background: var(--accent);
      color: white;
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 12px 18px;
    }
    .button:hover { background: var(--accent-strong); }
    label {
      color: var(--muted);
      display: grid;
      font-weight: 700;
      gap: 6px;
    }
    input, textarea {
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--ink);
      font: inherit;
      padding: 10px 12px;
      width: 100%;
    }
    textarea {
      min-height: 80px;
      resize: vertical;
    }
    .error {
      border-left: 4px solid #b42318;
    }
    .error h2 { color: #8a1f14; }
    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 18px;
    }
    .badge {
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      background: var(--good-bg);
      color: var(--good-ink);
      font-size: 0.86rem;
      font-weight: 700;
      padding: 5px 10px;
    }
    .badge.warn {
      background: var(--warn-bg);
      color: var(--warn-ink);
    }
    dl {
      display: grid;
      grid-template-columns: minmax(150px, 0.42fr) minmax(0, 1fr);
      gap: 10px 16px;
      margin: 0;
    }
    dt { color: var(--muted); font-weight: 700; }
    dd { margin: 0; min-width: 0; overflow-wrap: anywhere; }
    code {
      background: #edf2f6;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 2px 5px;
      overflow-wrap: anywhere;
    }
    .artifact-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 16px;
    }
    .artifact-preview img {
      display: block;
      width: 100%;
      height: auto;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      margin-top: 10px;
    }
    .link-list {
      display: grid;
      gap: 10px;
      list-style: none;
      margin: 0;
      padding: 0;
    }
    table {
      border-collapse: collapse;
      width: 100%;
      table-layout: fixed;
    }
    th, td {
      border-bottom: 1px solid var(--line);
      padding: 10px 8px;
      text-align: left;
      vertical-align: top;
      overflow-wrap: anywhere;
    }
    th { color: var(--muted); font-size: 0.86rem; }
    .safety {
      border-left: 4px solid var(--accent);
    }
    .safety ul { margin: 0; padding-left: 20px; }
    a { color: var(--accent); font-weight: 700; }
    .stack { display: grid; gap: 16px; }
    .footer-link { margin-top: 18px; }
"""


@router.get("/review", response_class=HTMLResponse)
def reviewer_home() -> HTMLResponse:
    """Return the private local reviewer sandbox entry page."""

    body = f"""
      <section class="hero">
        <p class="eyebrow">Evidence-backed offline orbital sample</p>
        <h1>OrbitMind Reviewer Sandbox</h1>
        <p>Run the bundled offline ISS sample and inspect the generated evidence bundle.</p>
        <form method="post" action="/review/run" class="footer-link">
          <button class="button" type="submit">Run bundled ISS sample</button>
        </form>
      </section>
      <section class="grid">
        <div class="card">
          <h2>Sample info</h2>
          <dl>
            <dt>available sample id</dt><dd><code>iss</code></dd>
            <dt>source</dt><dd>bundled stale sample/test-only data</dd>
            <dt>provider fetch</dt><dd>none</dd>
          </dl>
        </div>
        {_safety_boundary_panel()}
      </section>
      <section class="grid footer-link">
        <div class="card">
          <h2>Mission Workbench</h2>
          <p>Calculate deterministic offline pass and contact windows for one observer.</p>
          <p><a href="/workbench">Open Mission Workbench</a></p>
        </div>
        <div class="card">
          <h2>OrbitMind Observe</h2>
          <p>
            Use a reviewed bundled fixture to calculate bounded observer-relative pass candidates.
          </p>
          <p><a href="/observe">Open OrbitMind Observe</a></p>
        </div>
        <div class="card">
          <h2>Bundled satellite catalog</h2>
          <p>Choose a reviewed local fixture without entering TLE lines manually.</p>
          <p><a href="/review/catalog">Open the bundled offline satellite catalog</a></p>
        </div>
        <div class="card">
          <h2>Offline custom TLE</h2>
          <p>
            Paste a small two-line element set and generate the same deterministic evidence bundle.
          </p>
          <p><a href="/review/custom-tle">Open the offline custom TLE reviewer</a></p>
        </div>
      </section>
"""
    return HTMLResponse(_page("OrbitMind Reviewer Sandbox", body))


@router.post("/review/run", response_class=HTMLResponse)
def run_reviewer_sample(container: ContainerDep) -> HTMLResponse:
    """Run the bundled ISS sample and return a bounded HTML result."""

    result = run_sample(settings=container.settings, sample_id="iss")
    body = f"""
      <section class="hero">
        <p class="eyebrow">Generated evidence bundle</p>
        <h1>OrbitMind Reviewer Sandbox Result</h1>
        {_status_badges(result)}
      </section>
      <section class="grid">
        {_mission_section(result)}
        {_hash_section(result)}
      </section>
      {_artifact_section(result)}
      {_safety_boundary_panel()}
      <p class="footer-link"><a href="/review">Back to reviewer sandbox</a></p>
"""
    return HTMLResponse(_page("OrbitMind Reviewer Sandbox Result", body))


@router.get("/review/custom-tle", response_class=HTMLResponse)
def custom_tle_home() -> HTMLResponse:
    """Return the local offline custom TLE reviewer form."""

    body = f"""
      <section class="hero">
        <p class="eyebrow">Offline custom element input</p>
        <h1>Offline Custom TLE Reviewer</h1>
        <p>Paste a two-line element set and generate a deterministic offline evidence bundle.</p>
      </section>
      <section class="grid">
        <form method="post" action="/review/custom-tle/run" class="card stack">
          <h2>Custom TLE input</h2>
          <label>
            Satellite label/name, optional, max 80 chars
            <input name="satellite_label" maxlength="80" autocomplete="off">
          </label>
          <label>
            TLE line 1
            <textarea name="tle_line1" maxlength="100" required></textarea>
          </label>
          <label>
            TLE line 2
            <textarea name="tle_line2" maxlength="100" required></textarea>
          </label>
          <button class="button" type="submit">Generate offline evidence bundle</button>
        </form>
        {_safety_boundary_panel(CUSTOM_TLE_SAFETY_BOUNDARY_ITEMS)}
      </section>
      <p class="footer-link"><a href="/review">Back to reviewer sandbox</a></p>
"""
    return HTMLResponse(_page("Offline Custom TLE Reviewer", body))


@router.post("/review/custom-tle/run", response_class=HTMLResponse)
async def run_custom_tle_review_sample(request: Request, container: ContainerDep) -> HTMLResponse:
    """Run one user-pasted offline TLE through the existing deterministic workflow."""

    try:
        form = await _read_custom_tle_form(request)
        result = run_custom_tle_sample(
            settings=container.settings,
            satellite_label=form["satellite_label"],
            tle_line1=form["tle_line1"],
            tle_line2=form["tle_line2"],
        )
    except ValueError as exc:
        return _custom_tle_error_page(str(exc))
    except OrbitMindError as exc:
        return _custom_tle_error_page(exc.message, status_code=exc.http_status)
    body = f"""
      <section class="hero">
        <p class="eyebrow">Generated evidence bundle</p>
        <h1>Offline Custom TLE Reviewer Result</h1>
        {_status_badges(result)}
      </section>
      <section class="grid">
        {_mission_section(result)}
        {_hash_section(result)}
      </section>
      {_artifact_section(result)}
      {_safety_boundary_panel(CUSTOM_TLE_SAFETY_BOUNDARY_ITEMS)}
      <p class="footer-link"><a href="/review/custom-tle">Run another offline custom TLE</a></p>
"""
    return HTMLResponse(_page("Offline Custom TLE Reviewer Result", body))


@router.get("/observe", response_class=HTMLResponse)
def observe_home() -> HTMLResponse:
    """Return the bounded, bundled-fixture observer pass-planning form."""

    body = f"""
      <section class="hero">
        <p class="eyebrow">Bounded observer-relative geometry</p>
        <h1>OrbitMind Observe</h1>
        <p>
          Find a reviewed bundled satellite fixture by name or NORAD ID and calculate
          deterministic above-horizon pass candidates from one ground location. The window is
          anchored to the selected fixture TLE epoch for reproducibility, not current tracking.
        </p>
      </section>
      <section class="grid">
        <form method="post" action="/observe/run" class="card stack">
          <h2>Observer request</h2>
          <label>
            Satellite name or NORAD ID
            <input
              name="satellite_identifier"
              value="ISS"
              maxlength="80"
              autocomplete="off"
              required
            >
          </label>
          <p>
            Bundled aliases currently available: <code>ISS</code>, <code>ISS (ZARYA)</code>,
            and <code>25544</code>.
          </p>
          <label>
            Observer latitude (degrees)
            <input name="observer_latitude" type="number" min="-90" max="90" step="0.0001" required>
          </label>
          <label>
            Observer longitude (degrees)
            <input
              name="observer_longitude"
              type="number"
              min="-180"
              max="180"
              step="0.0001"
              required
            >
          </label>
          <label>
            Observer altitude (metres, optional; default 0)
            <input name="observer_altitude_m" type="number" min="-500" max="9000" step="1">
          </label>
          <label>
            Time window from fixture TLE epoch (hours, maximum {MAX_OBSERVE_WINDOW_HOURS})
            <input
              name="time_window_hours"
              type="number"
              min="1"
              max="{MAX_OBSERVE_WINDOW_HOURS}"
              step="1"
              value="{MAX_OBSERVE_WINDOW_HOURS}"
              required
            >
          </label>
          <button class="button" type="submit">Generate observation report</button>
        </form>
        {_observe_limitations_panel()}
      </section>
      {_safety_boundary_panel(OBSERVE_SAFETY_BOUNDARY_ITEMS)}
      <p class="footer-link"><a href="/review">Back to reviewer sandbox</a></p>
"""
    return HTMLResponse(_page("OrbitMind Observe", body))


@router.post("/observe/run", response_class=HTMLResponse)
async def run_observe(request: Request, container: ContainerDep) -> HTMLResponse:
    """Calculate bounded pass candidates from a reviewed local fixture only."""

    try:
        form = await _read_observe_form(request)
        sample = resolve_bundled_observation_sample(container.registry, form.satellite_identifier)
        observation = run_bundled_observation(
            settings=container.settings,
            sample_id=sample.sample_id,
            observer_latitude_deg=form.observer_latitude_deg,
            observer_longitude_deg=form.observer_longitude_deg,
            observer_altitude_km=form.observer_altitude_km,
            time_window_hours=form.time_window_hours,
        )
    except ValueError as exc:
        return _observe_error_page(str(exc))
    except OrbitMindError as exc:
        return _observe_error_page(exc.message, status_code=exc.http_status)
    body = f"""
      <section class="hero">
        <p class="eyebrow">Bundled offline observation report</p>
        <h1>OrbitMind Observe Result</h1>
        {_status_badges(observation.mission_result)}
      </section>
      <section class="grid">
        {_observe_source_section(observation)}
        {_observe_observer_section(observation)}
      </section>
      {_observe_pass_windows_section(observation)}
      <section class="grid">
        {_mission_section(observation.mission_result)}
        {_hash_section(observation.mission_result)}
      </section>
      {_artifact_section(observation.mission_result)}
      {_observe_limitations_panel()}
      {_safety_boundary_panel(OBSERVE_SAFETY_BOUNDARY_ITEMS)}
      <p class="footer-link"><a href="/observe">Run another bounded observation report</a></p>
"""
    return HTMLResponse(_page("OrbitMind Observe Result", body))


@router.get("/review/catalog", response_class=HTMLResponse)
def catalog_home(container: ContainerDep) -> HTMLResponse:
    """Return the bounded local catalog of reviewed offline TLE fixtures."""

    try:
        entries = get_bundled_offline_catalog(container.registry)
    except OrbitMindError:
        return _catalog_error_page("bundled offline catalog is unavailable", status_code=503)
    cards = "\n".join(_catalog_card(entry) for entry in entries)
    body = f"""
      <section class="hero">
        <p class="eyebrow">Verified local fixtures</p>
        <h1>Bundled Offline Satellite Catalog</h1>
        <p>
          Choose a bundled stale sample/test-only TLE and generate a deterministic SGP4
          evidence bundle.
        </p>
      </section>
      <section class="grid">
        {cards}
      </section>
      <section class="card soft footer-link">
        <h2>Catalog scope</h2>
        <p>
          This catalog currently contains only reviewed local fixtures. Additional fixtures require
          source and legal review before they are bundled.
        </p>
      </section>
      {_accuracy_limitations_panel()}
      {_safety_boundary_panel(CATALOG_SAFETY_BOUNDARY_ITEMS)}
      <p class="footer-link"><a href="/review">Back to reviewer sandbox</a></p>
"""
    return HTMLResponse(_page("Bundled Offline Satellite Catalog", body))


@router.post("/review/catalog/run", response_class=HTMLResponse)
async def run_catalog_review_sample(request: Request, container: ContainerDep) -> HTMLResponse:
    """Run one server-known catalog sample through the existing deterministic workflow."""

    try:
        sample_id = await _read_catalog_sample_id(request)
        catalog_entry = get_bundled_offline_catalog_entry(container.registry, sample_id)
        result = run_sample(settings=container.settings, sample_id=catalog_entry.sample_id)
    except ValueError as exc:
        return _catalog_error_page(str(exc))
    except OrbitMindError as exc:
        return _catalog_error_page(exc.message, status_code=exc.http_status)
    body = f"""
      <section class="hero">
        <p class="eyebrow">Generated evidence bundle</p>
        <h1>Bundled Offline Satellite Catalog Result</h1>
        {_status_badges(result)}
      </section>
      <section class="grid">
        {_catalog_selection_section(catalog_entry)}
        {_accuracy_limitations_panel()}
      </section>
      <section class="grid">
        {_mission_section(result)}
        {_hash_section(result)}
      </section>
      {_artifact_section(result)}
      {_safety_boundary_panel(CATALOG_SAFETY_BOUNDARY_ITEMS)}
      <p class="footer-link">
        <a href="/review/catalog">Back to bundled offline satellite catalog</a>
      </p>
"""
    return HTMLResponse(_page("Bundled Offline Satellite Catalog Result", body))


@router.get("/review/artifacts/{mission_id}/{filename:path}")
def get_reviewer_artifact(
    mission_id: str,
    filename: str,
    container: ContainerDep,
) -> FileResponse:
    """Serve only whitelisted generated files for a reviewer sample mission."""

    if not is_valid_uuid(mission_id):
        raise ValidationError("mission id is not a valid identifier")
    if filename not in ALLOWED_REVIEW_ARTIFACT_FILENAMES:
        raise NotFoundError("review artifact not found")
    artifact_path = container.settings.resolved_artifacts_dir() / mission_id / filename
    try:
        resolved_path = artifact_path.resolve()
        resolved_path.relative_to(container.settings.resolved_artifacts_dir().resolve())
    except ValueError as exc:  # pragma: no cover - filename allowlist prevents this.
        raise NotFoundError("review artifact not found") from exc
    if not resolved_path.is_file():
        raise NotFoundError("review artifact not found")
    return FileResponse(resolved_path)


async def _read_custom_tle_form(request: Request) -> dict[str, str]:
    body = await request.body()
    if len(body) > MAX_CUSTOM_TLE_BODY_BYTES:
        raise ValueError("custom TLE request body is too large")
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError as exc:
        raise ValueError("custom TLE form must be UTF-8 encoded") from exc
    return {
        "satellite_label": _single_form_value(parsed, "satellite_label"),
        "tle_line1": _single_form_value(parsed, "tle_line1"),
        "tle_line2": _single_form_value(parsed, "tle_line2"),
    }


async def _read_observe_form(request: Request) -> ObserveForm:
    body = await request.body()
    if len(body) > MAX_OBSERVE_BODY_BYTES:
        raise ValueError("observe request body is too large")
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError as exc:
        raise ValueError("observe form must be UTF-8 encoded") from exc
    allowed_keys = {
        "satellite_identifier",
        "observer_latitude",
        "observer_longitude",
        "observer_altitude_m",
        "time_window_hours",
    }
    if not set(parsed).issubset(allowed_keys):
        raise ValueError("observe form contains unsupported fields")
    satellite_identifier = _normalize_observe_identifier(
        _required_single_form_value(parsed, "satellite_identifier")
    )
    latitude = _parse_bounded_observe_float(
        _required_single_form_value(parsed, "observer_latitude"),
        field_name="observer latitude",
        lower=-90.0,
        upper=90.0,
    )
    longitude = _parse_bounded_observe_float(
        _required_single_form_value(parsed, "observer_longitude"),
        field_name="observer longitude",
        lower=-180.0,
        upper=180.0,
    )
    altitude_m = _parse_bounded_observe_float(
        _optional_single_form_value(parsed, "observer_altitude_m"),
        field_name="observer altitude",
        lower=-500.0,
        upper=9_000.0,
        default=0.0,
    )
    time_window_hours = _parse_observe_time_window(
        _required_single_form_value(parsed, "time_window_hours")
    )
    return ObserveForm(
        satellite_identifier=satellite_identifier,
        observer_latitude_deg=latitude,
        observer_longitude_deg=longitude,
        observer_altitude_km=altitude_m / 1_000.0,
        time_window_hours=time_window_hours,
    )


async def _read_catalog_sample_id(request: Request) -> str:
    body = await request.body()
    if len(body) > MAX_CATALOG_BODY_BYTES:
        raise ValueError("catalog request body is too large")
    try:
        parsed = parse_qs(body.decode("utf-8"), keep_blank_values=True)
    except UnicodeDecodeError as exc:
        raise ValueError("catalog form must be UTF-8 encoded") from exc
    if set(parsed) != {"sample_id"}:
        raise ValueError("catalog request must include only one sample selection")
    values = parsed["sample_id"]
    if len(values) != 1 or not values[0].strip():
        raise ValueError("catalog sample selection is required")
    return values[0]


def _required_single_form_value(parsed: dict[str, list[str]], key: str) -> str:
    values = parsed.get(key)
    if values is None or len(values) != 1 or not values[0].strip():
        raise ValueError(f"{key.replace('_', ' ')} is required")
    return values[0]


def _optional_single_form_value(parsed: dict[str, list[str]], key: str) -> str:
    values = parsed.get(key)
    if values is None:
        return ""
    if len(values) != 1:
        raise ValueError(f"{key.replace('_', ' ')} must be provided once")
    return values[0]


def _normalize_observe_identifier(value: str) -> str:
    identifier = value.strip()
    if not identifier or len(identifier) > 80:
        raise ValueError("satellite identifier must be non-empty and 80 characters or fewer")
    if "<" in identifier or ">" in identifier:
        raise ValueError("satellite identifier contains unsupported markup characters")
    return identifier


def _parse_bounded_observe_float(
    value: str,
    *,
    field_name: str,
    lower: float,
    upper: float,
    default: float | None = None,
) -> float:
    if not value.strip():
        if default is not None:
            return default
        raise ValueError(f"{field_name} is required")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a finite number") from exc
    if not math.isfinite(parsed) or parsed < lower or parsed > upper:
        raise ValueError(f"{field_name} must be between {lower:g} and {upper:g}")
    return parsed


def _parse_observe_time_window(value: str) -> int:
    normalized = value.strip()
    if not _POSITIVE_INTEGER_RE.fullmatch(normalized):
        raise ValueError("time window must be a whole number of hours")
    hours = int(normalized)
    if hours > MAX_OBSERVE_WINDOW_HOURS:
        raise ValueError("time window must not exceed 24 hours")
    return hours


def _single_form_value(parsed: dict[str, list[str]], key: str) -> str:
    values = parsed.get(key)
    if not values:
        return ""
    return values[0]


def _custom_tle_error_page(message: str, *, status_code: int = 422) -> HTMLResponse:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Input rejected</p>
        <h1>Offline Custom TLE Reviewer</h1>
        <p>The pasted offline TLE could not be accepted for a deterministic reviewer run.</p>
      </section>
      <section class="grid">
        <div class="card error">
          <h2>Validation error</h2>
          <p>{escape(message)}</p>
          <p><a href="/review/custom-tle">Back to custom TLE form</a></p>
        </div>
        {_safety_boundary_panel(CUSTOM_TLE_SAFETY_BOUNDARY_ITEMS)}
      </section>
"""
    return HTMLResponse(_page("Offline Custom TLE Reviewer Error", body), status_code=status_code)


def _observe_error_page(message: str, *, status_code: int = 422) -> HTMLResponse:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Observer request rejected</p>
        <h1>OrbitMind Observe</h1>
        <p>The bounded offline observation request could not be accepted.</p>
      </section>
      <section class="grid">
        <div class="card error">
          <h2>Validation error</h2>
          <p>{escape(message)}</p>
          <p><a href="/observe">Back to OrbitMind Observe</a></p>
        </div>
        {_observe_limitations_panel()}
      </section>
      {_safety_boundary_panel(OBSERVE_SAFETY_BOUNDARY_ITEMS)}
"""
    return HTMLResponse(_page("OrbitMind Observe Error", body), status_code=status_code)


def _catalog_error_page(message: str, *, status_code: int = 422) -> HTMLResponse:
    body = f"""
      <section class="hero">
        <p class="eyebrow">Selection rejected</p>
        <h1>Bundled Offline Satellite Catalog</h1>
        <p>The selected local catalog fixture could not be used for a reviewer run.</p>
      </section>
      <section class="grid">
        <div class="card error">
          <h2>Catalog selection error</h2>
          <p>{escape(message)}</p>
          <p><a href="/review/catalog">Back to bundled offline satellite catalog</a></p>
        </div>
        {_safety_boundary_panel(CATALOG_SAFETY_BOUNDARY_ITEMS)}
      </section>
"""
    return HTMLResponse(
        _page("Bundled Offline Satellite Catalog Error", body), status_code=status_code
    )


def _page(title: str, body: str) -> str:
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{escape(title)}</title>
    <style>{PAGE_CSS}</style>
  </head>
  <body>
    <main>
      {body}
    </main>
  </body>
</html>
"""


def _status_badges(result: SampleRunResult) -> str:
    mission = result.mission
    source_test_only = mission.source.test_only if mission.source is not None else None
    return f"""
        <div class="badges">
          <span class="badge">{escape(mission.status.value)}</span>
          <span class="badge">{escape(mission.epistemic_status.value)}</span>
          <span class="badge warn">test-only source: {str(source_test_only).lower()}</span>
        </div>
"""


def _mission_section(result: SampleRunResult) -> str:
    mission = result.mission
    source_test_only = mission.source.test_only if mission.source is not None else None
    source_label = mission.source.source_name if mission.source is not None else "unavailable"
    source_name = mission.source.name if mission.source is not None else "unavailable"
    first_sample = _format_sample(mission.samples[0] if mission.samples else None)
    last_sample = _format_sample(mission.samples[-1] if mission.samples else None)
    return f"""
      <section class="card">
        <h2>Mission summary</h2>
        <dl>
          <dt>mission_id</dt><dd>{escape(str(mission.mission_id))}</dd>
          <dt>status</dt><dd>{escape(mission.status.value)}</dd>
          <dt>epistemic_status</dt><dd>{escape(mission.epistemic_status.value)}</dd>
          <dt>sample_count</dt><dd>{mission.sample_count}</dd>
          <dt>source label</dt><dd>{escape(source_label)}</dd>
          <dt>source name</dt><dd>{escape(source_name)}</dd>
          <dt>source.test_only</dt><dd>{str(source_test_only).lower()}</dd>
          <dt>first_sample</dt><dd>{escape(first_sample)}</dd>
          <dt>last_sample</dt><dd>{escape(last_sample)}</dd>
        </dl>
      </section>
"""


def _hash_section(result: SampleRunResult) -> str:
    mission = result.mission
    source_checksum = mission.source.checksum if mission.source is not None else "unavailable"
    inputs_hash = mission.provenance[0].inputs_hash if mission.provenance else "unavailable"
    return f"""
      <section class="card">
        <h2>Evidence / hashes</h2>
        <dl>
          <dt>source_checksum</dt><dd><code>{escape(source_checksum)}</code></dd>
          <dt>inputs_hash</dt><dd><code>{escape(inputs_hash)}</code></dd>
        </dl>
      </section>
"""


def _observe_source_section(observation: BundledObservationRun) -> str:
    tle_epoch = _source_epoch_utc(observation.source.epoch_utc)
    tle_age_days = max(0, (datetime.now(UTC) - tle_epoch).days)
    norad_catalog_id = (
        str(observation.source.norad_cat_id)
        if observation.source.norad_cat_id is not None
        else "unavailable"
    )
    return f"""
      <section class="card">
        <h2>Orbital data source</h2>
        <dl>
          <dt>satellite name</dt><dd>{escape(observation.source.name)}</dd>
          <dt>NORAD ID</dt><dd>{escape(norad_catalog_id)}</dd>
          <dt>source used</dt><dd>bundled offline catalog fixture</dd>
          <dt>source label</dt><dd>bundled sample/test-only</dd>
          <dt>source timestamp</dt><dd>fixture epoch; no fetched_at for bundled data</dd>
          <dt>TLE epoch</dt><dd>{escape(_format_timestamp(tle_epoch))}</dd>
          <dt>data age</dt><dd>{tle_age_days} days</dd>
          <dt>source checksum</dt><dd><code>{escape(observation.source.checksum)}</code></dd>
          <dt>observation input checksum</dt>
          <dd><code>{escape(observation.geometry.request_checksum)}</code></dd>
        </dl>
      </section>
"""


def _observe_observer_section(observation: BundledObservationRun) -> str:
    return f"""
      <section class="card">
        <h2>Observer and model</h2>
        <dl>
          <dt>observer latitude</dt><dd>{observation.observer.latitude_deg:.6f} deg</dd>
          <dt>observer longitude</dt><dd>{observation.observer.longitude_deg:.6f} deg</dd>
          <dt>observer altitude</dt><dd>{observation.observer.altitude_km * 1_000.0:.1f} m</dd>
          <dt>time window</dt>
          <dd>
            {escape(_format_timestamp(observation.start))} to
            {escape(_format_timestamp(observation.end))}
          </dd>
          <dt>propagation model</dt><dd>SGP4</dd>
          <dt>look-angle method</dt><dd>bounded topocentric azimuth/elevation geometry</dd>
          <dt>sampled horizon threshold</dt><dd>0 degrees elevation</dd>
          <dt>geometry status</dt><dd>{observation.geometry.failed_sample_count} failed samples</dd>
        </dl>
      </section>
"""


def _observe_pass_windows_section(observation: BundledObservationRun) -> str:
    visible_intervals = observation.geometry.intervals
    visible_rows = "\n".join(_observe_pass_row(interval) for interval in visible_intervals[:20])
    if not visible_rows:
        visible_rows = (
            '<tr><td colspan="7">No sampled above-horizon pass candidate was found in this '
            "bounded window.</td></tr>"
        )
    additional_note = ""
    if len(visible_intervals) > 20:
        additional_note = (
            f"<p>Showing the first 20 of {len(visible_intervals)} bounded pass candidates.</p>"
        )
    return f"""
      <section class="card">
        <h2>Next sampled pass windows</h2>
        <p>
          Above-horizon geometric candidates only. These do not assess optical visibility,
          weather, terrain, sensor constraints, or operational access.
        </p>
        <table>
          <thead>
            <tr>
              <th>Rise time</th><th>Rise azimuth</th><th>Peak time</th>
              <th>Max elevation</th><th>Set time</th><th>Set azimuth</th><th>Boundary</th>
            </tr>
          </thead>
          <tbody>{visible_rows}</tbody>
        </table>
        {additional_note}
      </section>
"""


def _observe_pass_row(interval: ComputedVisibilityInterval) -> str:
    return (
        "<tr>"
        f"<td>{escape(_format_timestamp(interval.rise_time))}</td>"
        f"<td>{interval.rise_azimuth_deg:.2f} deg</td>"
        f"<td>{escape(_format_timestamp(interval.peak_time))}</td>"
        f"<td>{interval.peak_elevation_deg:.2f} deg</td>"
        f"<td>{escape(_format_timestamp(interval.set_time))}</td>"
        f"<td>{interval.set_azimuth_deg:.2f} deg</td>"
        f"<td>{escape(interval.refinement_status.value)}</td>"
        "</tr>"
    )


def _observe_limitations_panel() -> str:
    return """
      <section class="card safety">
        <h2>Observation limitations</h2>
        <ul>
          <li>TLE/SGP4 can have kilometre-scale uncertainty, especially for stale elements.</li>
          <li>No covariance is available.</li>
          <li>No probability of collision is computed.</li>
          <li>Not live certified tracking and not an operational safety assessment.</li>
          <li>Not suitable for maneuver decisions or guidance.</li>
          <li>Optical visibility is not assessed in this phase.</li>
        </ul>
      </section>
"""


def _source_epoch_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _catalog_card(entry: BundledOfflineCatalogEntry) -> str:
    norad_catalog_id = str(entry.norad_catalog_id) if entry.norad_catalog_id is not None else "N/A"
    epoch = entry.tle_epoch_utc.isoformat().replace("+00:00", "Z")
    age_observed_at = entry.age_observed_at_utc.isoformat().replace("+00:00", "Z")
    return f"""
      <article class="card stack">
        <div>
          <p class="eyebrow">{escape(entry.orbit_class)} orbit</p>
          <h2>{escape(entry.display_name)}</h2>
        </div>
        <dl>
          <dt>sample id</dt><dd><code>{escape(entry.sample_id)}</code></dd>
          <dt>NORAD catalog id</dt><dd>{escape(norad_catalog_id)}</dd>
          <dt>orbit class</dt><dd>{escape(entry.orbit_class)}</dd>
          <dt>TLE epoch</dt><dd>{escape(epoch)}</dd>
          <dt>TLE age</dt><dd>{entry.tle_age_days} days as of {escape(age_observed_at)}</dd>
          <dt>source</dt><dd>{escape(entry.source_label)}</dd>
          <dt>source note</dt><dd>{escape(entry.source_note)}</dd>
          <dt>accuracy note</dt><dd>{escape(entry.accuracy_note)}</dd>
        </dl>
        <form method="post" action="/review/catalog/run">
          <input type="hidden" name="sample_id" value="{escape(entry.sample_id)}">
          <button class="button" type="submit">Generate evidence bundle</button>
        </form>
      </article>
"""


def _catalog_selection_section(entry: BundledOfflineCatalogEntry) -> str:
    epoch = entry.tle_epoch_utc.isoformat().replace("+00:00", "Z")
    return f"""
      <section class="card">
        <h2>Catalog selection</h2>
        <dl>
          <dt>sample id</dt><dd><code>{escape(entry.sample_id)}</code></dd>
          <dt>satellite name</dt><dd>{escape(entry.display_name)}</dd>
          <dt>NORAD catalog id</dt><dd>{entry.norad_catalog_id}</dd>
          <dt>orbit class</dt><dd>{escape(entry.orbit_class)}</dd>
          <dt>TLE epoch</dt><dd>{escape(epoch)}</dd>
          <dt>TLE age</dt><dd>{entry.tle_age_days} days</dd>
          <dt>source</dt><dd>{escape(entry.source_label)}</dd>
        </dl>
      </section>
"""


def _accuracy_limitations_panel() -> str:
    return """
      <section class="card safety">
        <h2>Accuracy / limitations</h2>
        <ul>
          <li>This uses bundled offline TLE data.</li>
          <li>TLE + SGP4 position error can grow over time.</li>
          <li>No covariance is available.</li>
          <li>No collision probability is computed.</li>
          <li>Educational/advisory only; not live tracking.</li>
          <li>Not command readiness, approval, or certification.</li>
        </ul>
      </section>
"""


def _artifact_section(result: SampleRunResult) -> str:
    preview_cards = "\n".join(
        _artifact_preview(result, filename)
        for filename in ("ground_track.png", "altitude_vs_time.png")
    )
    report_links = "\n".join(
        _link_list_item(result.mission.mission_id, filename)
        for filename in ("static_report.md", "static_report.json")
    )
    sidecar_links = "\n".join(
        _link_list_item(result.mission.mission_id, filename)
        for filename in ("ground_track.json", "altitude_vs_time.json")
    )
    checksum_rows = "\n".join(_checksum_rows(result))
    return f"""
      <section class="card">
        <h2>Visual artifacts</h2>
        <div class="artifact-grid">
          {preview_cards}
        </div>
      </section>
      <section class="grid">
        <div class="card">
          <h2>Reports</h2>
          <ul class="link-list">
            {report_links}
          </ul>
        </div>
        <div class="card">
          <h2>Sidecar JSON</h2>
          <ul class="link-list">
            {sidecar_links}
          </ul>
        </div>
      </section>
      <section class="card">
        <h2>Artifact checksum table</h2>
        <table>
          <thead>
            <tr><th>Artifact name</th><th>File/link</th><th>Checksum</th></tr>
          </thead>
          <tbody>
            {checksum_rows}
          </tbody>
        </table>
      </section>
"""


def _artifact_preview(result: SampleRunResult, filename: str) -> str:
    artifact_label = filename.removesuffix(".png")
    href = _artifact_href(result.mission.mission_id, filename)
    return (
        '<article class="artifact-preview">'
        f"<h3>{escape(artifact_label)}</h3>"
        f'<a href="{href}">'
        f'<img src="{href}" alt="{escape(artifact_label)} artifact preview">'
        "</a>"
        "</article>"
    )


def _link_list_item(mission_id: str, filename: str) -> str:
    href = _artifact_href(mission_id, filename)
    return f'<li><a href="{href}">{escape(filename)}</a></li>'


def _checksum_rows(result: SampleRunResult) -> list[str]:
    rows: list[str] = []
    for artifact in sorted(result.mission.artifacts, key=lambda item: item.type.value):
        rows.append(
            _checksum_row(
                artifact.type.value,
                Path(artifact.path).name,
                result.display_artifact_path(artifact),
                artifact.checksum,
                result.mission.mission_id,
            )
        )
        rows.append(
            _checksum_row(
                f"{artifact.type.value} sidecar",
                Path(artifact.sidecar_path).name,
                result.display_sidecar_path(artifact),
                "sidecar",
                result.mission.mission_id,
            )
        )
    rows.append(
        _checksum_row(
            "static_report.json",
            "static_report.json",
            result.display_static_report_path(),
            result.static_report_checksum,
            result.mission.mission_id,
        )
    )
    rows.append(
        _checksum_row(
            "static_report.md",
            "static_report.md",
            result.display_static_report_markdown_path(),
            result.static_report_markdown_checksum,
            result.mission.mission_id,
        )
    )
    return rows


def _checksum_row(
    artifact_name: str,
    filename: str,
    display_path: Path,
    checksum: str,
    mission_id: str,
) -> str:
    href = _artifact_href(mission_id, filename)
    link_cell = (
        f'<a href="{href}">{escape(filename)}</a><br><code>{escape(str(display_path))}</code>'
    )
    return (
        "<tr>"
        f"<td>{escape(artifact_name)}</td>"
        f"<td>{link_cell}</td>"
        f"<td><code>{escape(checksum)}</code></td>"
        "</tr>"
    )


def _artifact_href(mission_id: str, filename: str) -> str:
    return f"/review/artifacts/{escape(str(mission_id))}/{escape(filename)}"


def _format_sample(sample: OrbitalStateSample | None) -> str:
    if sample is None:
        return "unavailable"
    if sample.latitude_deg is None or sample.longitude_deg is None or sample.altitude_km is None:
        return f"{sample.timestamp.isoformat()} geodetic sample unavailable"
    return (
        f"{sample.timestamp.isoformat()} "
        f"lat={sample.latitude_deg:.6f} deg "
        f"lon={sample.longitude_deg:.6f} deg "
        f"alt={sample.altitude_km:.3f} km"
    )


def _safety_boundary_panel(items: tuple[str, ...] = SAFETY_BOUNDARY_ITEMS) -> str:
    return f"""
      <section class="card safety">
        <h2>Safety boundary</h2>
        {_safety_boundary_list(items)}
      </section>
"""


def _safety_boundary_list(items: tuple[str, ...]) -> str:
    rendered_items = "\n".join(f"<li>{escape(item)}</li>" for item in items)
    return f"<ul>{rendered_items}</ul>"
