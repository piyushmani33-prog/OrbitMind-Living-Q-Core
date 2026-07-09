"""One-command offline sample runner for the bundled ISS mission.

Run with:

    python -m orbitmind.sample

The runner uses the existing mission workflow and response projections without
starting an API server. It is local, deterministic, and sample-data only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from orbitmind.api.container import AppContainer
from orbitmind.api.routers.missions import _build_detail
from orbitmind.api.schemas import MissionDetailResponse, OrbitPropagationRequest
from orbitmind.api.static_report_schemas import MissionStaticReportResponse
from orbitmind.api.visual_manifest_schemas import MissionVisualManifestResponse
from orbitmind.core.checksums import sha256_file
from orbitmind.core.config import PROJECT_ROOT, Settings
from orbitmind.core.errors import OrbitMindError
from orbitmind.core.logging import configure_logging
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.space.models import OrbitalStateSample
from orbitmind.visualization.models import ArtifactRecord

SAMPLE_DATABASE_PATH = PROJECT_ROOT / "data" / "orbitmind_sample.db"
SAMPLE_REQUEST: dict[str, object] = {
    "satellite_id": "ISS",
    "start_time": "2019-12-09T17:00:00Z",
    "end_time": "2019-12-09T18:00:00Z",
    "step_seconds": 120,
}


@dataclass(frozen=True)
class SampleRunResult:
    """Result bundle returned by the offline sample runner."""

    mission: MissionDetailResponse
    static_report: MissionStaticReportResponse
    artifacts_root: Path
    static_report_path: Path
    static_report_checksum: str

    def artifact_path(self, artifact: ArtifactRecord) -> Path:
        """Return the absolute image path for an artifact record."""
        return self.artifacts_root / artifact.path

    def sidecar_path(self, artifact: ArtifactRecord) -> Path:
        """Return the absolute sidecar path for an artifact record."""
        return self.artifacts_root / artifact.sidecar_path

    def display_artifact_path(self, artifact: ArtifactRecord) -> Path:
        """Return a local, project-relative image path for CLI display."""
        return _display_path(self.artifact_path(artifact), self.artifacts_root)

    def display_sidecar_path(self, artifact: ArtifactRecord) -> Path:
        """Return a local, project-relative sidecar path for CLI display."""
        return _display_path(self.sidecar_path(artifact), self.artifacts_root)

    def display_static_report_path(self) -> Path:
        """Return a local, project-relative static report path for CLI display."""
        return _display_path(self.static_report_path, self.artifacts_root)


def run_sample(settings: Settings | None = None) -> SampleRunResult:
    """Run the bundled deterministic ISS sample mission without an API server."""

    effective_settings = settings or _sample_settings()
    container = AppContainer(settings=effective_settings)
    try:
        container.init_storage()
        payload = OrbitPropagationRequest.model_validate(SAMPLE_REQUEST)
        mission_id = container.orchestrator.run_orbit_mission(
            raw_request=payload.model_dump(mode="json"),
            request=payload.to_domain(),
        )
        with container.database.session() as session:
            repo = SqlAlchemyMissionRepository(session)
            source_repo = SqlAlchemySourceRepository(session)
            mission = repo.get_mission(mission_id)
            if mission is None:  # pragma: no cover - run_orbit_mission just persisted it.
                raise RuntimeError("sample mission was not found after execution")
            detail = _build_detail(mission, repo, source_repo, container.registry)
            manifest = MissionVisualManifestResponse.from_mission(
                mission=mission,
                artifacts=repo.get_artifacts(mission_id),
                findings=repo.get_findings(mission_id),
                source_data=source_repo.get_mission_source_data(mission_id),
            )
            static_report = MissionStaticReportResponse.from_manifest(manifest)
            static_report_path, static_report_checksum = _write_static_report_json(
                static_report=static_report,
                artifacts_root=effective_settings.resolved_artifacts_dir(),
                mission_id=mission_id,
            )
        return SampleRunResult(
            mission=detail,
            static_report=static_report,
            artifacts_root=effective_settings.resolved_artifacts_dir(),
            static_report_path=static_report_path,
            static_report_checksum=static_report_checksum,
        )
    finally:
        container.database.engine.dispose()


def write_summary(result: SampleRunResult, stream: TextIO = sys.stdout) -> None:
    """Write a concise, reviewer-friendly summary for a sample run."""

    mission = result.mission
    source_test_only = mission.source.test_only if mission.source is not None else None
    source_checksum = mission.source.checksum if mission.source is not None else "unavailable"
    provenance_inputs_hash = (
        mission.provenance[0].inputs_hash if mission.provenance else "unavailable"
    )
    first = mission.samples[0] if mission.samples else None
    last = mission.samples[-1] if mission.samples else None

    print("OrbitMind offline sample completed", file=stream)
    print("", file=stream)
    print("Mission", file=stream)
    print(f"  mission_id: {mission.mission_id}", file=stream)
    print(f"  status: {mission.status.value}", file=stream)
    print(f"  epistemic_status: {mission.epistemic_status.value}", file=stream)
    print(f"  sample_count: {mission.sample_count}", file=stream)
    print(f"  source.test_only: {str(source_test_only).lower()}", file=stream)
    print(f"  source_checksum: {source_checksum}", file=stream)
    print(f"  inputs_hash: {provenance_inputs_hash}", file=stream)
    _write_sample_point("first_sample", first, stream)
    _write_sample_point("last_sample", last, stream)
    print("", file=stream)
    print("Artifacts", file=stream)
    for artifact in mission.artifacts:
        print(f"  - {artifact.type.value}", file=stream)
        print(f"    local image: {result.display_artifact_path(artifact)}", file=stream)
        print(f"    local sidecar: {result.display_sidecar_path(artifact)}", file=stream)
        print(f"    checksum: {artifact.checksum}", file=stream)
    print("", file=stream)
    print("Static report", file=stream)
    print(f"  schema_version: {result.static_report.schema_version}", file=stream)
    print(f"  report_id: {result.static_report.report_id}", file=stream)
    print("  generated_on_demand: true", file=stream)
    print(f"  local file: {result.display_static_report_path()}", file=stream)
    print(f"  checksum: {result.static_report_checksum}", file=stream)
    print("", file=stream)
    print("Safety boundary", file=stream)
    print("  bundled stale sample TLE only; not live tracking; no provider fetch", file=stream)
    print("  no command readiness, approval, or certification", file=stream)
    print("  no quantum advantage claim", file=stream)


def main(argv: Sequence[str] | None = None, stdout: TextIO = sys.stdout) -> int:
    """CLI entrypoint for ``python -m orbitmind.sample``."""

    parser = argparse.ArgumentParser(
        description="Run OrbitMind's bundled offline ISS sample mission without starting the API."
    )
    parser.parse_args(argv)
    settings = _sample_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    try:
        write_summary(run_sample(settings), stdout)
    except OrbitMindError as exc:
        print(f"OrbitMind sample failed: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "OrbitMind sample failed: unexpected_error: offline sample could not complete",
            file=sys.stderr,
        )
        return 1
    return 0


def _sample_settings() -> Settings:
    return Settings(
        database_url=f"sqlite:///{SAMPLE_DATABASE_PATH.as_posix()}",
        artifacts_dir=PROJECT_ROOT / "artifacts",
        cache_dir=PROJECT_ROOT / "cache",
        env="sample",
        log_level="WARNING",
        network_enabled=False,
        celestrak_enabled=False,
        jpl_sbdb_enabled=False,
        jpl_cad_enabled=False,
        quantum_enabled=False,
    )


def _write_sample_point(label: str, sample: OrbitalStateSample | None, stream: TextIO) -> None:
    if sample is None:
        return
    if sample.latitude_deg is None or sample.longitude_deg is None or sample.altitude_km is None:
        print(f"  {label}: {sample.timestamp.isoformat()} geodetic sample unavailable", file=stream)
        return
    print(
        f"  {label}: {sample.timestamp.isoformat()} "
        f"lat={sample.latitude_deg:.6f} deg "
        f"lon={sample.longitude_deg:.6f} deg "
        f"alt={sample.altitude_km:.3f} km",
        file=stream,
    )


def _write_static_report_json(
    *,
    static_report: MissionStaticReportResponse,
    artifacts_root: Path,
    mission_id: str,
) -> tuple[Path, str]:
    report_path = artifacts_root / mission_id / "static_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        static_report.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    )
    report_path.write_text(f"{body}\n", encoding="utf-8")
    return report_path, sha256_file(report_path)


def _display_path(path: Path, artifacts_root: Path) -> Path:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        return Path("artifacts") / resolved.relative_to(artifacts_root.resolve())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
