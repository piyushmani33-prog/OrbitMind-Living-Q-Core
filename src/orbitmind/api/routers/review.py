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
from orbitmind.visualization.models import ArtifactRecord

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


@router.get("/review", response_class=HTMLResponse)
def reviewer_home() -> HTMLResponse:
    """Return the private local reviewer sandbox entry page."""

    body = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>OrbitMind Reviewer Sandbox</title>
  </head>
  <body>
    <main>
      <h1>OrbitMind Reviewer Sandbox</h1>
      <p>Run the bundled offline ISS sample and inspect the generated evidence bundle.</p>
      <section>
        <h2>Safety boundary</h2>
        {_safety_boundary_list()}
      </section>
      <form method="post" action="/review/run">
        <button type="submit">Run bundled ISS sample</button>
      </form>
      <p>Available sample id: <code>iss</code></p>
    </main>
  </body>
</html>
"""
    return HTMLResponse(body)


@router.post("/review/run", response_class=HTMLResponse)
def run_reviewer_sample(container: ContainerDep) -> HTMLResponse:
    """Run the bundled ISS sample and return a bounded HTML result."""

    result = run_sample(settings=container.settings, sample_id="iss")
    body = f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>OrbitMind Reviewer Sandbox Result</title>
  </head>
  <body>
    <main>
      <h1>OrbitMind Reviewer Sandbox Result</h1>
      {_mission_section(result)}
      {_artifact_section(result)}
      <section>
        <h2>Safety boundary</h2>
        {_safety_boundary_list()}
      </section>
      <p><a href="/review">Back to reviewer sandbox</a></p>
    </main>
  </body>
</html>
"""
    return HTMLResponse(body)


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
        artifact_path.resolve().relative_to(container.settings.resolved_artifacts_dir().resolve())
    except ValueError as exc:  # pragma: no cover - filename allowlist prevents this.
        raise NotFoundError("review artifact not found") from exc
    if not artifact_path.is_file():
        raise NotFoundError("review artifact not found")
    return FileResponse(artifact_path)


def _mission_section(result: SampleRunResult) -> str:
    mission = result.mission
    source_test_only = mission.source.test_only if mission.source is not None else None
    source_checksum = mission.source.checksum if mission.source is not None else "unavailable"
    inputs_hash = mission.provenance[0].inputs_hash if mission.provenance else "unavailable"
    first_sample = _format_sample(mission.samples[0] if mission.samples else None)
    last_sample = _format_sample(mission.samples[-1] if mission.samples else None)
    return f"""
      <section>
        <h2>Mission</h2>
        <dl>
          <dt>mission_id</dt><dd>{escape(mission.mission_id)}</dd>
          <dt>status</dt><dd>{escape(mission.status.value)}</dd>
          <dt>epistemic_status</dt><dd>{escape(mission.epistemic_status.value)}</dd>
          <dt>sample_count</dt><dd>{mission.sample_count}</dd>
          <dt>source.test_only</dt><dd>{str(source_test_only).lower()}</dd>
          <dt>source_checksum</dt><dd>{escape(source_checksum)}</dd>
          <dt>inputs_hash</dt><dd>{escape(inputs_hash)}</dd>
          <dt>first_sample</dt><dd>{escape(first_sample)}</dd>
          <dt>last_sample</dt><dd>{escape(last_sample)}</dd>
        </dl>
      </section>
"""


def _artifact_section(result: SampleRunResult) -> str:
    artifact_items = "\n".join(
        _artifact_list_item(result, artifact) for artifact in result.mission.artifacts
    )
    static_items = "\n".join(
        [
            _file_list_item(
                result.mission.mission_id,
                "static_report.json",
                result.display_static_report_path(),
                result.static_report_checksum,
            ),
            _file_list_item(
                result.mission.mission_id,
                "static_report.md",
                result.display_static_report_markdown_path(),
                result.static_report_markdown_checksum,
            ),
        ]
    )
    return f"""
      <section>
        <h2>Artifacts</h2>
        <ul>
          {artifact_items}
          {static_items}
        </ul>
      </section>
"""


def _artifact_list_item(result: SampleRunResult, artifact: ArtifactRecord) -> str:
    image_name = Path(artifact.path).name
    sidecar_name = Path(artifact.sidecar_path).name
    image_path = result.display_artifact_path(artifact)
    sidecar_path = result.display_sidecar_path(artifact)
    return "\n".join(
        [
            _file_list_item(result.mission.mission_id, image_name, image_path, artifact.checksum),
            _file_list_item(result.mission.mission_id, sidecar_name, sidecar_path, "sidecar"),
        ]
    )


def _file_list_item(
    mission_id: str,
    filename: str,
    display_path: Path,
    checksum: str,
) -> str:
    href = f"/review/artifacts/{escape(mission_id)}/{escape(filename)}"
    return (
        "<li>"
        f'<a href="{href}">{escape(filename)}</a> '
        f"<code>{escape(str(display_path))}</code> "
        f"checksum: <code>{escape(checksum)}</code>"
        "</li>"
    )


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


def _safety_boundary_list() -> str:
    items = "\n".join(f"<li>{escape(item)}</li>" for item in SAFETY_BOUNDARY_ITEMS)
    return f"<ul>{items}</ul>"
