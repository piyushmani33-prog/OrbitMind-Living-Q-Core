"""Server-rendered offline Mission Workbench over the mission-window service."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html import escape
from typing import Annotated
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError as PydanticValidationError

from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container
from orbitmind.api.presentation.trajectory_replay import (
    SVG_HEIGHT,
    SVG_WIDTH,
    ReplayDisplayProjection,
    build_replay_display_projection,
    escape_attr,
)
from orbitmind.api.routers.review import PAGE_CSS
from orbitmind.core.errors import OrbitMindError
from orbitmind.mission_windows.models import (
    MissionWindowEvent,
    MissionWindowRequest,
    MissionWindowResult,
    ObserverLocation,
)
from orbitmind.observation_geometry.models import GeodeticPosition, PinnedOrbitElementSet
from orbitmind.sample import (
    BundledOfflineCatalogEntry,
    get_bundled_offline_catalog,
    get_bundled_offline_catalog_entry,
    resolve_bundled_observation_sample,
    resolve_custom_offline_tle,
)
from orbitmind.trajectory_replay.models import (
    MAX_REPLAY_SAMPLES,
    PINNED_MODEL_STATEMENT,
    PREDICTED_REPLAY_LIMITATION,
    TrajectoryReplayRequest,
    TrajectoryReplayResult,
)

router = APIRouter(tags=["workbench"])

ContainerDep = Annotated[AppContainer, Depends(get_container)]

MAX_WORKBENCH_BODY_BYTES = 4_096
WORKBENCH_COARSE_STEP_SECONDS = 60
MAX_REPLAY_HTML_BYTES = 1_000_000
_WORKBENCH_SOURCE_MODES = frozenset({"catalog", "custom"})
_WORKBENCH_FORM_FIELDS = frozenset(
    {
        "source_mode",
        "catalog_sample_id",
        "custom_label",
        "tle_line1",
        "tle_line2",
        "observer_latitude_deg",
        "observer_longitude_deg",
        "observer_altitude_metres",
        "start_time_utc",
        "duration_hours",
        "minimum_elevation_deg",
    }
)
_SAFE_WORKBENCH_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .:_()&+-]*$")
_UNSAFE_WORKBENCH_LABEL = re.compile(
    r"(?i)(?:\bauthorization\s*:\s*bearer\b|\bbearer\s+[A-Za-z0-9._-]{6,}|\bcookie\s*:)"
)
_COMPASS_LABELS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
NO_WINDOW_MESSAGE = "No qualifying geometric window was found in the requested interval."
EARTH_ORIENTATION_LIMITATION = (
    "UTC is used as a UT1 approximation; full Earth-orientation and polar-motion corrections "
    "are not applied."
)

WORKBENCH_CSS = (
    PAGE_CSS
    + """
    select {
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--ink);
      font: inherit;
      padding: 10px 12px;
      width: 100%;
      background: var(--panel);
    }
    input:focus-visible, textarea:focus-visible, select:focus-visible,
    button:focus-visible, a:focus-visible, summary:focus-visible {
      outline: 3px solid #80b7d4;
      outline-offset: 2px;
    }
    fieldset {
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 0;
      padding: 20px;
    }
    legend { font-weight: 800; padding: 0 8px; }
    .workbench-form, .section-stack { display: grid; gap: 18px; }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 16px;
    }
    .source-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 16px;
    }
    .source-option {
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 14px;
      padding: 16px;
    }
    .radio-label {
      align-items: center;
      color: var(--ink);
      display: flex;
      gap: 9px;
    }
    .radio-label input { width: auto; }
    .helper { color: var(--muted); font-size: 0.88rem; margin: 0; }
    .action-row { align-items: center; display: flex; flex-wrap: wrap; gap: 14px; }
    .result-lead {
      border-top: 5px solid var(--accent);
      display: grid;
      gap: 18px;
    }
    .next-window {
      background: var(--panel);
      border: 1px solid var(--line);
      border-left: 5px solid var(--good-ink);
      border-radius: 8px;
      padding: 24px;
    }
    .empty-state { border-left: 5px solid var(--warn-ink); }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }
    .metric {
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
      padding: 14px;
    }
    .metric-label { color: var(--muted); display: block; font-size: 0.82rem; font-weight: 700; }
    .metric-value {
      display: block;
      font-size: 1rem;
      font-weight: 800;
      margin-top: 4px;
      overflow-wrap: anywhere;
    }
    .section-gap { margin-top: 20px; }
    .table-wrap { overflow-x: auto; }
    .window-table { min-width: 880px; table-layout: auto; }
    details {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 18px 20px;
    }
    summary { color: var(--accent); cursor: pointer; font-weight: 800; }
    details[open] summary { margin-bottom: 18px; }
    .limitations { margin: 12px 0 0; padding-left: 20px; }
    .limitations li + li { margin-top: 7px; }
    .secondary-button {
      background: var(--panel);
      border: 1px solid var(--accent);
      color: var(--accent);
    }
    .replay-panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      display: grid;
      gap: 18px;
      padding: 22px;
    }
    .replay-svg-wrap {
      background: linear-gradient(180deg, #eef7fb 0%, #f8fbfc 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
    }
    .replay-svg { display: block; height: auto; width: 100%; }
    .graticule { stroke: #b7ccd5; stroke-width: 1; }
    .guide-strong { stroke: #6f8994; stroke-width: 1.5; }
    .track-line {
      fill: none;
      stroke: var(--accent);
      stroke-linecap: round;
      stroke-linejoin: round;
      stroke-width: 2.4;
    }
    .satellite-marker { fill: var(--good-ink); stroke: #ffffff; stroke-width: 3; }
    .observer-marker { fill: var(--warn-ink); stroke: #ffffff; stroke-width: 3; }
    .replay-controls {
      align-items: end;
      display: grid;
      grid-template-columns: auto auto 1fr auto auto;
      gap: 12px;
    }
    .compact-button {
      min-height: 42px;
      padding: 9px 13px;
    }
    .timeline-field { display: grid; gap: 6px; min-width: 180px; }
    .timeline-field input { accent-color: var(--accent); }
    .readout-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .replay-error {
      background: #fff1f0;
      border: 1px solid #e3a29d;
      border-radius: 8px;
      color: #7a231d;
      display: none;
      padding: 12px 14px;
    }
    .noscript-note {
      background: var(--panel-soft);
      border: 1px solid var(--line);
      border-radius: 8px;
      color: var(--muted);
      padding: 12px 14px;
    }
    .js-disabled .requires-js { opacity: 0.72; }
    @media (max-width: 700px) {
      main { width: min(100% - 20px, 1120px); padding: 20px 0 36px; }
      .hero, .card, .next-window { padding: 18px; }
      h1 { font-size: 1.72rem; }
      dl { grid-template-columns: 1fr; gap: 4px; }
      dd + dt { margin-top: 10px; }
      .replay-panel { padding: 16px; }
      .replay-controls { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .timeline-field { grid-column: 1 / -1; }
      .replay-controls select { grid-column: 1 / -1; }
    }
"""
)


@dataclass(frozen=True)
class WorkbenchForm:
    """Bounded transient form values; raw TLE text is never persisted or rendered."""

    source_mode: str
    catalog_sample_id: str
    custom_label: str | None
    tle_line1: str
    tle_line2: str
    observer_latitude_deg: float
    observer_longitude_deg: float
    observer_altitude_metres: float
    start_time_utc: datetime
    duration_hours: float
    minimum_elevation_deg: float


@dataclass(frozen=True)
class ResolvedWorkbenchSource:
    """Safe display identity plus a validated request-local orbital element set."""

    elements: PinnedOrbitElementSet
    display_label: str
    stable_identity: str
    source_mode_label: str


class WorkbenchFormError(ValueError):
    """Safe validation error whose message contains no submitted orbital data."""


class WorkbenchBodyTooLarge(WorkbenchFormError):
    """Bounded-body failure before form parsing."""


@router.get("/workbench", response_class=HTMLResponse)
def mission_workbench_home(container: ContainerDep) -> HTMLResponse:
    """Render the offline Mission Workbench form."""

    catalog = get_bundled_offline_catalog(container.registry)
    body = f"""
      <section class="hero">
        <p class="eyebrow">Deterministic offline mission geometry</p>
        <h1>OrbitMind Mission Workbench</h1>
        <p>Calculate predicted geometric pass and contact windows from an identified orbital
        element set.</p>
        <div class="badges">
          <span class="badge">Offline orbital sources</span>
          <span class="badge warn">Predicted geometry, not live tracking</span>
        </div>
      </section>
      {_workbench_form(catalog)}
      <p class="footer-link"><a href="/review">Back to reviewer sandbox</a></p>
    """
    return HTMLResponse(_workbench_page("OrbitMind Mission Workbench", body))


@router.post("/workbench/run", response_class=HTMLResponse)
async def run_mission_workbench(request: Request, container: ContainerDep) -> HTMLResponse:
    """Validate one offline request and render deterministic geometric windows."""

    try:
        form = await _parse_workbench_form(request)
    except WorkbenchBodyTooLarge as exc:
        return _workbench_error(str(exc), status_code=413)
    except WorkbenchFormError as exc:
        return _workbench_error(str(exc), status_code=422)

    try:
        source = _resolve_workbench_source(form, container)
    except (OrbitMindError, PydanticValidationError, ValueError):
        return _workbench_error(
            "The selected offline orbital source could not be validated.",
            status_code=422,
        )

    try:
        observer = ObserverLocation(
            latitude_deg=form.observer_latitude_deg,
            longitude_deg=form.observer_longitude_deg,
            altitude_metres=form.observer_altitude_metres,
        )
        mission_request = MissionWindowRequest(
            orbital_source=source.elements,
            trajectory_reference=source.stable_identity,
            observer=observer,
            start_time=form.start_time_utc,
            end_time=form.start_time_utc + timedelta(hours=form.duration_hours),
            minimum_elevation_deg=form.minimum_elevation_deg,
            coarse_step_seconds=WORKBENCH_COARSE_STEP_SECONDS,
        )
    except (PydanticValidationError, ValueError):
        return _workbench_error(
            "The mission-window request is outside the supported scientific bounds.",
            status_code=422,
        )

    try:
        result = container.mission_window_service.calculate(mission_request)
    except (OrbitMindError, PydanticValidationError, ValueError):
        return _workbench_error(
            "The mission-window calculation could not complete safely.",
            status_code=422,
        )
    except Exception:  # pragma: no cover - final bounded browser failure boundary.
        return _workbench_error(
            "The mission-window calculation could not complete safely.",
            status_code=500,
        )

    return HTMLResponse(
        _workbench_page(
            "OrbitMind Mission Workbench Result",
            _result_page(source=source, result=result),
        )
    )


@router.post("/workbench/replay", response_class=HTMLResponse)
async def replay_mission_workbench(request: Request, container: ContainerDep) -> HTMLResponse:
    """Render a display-only animated replay over server-generated trajectory samples."""

    try:
        form = await _parse_workbench_form(request)
    except WorkbenchBodyTooLarge as exc:
        return _workbench_error(str(exc), status_code=413)
    except WorkbenchFormError as exc:
        return _workbench_error(str(exc), status_code=422)

    try:
        source = _resolve_workbench_source(form, container)
    except (OrbitMindError, PydanticValidationError, ValueError):
        return _workbench_error(
            "The selected offline orbital source could not be validated.",
            status_code=422,
        )

    try:
        replay_request = TrajectoryReplayRequest(
            orbital_source=source.elements,
            trajectory_reference=source.stable_identity,
            observer=_replay_observer(form),
            start_time=form.start_time_utc,
            end_time=form.start_time_utc + timedelta(hours=form.duration_hours),
            sample_interval_seconds=_replay_sample_interval_seconds(form.duration_hours),
            maximum_samples=MAX_REPLAY_SAMPLES,
        )
    except (PydanticValidationError, ValueError):
        return _workbench_error(
            "The trajectory replay request is outside the supported scientific bounds.",
            status_code=422,
        )

    try:
        result = container.trajectory_replay_service.calculate(replay_request)
        projection = build_replay_display_projection(result)
    except (OrbitMindError, PydanticValidationError, ValueError):
        return _workbench_error(
            "The trajectory replay calculation could not complete safely.",
            status_code=422,
        )
    except Exception:  # pragma: no cover - final bounded browser failure boundary.
        return _workbench_error(
            "The trajectory replay calculation could not complete safely.",
            status_code=500,
        )

    page = _workbench_page(
        "OrbitMind Trajectory Replay",
        _replay_page(source=source, result=result, projection=projection),
    )
    if len(page.encode("utf-8")) > MAX_REPLAY_HTML_BYTES:
        return _workbench_error(
            "The trajectory replay response exceeds the supported display size.",
            status_code=413,
        )
    return HTMLResponse(page)


def _workbench_form(catalog: tuple[BundledOfflineCatalogEntry, ...]) -> str:
    options = "".join(
        f'<option value="{escape(entry.sample_id, quote=True)}">'
        f"{escape(entry.display_name)} ({escape(entry.sample_id)})</option>"
        for entry in catalog
    )
    return f"""
      <form method="post" action="/workbench/run" class="workbench-form">
        <fieldset>
          <legend>1. Satellite or spacecraft</legend>
          <div class="source-grid">
            <div class="source-option">
              <label class="radio-label">
                <input type="radio" name="source_mode" value="catalog" required>
                Offline catalog
              </label>
              <label>Bundled sample
                <select name="catalog_sample_id">
                  <option value="">Select a reviewed offline sample</option>
                  {options}
                </select>
              </label>
              <p class="helper">Bounded local fixtures only. No provider or network fetch.</p>
            </div>
            <div class="source-option">
              <label class="radio-label">
                <input type="radio" name="source_mode" value="custom" required>
                Custom offline TLE
              </label>
              <label>Optional safe label
                <input name="custom_label" maxlength="80" autocomplete="off">
              </label>
              <label>TLE line 1
                <textarea name="tle_line1" maxlength="100" spellcheck="false"></textarea>
              </label>
              <label>TLE line 2
                <textarea name="tle_line2" maxlength="100" spellcheck="false"></textarea>
              </label>
              <p class="helper">TLE text stays in this request and is not persisted or shown in
              the result.</p>
            </div>
          </div>
        </fieldset>
        <fieldset>
          <legend>2. Observer</legend>
          <div class="form-grid">
            <label>Latitude (degrees)
              <input name="observer_latitude_deg" inputmode="decimal" value="0" required>
            </label>
            <label>Longitude (degrees)
              <input name="observer_longitude_deg" inputmode="decimal" value="0" required>
            </label>
            <label>Altitude (metres)
              <input name="observer_altitude_metres" inputmode="decimal" value="0" required>
            </label>
          </div>
          <p class="helper">The zero values are explicit examples, not an inferred location.</p>
        </fieldset>
        <fieldset>
          <legend>3. Analysis interval</legend>
          <div class="form-grid">
            <label>Start time (UTC)
              <input name="start_time_utc" value="2019-12-09T17:00:00Z" required>
            </label>
            <label>Duration (hours, 1-24)
              <input name="duration_hours" type="number" min="1" max="24" step="0.25"
                value="6" required>
            </label>
            <label>Minimum elevation (degrees)
              <input name="minimum_elevation_deg" type="number" min="0" max="89.9"
                step="0.1" value="10" required>
            </label>
          </div>
          <p class="helper">Enter an explicit UTC timestamp ending in Z or +00:00. Server local
          time is never substituted.</p>
        </fieldset>
        <div class="action-row">
          <button class="button" type="submit">Calculate Mission Windows</button>
          <button class="button secondary-button" type="submit"
            formaction="/workbench/replay">Replay Predicted Trajectory</button>
          <span class="helper">Geometric windows only; optical visibility is not assessed.</span>
        </div>
      </form>
    """


async def _parse_workbench_form(request: Request) -> WorkbenchForm:
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_WORKBENCH_BODY_BYTES:
            raise WorkbenchBodyTooLarge("The submitted form exceeds the 4096-byte limit.")
    try:
        encoded = bytes(body).decode("utf-8")
        parsed = parse_qs(
            encoded,
            keep_blank_values=True,
            max_num_fields=len(_WORKBENCH_FORM_FIELDS) + 2,
        )
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorkbenchFormError("The submitted form could not be parsed safely.") from exc
    if set(parsed) - _WORKBENCH_FORM_FIELDS:
        raise WorkbenchFormError("The submitted form contains an unexpected field.")

    source_mode = _single_form_value(parsed, "source_mode")
    if source_mode not in _WORKBENCH_SOURCE_MODES:
        raise WorkbenchFormError("Choose exactly one offline source mode.")
    catalog_sample_id = _single_form_value(parsed, "catalog_sample_id")
    custom_label_raw = _single_form_value(parsed, "custom_label")
    tle_line1 = _single_form_value(parsed, "tle_line1")
    tle_line2 = _single_form_value(parsed, "tle_line2")

    if source_mode == "catalog":
        if not catalog_sample_id or custom_label_raw or tle_line1 or tle_line2:
            raise WorkbenchFormError("Choose exactly one offline source mode.")
    elif catalog_sample_id or not tle_line1 or not tle_line2:
        raise WorkbenchFormError("Choose exactly one offline source mode.")

    custom_label = custom_label_raw or None
    if custom_label is not None and (
        _SAFE_WORKBENCH_LABEL.fullmatch(custom_label) is None
        or _UNSAFE_WORKBENCH_LABEL.search(custom_label) is not None
    ):
        raise WorkbenchFormError("The custom label contains unsupported characters.")

    latitude = _finite_form_float(parsed, "observer_latitude_deg")
    longitude = _finite_form_float(parsed, "observer_longitude_deg")
    altitude = _finite_form_float(parsed, "observer_altitude_metres")
    duration = _finite_form_float(parsed, "duration_hours")
    minimum_elevation = _finite_form_float(parsed, "minimum_elevation_deg")
    if not -90.0 <= latitude <= 90.0:
        raise WorkbenchFormError("Observer latitude must be between -90 and 90 degrees.")
    if not -180.0 <= longitude <= 180.0:
        raise WorkbenchFormError("Observer longitude must be between -180 and 180 degrees.")
    if not -500.0 <= altitude <= 9_000.0:
        raise WorkbenchFormError("Observer altitude must be between -500 and 9000 metres.")
    if not 1.0 <= duration <= 24.0:
        raise WorkbenchFormError("Duration must be between 1 and 24 hours.")
    if not 0.0 <= minimum_elevation < 90.0:
        raise WorkbenchFormError("Minimum elevation must be at least 0 and below 90 degrees.")

    return WorkbenchForm(
        source_mode=source_mode,
        catalog_sample_id=catalog_sample_id,
        custom_label=custom_label,
        tle_line1=tle_line1,
        tle_line2=tle_line2,
        observer_latitude_deg=latitude,
        observer_longitude_deg=longitude,
        observer_altitude_metres=altitude,
        start_time_utc=_utc_form_datetime(parsed, "start_time_utc"),
        duration_hours=duration,
        minimum_elevation_deg=minimum_elevation,
    )


def _single_form_value(
    parsed: dict[str, list[str]],
    field: str,
    *,
    required: bool = False,
) -> str:
    values = parsed.get(field, [])
    if len(values) > 1:
        raise WorkbenchFormError(f"The {field} field must be supplied once.")
    value = values[0].strip() if values else ""
    if required and not value:
        raise WorkbenchFormError(f"The {field} field is required.")
    return value


def _finite_form_float(parsed: dict[str, list[str]], field: str) -> float:
    value = _single_form_value(parsed, field, required=True)
    try:
        number = float(value)
    except ValueError as exc:
        raise WorkbenchFormError(f"The {field} field must be a number.") from exc
    if not math.isfinite(number):
        raise WorkbenchFormError(f"The {field} field must be finite.")
    return number


def _utc_form_datetime(parsed: dict[str, list[str]], field: str) -> datetime:
    value = _single_form_value(parsed, field, required=True)
    if len(value) > 40:
        raise WorkbenchFormError("The analysis start time is invalid.")
    try:
        parsed_time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkbenchFormError("The analysis start time must be an ISO UTC timestamp.") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset() is None:
        raise WorkbenchFormError("The analysis start time must include an explicit UTC offset.")
    if parsed_time.utcoffset() != timedelta(0):
        raise WorkbenchFormError("The analysis start time must use UTC (Z or +00:00).")
    return parsed_time.astimezone(UTC)


def _resolve_workbench_source(
    form: WorkbenchForm,
    container: AppContainer,
) -> ResolvedWorkbenchSource:
    if form.source_mode == "catalog":
        entry = get_bundled_offline_catalog_entry(
            container.registry,
            form.catalog_sample_id,
        )
        sample = resolve_bundled_observation_sample(container.registry, entry.sample_id)
        satellite_id = str(sample.request["satellite_id"])
        source = container.registry.get_source_record(satellite_id)
        line1, line2 = container.registry.get_tle(satellite_id)
        return ResolvedWorkbenchSource(
            elements=PinnedOrbitElementSet(
                source=source,
                tle_line1=line1,
                tle_line2=line2,
            ),
            display_label=entry.display_name,
            stable_identity=f"offline-catalog:{entry.sample_id}",
            source_mode_label="Bundled offline catalog",
        )

    resolved = resolve_custom_offline_tle(
        satellite_label=form.custom_label,
        tle_line1=form.tle_line1,
        tle_line2=form.tle_line2,
    )
    checksum = resolved.elements.element_checksum
    return ResolvedWorkbenchSource(
        elements=resolved.elements,
        display_label=resolved.elements.source.name,
        stable_identity=f"custom-tle:{checksum}",
        source_mode_label="User-provided offline TLE",
    )


def _replay_observer(form: WorkbenchForm) -> GeodeticPosition:
    return GeodeticPosition(
        latitude_deg=form.observer_latitude_deg,
        longitude_deg=form.observer_longitude_deg,
        altitude_km=form.observer_altitude_metres / 1000.0,
    )


def _replay_sample_interval_seconds(duration_hours: float) -> int:
    if duration_hours <= 6.0:
        return 15
    if duration_hours <= 12.0:
        return 30
    return 60


def _replay_page(
    *,
    source: ResolvedWorkbenchSource,
    result: TrajectoryReplayResult,
    projection: ReplayDisplayProjection,
) -> str:
    return f"""
      <section class="hero result-lead">
        <div>
          <p class="eyebrow">Offline predicted trajectory replay</p>
          <h1>{escape(source.display_label)}</h1>
          <p>{escape(PREDICTED_REPLAY_LIMITATION)}</p>
          <p>{escape(PINNED_MODEL_STATEMENT)}</p>
        </div>
        <div class="badges">
          <span class="badge">Offline orbital source</span>
          <span class="badge">Predicted trajectory</span>
          <span class="badge warn">Not live tracking</span>
        </div>
      </section>
      {_replay_svg_panel(result, projection)}
      <section class="grid section-gap">
        {_replay_source_summary(source, result)}
        {_replay_accuracy_card(result)}
      </section>
      {_replay_method_and_evidence(source, result)}
      <script id="trajectory-replay-data" type="application/json">{projection.payload_json}</script>
      <script>{_replay_controller_script()}</script>
      <p class="footer-link"><a href="/workbench">Calculate another mission window</a> ·
      <a href="/review">Reviewer sandbox</a></p>
    """


def _replay_svg_panel(result: TrajectoryReplayResult, projection: ReplayDisplayProjection) -> str:
    polylines = "\n".join(
        f'          <polyline class="track-line" points="{escape_attr(points)}"></polyline>'
        for points in projection.polyline_points
    )
    observer_label = (
        f"Observer at {result.observer.latitude_deg:.4f} degrees latitude and "
        f"{result.observer.longitude_deg:.4f} degrees longitude"
        if result.observer is not None
        else "Observer"
    )
    first = result.samples[0]
    return f"""
      <section class="replay-panel section-gap" aria-labelledby="replay-heading">
        <div>
          <p class="eyebrow">Predicted ground track</p>
          <h2 id="replay-heading">Trajectory replay</h2>
          <p class="helper">Schematic equirectangular display. Playback speed changes only the
          visualization; scientific timestamps and samples are unchanged.</p>
        </div>
        <div class="replay-svg-wrap">
          <svg class="replay-svg" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" role="img"
            aria-labelledby="trajectory-title trajectory-description">
            <title id="trajectory-title">Predicted trajectory ground track</title>
            <desc id="trajectory-description">Server-generated predicted trajectory samples
            shown on a schematic latitude and longitude grid. This is not live tracking.</desc>
            {_svg_graticule()}
{polylines}
            <circle id="observer-marker" class="observer-marker"
              cx="{projection.observer_x:.3f}" cy="{projection.observer_y:.3f}" r="7">
              <title>{escape(observer_label)}</title>
            </circle>
            <circle id="satellite-marker" class="satellite-marker"
              cx="{_sample_x(projection, first.sequence):.3f}"
              cy="{_sample_y(projection, first.sequence):.3f}" r="8">
              <title>Selected predicted sample</title>
            </circle>
          </svg>
        </div>
        {_replay_controls(result)}
        <p id="trajectory-replay-error" class="replay-error" role="status">Replay controls are
        unavailable because the embedded display payload was not accepted.</p>
        <noscript><p class="noscript-note">The trajectory and scientific summary are available,
        but playback controls require local JavaScript.</p></noscript>
        {_replay_readout(result)}
      </section>
    """


def _svg_graticule() -> str:
    vertical = "\n".join(
        f'            <line class="graticule" x1="{((lon + 180) / 360) * SVG_WIDTH:.2f}" '
        f'y1="0" x2="{((lon + 180) / 360) * SVG_WIDTH:.2f}" y2="{SVG_HEIGHT}"></line>'
        for lon in range(-120, 181, 60)
    )
    horizontal = "\n".join(
        f'            <line class="graticule" x1="0" y1="{((90 - lat) / 180) * SVG_HEIGHT:.2f}" '
        f'x2="{SVG_WIDTH}" y2="{((90 - lat) / 180) * SVG_HEIGHT:.2f}"></line>'
        for lat in range(-60, 61, 30)
    )
    return f"""
            <rect x="0" y="0" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="#f8fbfc"></rect>
            {vertical}
            {horizontal}
            <line class="guide-strong" x1="500" y1="0" x2="500" y2="{SVG_HEIGHT}"></line>
            <line class="guide-strong" x1="0" y1="250" x2="{SVG_WIDTH}" y2="250"></line>
            <line class="guide-strong" x1="0" y1="0" x2="0" y2="{SVG_HEIGHT}"></line>
            <line class="guide-strong" x1="{SVG_WIDTH}" y1="0" x2="{SVG_WIDTH}"
              y2="{SVG_HEIGHT}"></line>
    """


def _replay_controls(result: TrajectoryReplayResult) -> str:
    last = result.sample_count - 1
    return f"""
        <div class="replay-controls requires-js">
          <button id="replay-play" class="button compact-button" type="button"
            aria-pressed="false">Play</button>
          <button id="replay-prev" class="button secondary-button compact-button"
            type="button">Previous</button>
          <label class="timeline-field">Timeline
            <input id="replay-slider" type="range" min="0" max="{last}" value="0" step="1"
              aria-valuemin="1" aria-valuemax="{result.sample_count}" aria-valuenow="1"
              aria-valuetext="Sample 1 of {result.sample_count}">
          </label>
          <button id="replay-next" class="button secondary-button compact-button"
            type="button">Next</button>
          <label>Visualization speed
            <select id="replay-speed">
              <option value="0.5">0.5x</option>
              <option value="1" selected>1x</option>
              <option value="2">2x</option>
              <option value="4">4x</option>
            </select>
          </label>
        </div>
    """


def _replay_readout(result: TrajectoryReplayResult) -> str:
    first = result.samples[0]
    observer_values = ""
    if first.observer_azimuth_deg is not None:
        if first.observer_elevation_deg is None or first.observer_slant_range_km is None:
            raise ValueError("observer replay sample is incomplete")
        observer_values = (
            f"{_metric('Azimuth', _format_direction(first.observer_azimuth_deg))}"
            f"{_metric('Elevation', f'{first.observer_elevation_deg:.2f}°')}"
            f"{_metric('Range', f'{first.observer_slant_range_km:.2f} km')}"
        )
    return f"""
        <div class="readout-grid" aria-live="polite" aria-atomic="true">
          {_metric("Sample", f"1 of {result.sample_count}")}
          {_metric("UTC timestamp", _format_display_utc(first.timestamp))}
          {_metric("Geodetic latitude", f"{first.latitude_deg:.4f}°")}
          {_metric("Canonical longitude", f"{first.longitude_deg:.4f}°")}
          {_metric("WGS84 altitude", f"{first.altitude_km:.3f} km")}
          {observer_values}
        </div>
    """


def _replay_source_summary(
    source: ResolvedWorkbenchSource,
    result: TrajectoryReplayResult,
) -> str:
    if result.observer is None:
        raise ValueError("trajectory replay result is missing observer values")
    return f"""
      <section class="card">
        <h2>Source and interval</h2>
        <dl>
          <dt>Object</dt><dd>{escape(result.source_identity.object_label)}</dd>
          <dt>Stable source identity</dt><dd><code>{escape(source.stable_identity)}</code></dd>
          <dt>Source mode</dt><dd>{escape(source.source_mode_label)}</dd>
          <dt>NORAD catalog ID</dt>
          <dd>{_optional_number(result.source_identity.norad_catalog_id)}</dd>
          <dt>Source epoch</dt><dd>{_format_utc(result.source_identity.source_epoch)}</dd>
          <dt>Source age at replay start</dt><dd>{_format_replay_source_age(result)}</dd>
          <dt>Replay start</dt><dd>{_format_utc(result.request_start)}</dd>
          <dt>Replay end</dt><dd>{_format_utc(result.request_end)}</dd>
          <dt>Selected sampling interval</dt><dd>{result.sample_interval_seconds} seconds</dd>
          <dt>Samples</dt><dd>{result.sample_count}</dd>
          <dt>Track segments</dt><dd>{len(result.track_segments)}</dd>
          <dt>Observer latitude</dt><dd>{result.observer.latitude_deg:.8f}°</dd>
          <dt>Observer longitude</dt><dd>{result.observer.longitude_deg:.8f}°</dd>
          <dt>Observer altitude</dt><dd>{result.observer.altitude_km:.6f} km</dd>
        </dl>
      </section>
    """


def _replay_accuracy_card(result: TrajectoryReplayResult) -> str:
    end_offset = _format_offset(abs(result.source_end_offset_seconds))
    return f"""
      <section class="card soft">
        <h2>Accuracy and limitations</h2>
        <dl>
          <dt>Prediction offset at end</dt><dd>{end_offset}</dd>
          <dt>Propagator</dt>
          <dd><code>{escape(result.source_identity.propagator_identifier)}</code></dd>
          <dt>Frame/geodetic model</dt>
          <dd><code>{escape(result.source_identity.frame_model_identifier)}</code></dd>
          <dt>Observer geometry</dt>
          <dd><code>{escape(result.source_identity.observer_geometry_identifier)}</code></dd>
          <dt>Payload size</dt><dd>Bounded compact display JSON</dd>
        </dl>
        <ul class="limitations">
          <li>{escape(PREDICTED_REPLAY_LIMITATION)}</li>
          <li>{escape(PINNED_MODEL_STATEMENT)}</li>
          <li>Source age affects prediction usefulness.</li>
          <li>UTC is used as a UT1 approximation; no external Earth-orientation or polar-motion
          corrections are applied.</li>
          <li>WGS84 ellipsoid altitude is shown; this is not a guaranteed true current state.</li>
          <li>No universal position-error guarantee is provided.</li>
          <li>No optical visibility, collision, maneuver, command, safety, or certification
          authority is provided.</li>
        </ul>
      </section>
    """


def _replay_method_and_evidence(
    source: ResolvedWorkbenchSource,
    result: TrajectoryReplayResult,
) -> str:
    if result.observer is None:
        raise ValueError("trajectory replay result is missing observer values")
    limitations = "".join(f"<li>{escape(item)}</li>" for item in result.limitations)
    return f"""
      <details class="section-gap">
        <summary>Method and evidence</summary>
        <div class="grid">
          <div>
            <h3>Deterministic replay references</h3>
            <dl>
              <dt>Input reference</dt><dd><code>{escape(result.input_reference)}</code></dd>
              <dt>Result reference</dt><dd><code>{escape(result.result_reference)}</code></dd>
              <dt>Source checksum</dt>
              <dd><code>{escape(result.source_identity.source_checksum)}</code></dd>
              <dt>Element checksum</dt>
              <dd><code>{escape(source.elements.element_checksum)}</code></dd>
              <dt>Source reference</dt>
              <dd><code>{escape(result.source_identity.trajectory_reference)}</code></dd>
              <dt>Schema</dt><dd><code>{escape(result.schema_version)}</code></dd>
              <dt>Engine</dt><dd><code>{escape(result.engine_version)}</code></dd>
              <dt>Propagator</dt>
              <dd><code>{escape(result.source_identity.propagator_identifier)}</code></dd>
              <dt>Frame/geodetic</dt>
              <dd><code>{escape(result.source_identity.frame_model_identifier)}</code></dd>
              <dt>Observer geometry</dt>
              <dd><code>{escape(result.source_identity.observer_geometry_identifier)}</code></dd>
            </dl>
          </div>
          <div>
            <h3>Exact request</h3>
            <dl>
              <dt>Start</dt><dd>{_format_utc(result.request_start)}</dd>
              <dt>End</dt><dd>{_format_utc(result.request_end)}</dd>
              <dt>Sampling interval</dt><dd>{result.sample_interval_seconds} seconds</dd>
              <dt>Maximum sample bound</dt><dd>{result.maximum_samples}</dd>
              <dt>Observer latitude</dt><dd>{result.observer.latitude_deg:.8f}°</dd>
              <dt>Observer longitude</dt><dd>{result.observer.longitude_deg:.8f}°</dd>
              <dt>Observer altitude</dt><dd>{result.observer.altitude_km:.6f} km</dd>
            </dl>
          </div>
        </div>
        <h3 class="section-gap">Full limitation set</h3>
        <ul class="limitations">{limitations}</ul>
      </details>
    """


def _replay_controller_script() -> str:
    return """
(function () {
  "use strict";
  const dataNode = document.getElementById("trajectory-replay-data");
  const marker = document.getElementById("satellite-marker");
  const slider = document.getElementById("replay-slider");
  const playButton = document.getElementById("replay-play");
  const previousButton = document.getElementById("replay-prev");
  const nextButton = document.getElementById("replay-next");
  const speedSelect = document.getElementById("replay-speed");
  const errorBox = document.getElementById("trajectory-replay-error");
  const values = Array.from(document.querySelectorAll(".readout-grid .metric-value"));
  let payload;
  let sampleIndex = 0;
  let playing = false;
  let startedAt = 0;
  const baseMs = 30000;

  function fail() {
    playing = false;
    playButton.disabled = true;
    previousButton.disabled = true;
    nextButton.disabled = true;
    slider.disabled = true;
    speedSelect.disabled = true;
    errorBox.style.display = "block";
  }

  function isGoodSample(sample, index) {
    return sample && sample.sequence === index && Number.isFinite(sample.x) &&
      Number.isFinite(sample.y) && typeof sample.timestamp_utc === "string" &&
      Number.isFinite(sample.latitude_deg) && Number.isFinite(sample.longitude_deg) &&
      Number.isFinite(sample.altitude_km);
  }

  function setValue(index, value) {
    if (values[index]) {
      values[index].textContent = value;
    }
  }

  function show(index) {
    const sample = payload.samples[index];
    if (!isGoodSample(sample, index)) {
      fail();
      return;
    }
    sampleIndex = index;
    marker.setAttribute("cx", String(sample.x));
    marker.setAttribute("cy", String(sample.y));
    slider.value = String(index);
    slider.setAttribute("aria-valuenow", String(index + 1));
    slider.setAttribute("aria-valuetext", "Sample " + String(index + 1) +
      " of " + String(payload.sample_count));
    setValue(0, String(index + 1) + " of " + String(payload.sample_count));
    setValue(1, sample.timestamp_utc.replace("T", " ").replace("Z", " UTC"));
    setValue(2, sample.latitude_deg.toFixed(4) + "°");
    setValue(3, sample.longitude_deg.toFixed(4) + "°");
    setValue(4, sample.altitude_km.toFixed(3) + " km");
    if (Object.prototype.hasOwnProperty.call(sample, "azimuth_deg")) {
      setValue(5, sample.azimuth_deg.toFixed(2) + "°");
      setValue(6, sample.elevation_deg.toFixed(2) + "°");
      setValue(7, sample.range_km.toFixed(2) + " km");
    }
  }

  function setPlaying(next) {
    playing = next;
    playButton.textContent = playing ? "Pause" : "Play";
    playButton.setAttribute("aria-pressed", playing ? "true" : "false");
    if (playing) {
      startedAt = performance.now() - (sampleIndex / Math.max(payload.sample_count - 1, 1)) *
        baseMs / Number(speedSelect.value);
      requestAnimationFrame(tick);
    }
  }

  function tick(now) {
    if (!playing) {
      return;
    }
    const speed = Number(speedSelect.value);
    const progress = Math.min((now - startedAt) / (baseMs / speed), 1);
    const nextIndex = Math.round(progress * (payload.sample_count - 1));
    show(nextIndex);
    if (progress >= 1) {
      setPlaying(false);
      return;
    }
    requestAnimationFrame(tick);
  }

  try {
    payload = JSON.parse(dataNode.textContent);
    if (!payload || payload.schema_version !== "trajectory-replay-display-v1" ||
        !Array.isArray(payload.samples) || payload.samples.length !== payload.sample_count ||
        payload.sample_count < 2) {
      fail();
      return;
    }
    for (let index = 0; index < payload.samples.length; index += 1) {
      if (!isGoodSample(payload.samples[index], index)) {
        fail();
        return;
      }
    }
  } catch {
    fail();
    return;
  }

  playButton.addEventListener("click", function () {
    if (!playing && sampleIndex === payload.sample_count - 1) {
      show(0);
    }
    setPlaying(!playing);
  });
  previousButton.addEventListener("click", function () {
    setPlaying(false);
    show(Math.max(sampleIndex - 1, 0));
  });
  nextButton.addEventListener("click", function () {
    setPlaying(false);
    show(Math.min(sampleIndex + 1, payload.sample_count - 1));
  });
  slider.addEventListener("input", function () {
    setPlaying(false);
    show(Number(slider.value));
  });
  speedSelect.addEventListener("change", function () {
    if (playing) {
      setPlaying(false);
    }
  });
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    setPlaying(false);
  }
  show(0);
}());
"""


def _sample_x(projection: ReplayDisplayProjection, sequence: int) -> float:
    first_segment = projection.polyline_points[0].split()[sequence]
    return float(first_segment.split(",", maxsplit=1)[0])


def _sample_y(projection: ReplayDisplayProjection, sequence: int) -> float:
    first_segment = projection.polyline_points[0].split()[sequence]
    return float(first_segment.split(",", maxsplit=1)[1])


def _result_page(*, source: ResolvedWorkbenchSource, result: MissionWindowResult) -> str:
    lead = _primary_window(result.windows[0]) if result.windows else _no_window_state(result)
    all_windows = _all_windows_table(result) if len(result.windows) > 1 else ""
    return f"""
      <section class="hero result-lead">
        <div>
          <p class="eyebrow">Offline mission-window result</p>
          <h1>{escape(source.display_label)}</h1>
          <p>{escape(result.model_statement)}</p>
        </div>
        <div class="badges">
          <span class="badge">Offline orbital source</span>
          <span class="badge">Predicted geometry</span>
          <span class="badge warn">{result.window_count} qualifying window(s)</span>
        </div>
      </section>
      {lead}
      <section class="grid section-gap">
        {_identity_card(source, result)}
        {_accuracy_card(result)}
      </section>
      {all_windows}
      {_method_and_evidence(result)}
      <p class="footer-link"><a href="/workbench">Calculate another mission window</a> ·
      <a href="/review">Reviewer sandbox</a></p>
    """


def _primary_window(event: MissionWindowEvent) -> str:
    classification = _classification_label(event)
    rise_label = "Rise / boundary" if event.begins_before_requested_interval else "Rise"
    set_label = "Set / boundary" if event.ends_after_requested_interval else "Set"
    return f"""
      <section class="next-window" aria-labelledby="next-window-heading">
        <p class="eyebrow">Next predicted pass/contact window</p>
        <h2 id="next-window-heading">{escape(classification)}</h2>
        <div class="metric-grid">
          {_metric(rise_label, _format_display_utc(event.rise_time))}
          {_metric("Peak", _format_display_utc(event.peak_time))}
          {_metric(set_label, _format_display_utc(event.set_time))}
          {_metric("Maximum elevation", f"{event.maximum_elevation_deg:.2f}°")}
          {_metric("Duration", _format_duration(event.duration_seconds))}
          {_metric("Rise direction", _format_direction(event.rise_azimuth_deg))}
          {_metric("Peak direction", _format_direction(event.peak_azimuth_deg))}
          {_metric("Set direction", _format_direction(event.set_azimuth_deg))}
        </div>
      </section>
    """


def _no_window_state(result: MissionWindowResult) -> str:
    return f"""
      <section class="next-window empty-state" aria-labelledby="no-window-heading">
        <p class="eyebrow">Calculation completed</p>
        <h2 id="no-window-heading">{NO_WINDOW_MESSAGE}</h2>
        <p>Try lowering the minimum elevation threshold or expanding the interval within the
        24-hour bound.</p>
        <div class="metric-grid">
          {_metric("Requested start", _format_display_utc(result.request_start))}
          {_metric("Requested end", _format_display_utc(result.request_end))}
          {_metric("Minimum elevation", f"{result.minimum_elevation_deg:.2f}°")}
          {_metric("Source epoch", _format_optional_utc(result.source_epoch))}
        </div>
      </section>
    """


def _identity_card(source: ResolvedWorkbenchSource, result: MissionWindowResult) -> str:
    return f"""
      <section class="card">
        <h2>Object and request</h2>
        <dl>
          <dt>Object</dt><dd>{escape(result.source_identity.object_name)}</dd>
          <dt>Stable source identity</dt><dd><code>{escape(source.stable_identity)}</code></dd>
          <dt>Source mode</dt><dd>{escape(source.source_mode_label)}</dd>
          <dt>NORAD catalog ID</dt>
          <dd>{_optional_number(result.source_identity.norad_catalog_id)}</dd>
          <dt>Source epoch</dt><dd>{_format_optional_utc(result.source_epoch)}</dd>
          <dt>Source age at start</dt><dd>{_format_source_age(result)}</dd>
          <dt>Analysis start</dt><dd>{_format_utc(result.request_start)}</dd>
          <dt>Analysis end</dt><dd>{_format_utc(result.request_end)}</dd>
          <dt>Minimum elevation</dt><dd>{result.minimum_elevation_deg:.2f}°</dd>
        </dl>
      </section>
    """


def _accuracy_card(result: MissionWindowResult) -> str:
    return f"""
      <section class="card soft">
        <h2>Accuracy and limitations</h2>
        <dl>
          <dt>Source epoch</dt><dd>{_format_optional_utc(result.source_epoch)}</dd>
          <dt>Maximum prediction offset</dt><dd>{_format_maximum_prediction_offset(result)}</dd>
          <dt>Propagator</dt><dd><code>{escape(result.propagation_model)}</code></dd>
          <dt>Geometry model</dt><dd><code>{escape(result.geometry_model)}</code></dd>
          <dt>Event tolerance</dt><dd>{result.event_time_tolerance_seconds:.1f} seconds</dd>
          <dt>Coarse sample step</dt><dd>{result.coarse_step_seconds} seconds</dd>
        </dl>
        <ul class="limitations">
          <li>Geometric window only; optical visibility is not assessed.</li>
          <li>Not live tracking and no guaranteed visibility.</li>
          <li>Not certified for command, collision, or safety decisions.</li>
          <li>{EARTH_ORIENTATION_LIMITATION}</li>
        </ul>
      </section>
    """


def _all_windows_table(result: MissionWindowResult) -> str:
    rows = "".join(
        f"""
          <tr>
            <td>{index}</td>
            <td>{_format_utc(event.rise_time)}</td>
            <td>{_format_utc(event.peak_time)}</td>
            <td>{_format_utc(event.set_time)}</td>
            <td>{event.maximum_elevation_deg:.2f}°</td>
            <td>{_format_duration(event.duration_seconds)}</td>
            <td>{_format_direction(event.rise_azimuth_deg)} →
              {_format_direction(event.set_azimuth_deg)}</td>
            <td>{escape(_classification_label(event))}</td>
          </tr>
        """
        for index, event in enumerate(result.windows, start=1)
    )
    return f"""
      <section class="card section-gap">
        <h2>All qualifying windows</h2>
        <div class="table-wrap">
          <table class="window-table">
            <thead><tr><th>#</th><th>Rise / boundary (UTC)</th><th>Peak (UTC)</th>
            <th>Set / boundary (UTC)</th><th>Maximum elevation</th><th>Duration</th>
            <th>Direction</th><th>Classification</th></tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </section>
    """


def _method_and_evidence(result: MissionWindowResult) -> str:
    limitations = "".join(f"<li>{escape(item)}</li>" for item in result.limitations)
    return f"""
      <details class="section-gap">
        <summary>Method and evidence</summary>
        <div class="grid">
          <div>
            <h3>Deterministic references</h3>
            <dl>
              <dt>Input reference</dt><dd><code>{escape(result.input_reference)}</code></dd>
              <dt>Result reference</dt><dd><code>{escape(result.result_reference)}</code></dd>
              <dt>Source checksum</dt>
              <dd><code>{escape(result.source_identity.source_checksum)}</code></dd>
              <dt>Trajectory reference</dt>
              <dd><code>{escape(result.trajectory_reference)}</code></dd>
              <dt>Schema</dt><dd><code>{escape(result.schema_version)}</code></dd>
              <dt>Engine</dt><dd><code>{escape(result.engine_version)}</code></dd>
            </dl>
          </div>
          <div>
            <h3>Exact request</h3>
            <dl>
              <dt>Observer latitude</dt><dd>{result.observer.latitude_deg:.8f}°</dd>
              <dt>Observer longitude</dt><dd>{result.observer.longitude_deg:.8f}°</dd>
              <dt>Observer altitude</dt><dd>{result.observer.altitude_metres:.3f} m</dd>
              <dt>Start</dt><dd>{_format_utc(result.request_start)}</dd>
              <dt>End</dt><dd>{_format_utc(result.request_end)}</dd>
              <dt>Threshold</dt><dd>{result.minimum_elevation_deg:.8f}°</dd>
            </dl>
          </div>
        </div>
        <h3 class="section-gap">Full limitation set</h3>
        <ul class="limitations">{limitations}</ul>
      </details>
    """


def _workbench_error(message: str, *, status_code: int) -> HTMLResponse:
    body = f"""
      <section class="hero error">
        <p class="eyebrow">Mission Workbench input not accepted</p>
        <h1>Unable to calculate mission windows</h1>
        <p>{escape(message)}</p>
      </section>
      <section class="card safety">
        <h2>Safe boundary</h2>
        <p>No orbital text, stack trace, local path, environment value, or provider response is
        included in this error.</p>
      </section>
      <p class="footer-link"><a href="/workbench">Return to Mission Workbench</a></p>
    """
    return HTMLResponse(
        _workbench_page("Mission Workbench input not accepted", body),
        status_code=status_code,
    )


def _metric(label: str, value: str) -> str:
    return f"""
      <div class="metric">
        <span class="metric-label">{escape(label)}</span>
        <span class="metric-value">{escape(value)}</span>
      </div>
    """


def _classification_label(event: MissionWindowEvent) -> str:
    if event.begins_before_requested_interval and event.ends_after_requested_interval:
        return "Window spans the full requested interval"
    if event.begins_before_requested_interval:
        return "Active at analysis start"
    if event.ends_after_requested_interval:
        return "Continues after analysis end"
    return "Complete window within analysis interval"


def _format_direction(azimuth_deg: float) -> str:
    index = int((azimuth_deg + 22.5) // 45.0) % len(_COMPASS_LABELS)
    return f"{_COMPASS_LABELS[index]} ({azimuth_deg:.2f}°)"


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _format_display_utc(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " UTC"


def _format_optional_utc(value: datetime | None) -> str:
    return _format_utc(value) if value is not None else "Unavailable"


def _format_duration(seconds: float) -> str:
    whole_minutes, remaining_seconds = divmod(seconds, 60.0)
    hours, minutes = divmod(int(whole_minutes), 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    parts.append(f"{remaining_seconds:.1f} s")
    return " ".join(parts)


def _format_source_age(result: MissionWindowResult) -> str:
    offset = result.prediction_start_offset_seconds
    if offset is None:
        return "Unavailable"
    relation = "after" if offset >= 0 else "before"
    return f"{_format_offset(abs(offset))} {relation} source epoch"


def _format_replay_source_age(result: TrajectoryReplayResult) -> str:
    offset = result.source_start_offset_seconds
    relation = "after" if offset >= 0 else "before"
    return f"{_format_offset(abs(offset))} {relation} source epoch"


def _format_maximum_prediction_offset(result: MissionWindowResult) -> str:
    offsets = (
        result.prediction_start_offset_seconds,
        result.prediction_end_offset_seconds,
    )
    available = [abs(value) for value in offsets if value is not None]
    return _format_offset(max(available)) if available else "Unavailable"


def _format_offset(seconds: float) -> str:
    total_seconds = round(seconds)
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if secs or not parts:
        parts.append(f"{secs} s")
    return " ".join(parts)


def _optional_number(value: int | None) -> str:
    return str(value) if value is not None else "Unavailable"


def _workbench_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>{WORKBENCH_CSS}</style>
</head>
<body>
  <main>{body}</main>
</body>
</html>
"""
