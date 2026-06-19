"""Unit tests for visual artifact generation + sidecar metadata."""

from __future__ import annotations

import json
from pathlib import Path

from orbitmind.core.checksums import sha256_file
from orbitmind.mission.models import OutputType
from orbitmind.space.models import ScientificResult
from orbitmind.visualization.charts import VisualizationService

MISSION_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_renders_two_artifacts(scientific_result: ScientificResult, tmp_path: Path) -> None:
    service = VisualizationService(tmp_path)
    records = service.render(
        mission_id=MISSION_ID,
        result=scientific_result,
        output_types=list(OutputType),
        verification_passed=True,
    )
    assert {r.type for r in records} == set(OutputType)
    for record in records:
        image = tmp_path / record.path
        assert image.exists() and image.stat().st_size > 0


def test_sidecar_metadata_is_complete(scientific_result: ScientificResult, tmp_path: Path) -> None:
    service = VisualizationService(tmp_path)
    records = service.render(
        mission_id=MISSION_ID,
        result=scientific_result,
        output_types=[OutputType.ALTITUDE_VS_TIME],
        verification_passed=True,
    )
    record = records[0]
    sidecar = json.loads((tmp_path / record.sidecar_path).read_text(encoding="utf-8"))
    for key in (
        "artifact_type",
        "created_at",
        "mission_id",
        "source_references",
        "computation_version",
        "software_versions",
        "verification_status",
        "checksum",
    ):
        assert key in sidecar
    # The recorded checksum matches the actual image bytes.
    assert sidecar["checksum"] == record.checksum == sha256_file(tmp_path / record.path)
    # Source reference makes the test-only / not-live nature explicit.
    assert sidecar["source_references"][0]["test_only"] is True


def test_artifacts_written_under_mission_dir(
    scientific_result: ScientificResult, tmp_path: Path
) -> None:
    service = VisualizationService(tmp_path)
    records = service.render(
        mission_id=MISSION_ID,
        result=scientific_result,
        output_types=[OutputType.GROUND_TRACK],
        verification_passed=True,
    )
    assert records[0].path.startswith(MISSION_ID)
