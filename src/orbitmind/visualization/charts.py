"""Deterministic chart rendering with JSON sidecars (offline, Agg backend)."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless, deterministic; no GUI/display required
import matplotlib.pyplot as plt

from orbitmind.core.checksums import sha256_file
from orbitmind.core.paths import mission_artifact_dir
from orbitmind.core.timeutils import utcnow
from orbitmind.mission.models import OutputType
from orbitmind.space.models import SampleStatus, ScientificResult
from orbitmind.visualization.models import ArtifactRecord


class VisualizationService:
    """Renders mission artifacts under ``artifacts_root/<mission_id>/``."""

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root

    def render(
        self,
        *,
        mission_id: str,
        result: ScientificResult,
        output_types: list[OutputType],
        verification_passed: bool,
    ) -> list[ArtifactRecord]:
        out_dir = mission_artifact_dir(self._root, mission_id)
        records: list[ArtifactRecord] = []
        for output_type in output_types:
            image_path = out_dir / f"{output_type.value}.png"
            if output_type is OutputType.GROUND_TRACK:
                self._render_ground_track(result, image_path)
            else:  # ALTITUDE_VS_TIME
                self._render_altitude(result, image_path)
            records.append(
                self._finalize(mission_id, output_type, result, image_path, verification_passed)
            )
        return records

    @staticmethod
    def _render_altitude(result: ScientificResult, path: Path) -> None:
        ok = [s for s in result.samples if s.status is SampleStatus.OK]
        times = [s.timestamp for s in ok]
        alts = [s.altitude_km for s in ok]
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.plot(times, alts, color="#1f77b4", linewidth=1.2)
        ax.set_title(f"Altitude vs Time — {result.satellite_id} (sample TLE, not live)")
        ax.set_xlabel("Time (UTC)")
        ax.set_ylabel("Altitude above WGS-84 ellipsoid (km)")
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    @staticmethod
    def _render_ground_track(result: ScientificResult, path: Path) -> None:
        ok = [s for s in result.samples if s.status is SampleStatus.OK]
        lons = [s.longitude_deg for s in ok]
        lats = [s.latitude_deg for s in ok]
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.scatter(lons, lats, s=6, color="#d62728")
        ax.set_title(f"Ground Track — {result.satellite_id} (sample TLE, not live)")
        ax.set_xlabel("Longitude (deg)")
        ax.set_ylabel("Latitude (deg)")
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)

    def _finalize(
        self,
        mission_id: str,
        output_type: OutputType,
        result: ScientificResult,
        image_path: Path,
        verification_passed: bool,
    ) -> ArtifactRecord:
        checksum = sha256_file(image_path)
        sidecar_path = image_path.with_suffix(".json")
        sidecar = {
            "artifact_type": output_type.value,
            "created_at": utcnow().isoformat(),
            "mission_id": mission_id,
            "source_references": [
                {
                    "name": result.source.source_name,
                    "satellite_id": result.source.satellite_id,
                    "epoch_utc": result.source.epoch_utc,
                    "checksum": result.source.checksum,
                    "test_only": result.source.test_only,
                    "note": "Bundled sample TLE — not live satellite data.",
                }
            ],
            "computation_version": result.computation_version,
            "software_versions": result.software_versions,
            "verification_status": "passed" if verification_passed else "failed",
            "checksum": checksum,
            "units": result.units,
        }
        sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True), encoding="utf-8")
        return ArtifactRecord(
            mission_id=mission_id,
            type=output_type,
            path=str(image_path.relative_to(self._root)),
            sidecar_path=str(sidecar_path.relative_to(self._root)),
            checksum=checksum,
        )
