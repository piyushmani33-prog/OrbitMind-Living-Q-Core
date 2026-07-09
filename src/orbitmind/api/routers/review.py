"""Private browser reviewer sandbox for the bundled offline sample."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse

from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_container
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.ids import is_valid_uuid
from orbitmind.sample import SampleRunResult, run_sample
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
    first_sample = _format_sample(mission.samples[0] if mission.samples else None)
    last_sample = _format_sample(mission.samples[-1] if mission.samples else None)
    return f"""
      <section class="card">
        <h2>Mission summary</h2>
        <dl>
          <dt>mission_id</dt><dd>{escape(mission.mission_id)}</dd>
          <dt>status</dt><dd>{escape(mission.status.value)}</dd>
          <dt>epistemic_status</dt><dd>{escape(mission.epistemic_status.value)}</dd>
          <dt>sample_count</dt><dd>{mission.sample_count}</dd>
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
    return f"/review/artifacts/{escape(mission_id)}/{escape(filename)}"


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


def _safety_boundary_panel() -> str:
    return f"""
      <section class="card safety">
        <h2>Safety boundary</h2>
        {_safety_boundary_list()}
      </section>
"""


def _safety_boundary_list() -> str:
    items = "\n".join(f"<li>{escape(item)}</li>" for item in SAFETY_BOUNDARY_ITEMS)
    return f"<ul>{items}</ul>"
