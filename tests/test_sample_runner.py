"""Tests for the one-command offline sample runner."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path

import pytest

import orbitmind.sample as sample_module
from orbitmind.core.config import Settings
from orbitmind.sample import run_sample, write_summary


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{(tmp_path / 'sample.db').as_posix()}",
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        log_level="WARNING",
        network_enabled=False,
        celestrak_enabled=False,
        jpl_sbdb_enabled=False,
        jpl_cad_enabled=False,
        quantum_enabled=False,
    )


def test_run_sample_uses_existing_offline_mission_workflow(tmp_path: Path) -> None:
    result = run_sample(_settings(tmp_path))

    assert result.mission.status.value == "completed"
    assert result.mission.epistemic_status.value == "deterministic-calculation"
    assert result.mission.sample_count == 31
    assert result.mission.source is not None
    assert result.mission.source.test_only is True
    assert result.mission.provenance[0].method == "sgp4-propagation"
    assert result.mission.provenance[0].inputs_hash

    artifacts = {artifact.type.value: artifact for artifact in result.mission.artifacts}
    assert set(artifacts) == {"altitude_vs_time", "ground_track"}
    for artifact in artifacts.values():
        assert result.artifact_path(artifact).is_file()
        assert result.sidecar_path(artifact).is_file()
        assert len(artifact.checksum) == 64

    assert result.static_report.schema_version == "static-report-v1"
    assert result.static_report.scope_id == result.mission.mission_id
    assert result.static_report.mission_summary.artifact_count == 2
    expected_report_path = tmp_path / "artifacts" / result.mission.mission_id / "static_report.json"
    assert result.static_report_path == expected_report_path
    assert result.static_report_path.is_file()
    assert result.static_report_path.parent == tmp_path / "artifacts" / result.mission.mission_id
    assert len(result.static_report_checksum) == 64

    report_json = json.loads(result.static_report_path.read_text(encoding="utf-8"))
    assert report_json["schema_version"] == "static-report-v1"
    assert report_json["report_id"] == result.static_report.report_id

    expected_markdown_path = tmp_path / "artifacts" / result.mission.mission_id / "static_report.md"
    assert result.static_report_markdown_path == expected_markdown_path
    assert result.static_report_markdown_path.is_file()
    assert result.static_report_markdown_path.parent == (
        tmp_path / "artifacts" / result.mission.mission_id
    )
    assert len(result.static_report_markdown_checksum) == 64

    report_markdown = result.static_report_markdown_path.read_text(encoding="utf-8")
    assert "# OrbitMind Offline Sample Static Report" in report_markdown
    assert f"Report ID: {result.static_report.report_id}" in report_markdown
    assert "Schema version: static-report-v1" in report_markdown
    assert f"Mission ID: {result.mission.mission_id}" in report_markdown
    assert "Bundled stale sample TLE only; not live tracking." in report_markdown
    assert "No quantum advantage claim." in report_markdown


def test_run_sample_normalizes_sample_id(tmp_path: Path) -> None:
    result = run_sample(_settings(tmp_path), sample_id="ISS")

    assert result.mission.status.value == "completed"
    assert result.mission.sample_count == 31
    assert result.static_report_path.is_file()
    assert result.static_report_markdown_path.is_file()


def test_write_summary_is_bounded_and_reviewer_readable(tmp_path: Path) -> None:
    result = run_sample(_settings(tmp_path))
    stream = StringIO()

    write_summary(result, stream)

    output = stream.getvalue()
    assert "OrbitMind offline sample completed" in output
    assert f"mission_id: {result.mission.mission_id}" in output
    assert "status: completed" in output
    assert "epistemic_status: deterministic-calculation" in output
    assert "sample_count: 31" in output
    assert "source.test_only: true" in output
    assert "altitude_vs_time" in output
    assert "ground_track" in output
    assert "local image: " in output
    assert "local sidecar: " in output
    assert f"local file: {result.display_static_report_path()}" in output
    assert f"checksum: {result.static_report_checksum}" in output
    assert f"local markdown: {result.display_static_report_markdown_path()}" in output
    assert f"markdown_checksum: {result.static_report_markdown_checksum}" in output
    assert "static_report.json" in output
    assert "static_report.md" in output
    assert str(tmp_path.resolve()) not in output
    assert "schema_version: static-report-v1" in output
    assert "not live tracking" in output
    assert "no provider fetch" in output
    assert "no command readiness" in output
    assert "no quantum advantage claim" in output


def test_main_runs_sample_without_api_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sample_module, "_sample_settings", lambda: _settings(tmp_path))
    stream = StringIO()

    exit_code = sample_module.main([], stdout=stream)

    assert exit_code == 0
    assert "OrbitMind offline sample completed" in stream.getvalue()


def test_main_runs_explicit_iss_sample(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sample_module, "_sample_settings", lambda: _settings(tmp_path))
    stream = StringIO()

    exit_code = sample_module.main(["--sample", "iss"], stdout=stream)

    output = stream.getvalue()
    assert exit_code == 0
    assert "OrbitMind offline sample completed" in output
    assert "sample_count: 31" in output
    assert "static_report.json" in output
    assert "static_report.md" in output
    assert "not live tracking" in output


def test_main_normalizes_explicit_sample_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sample_module, "_sample_settings", lambda: _settings(tmp_path))
    stream = StringIO()

    exit_code = sample_module.main(["--sample", "ISS"], stdout=stream)

    output = stream.getvalue()
    assert exit_code == 0
    assert "OrbitMind offline sample completed" in output
    assert "sample_count: 31" in output
    assert "static_report.json" in output
    assert "static_report.md" in output
    assert "not live tracking" in output


def test_main_lists_samples_without_running_mission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_run_sample(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("list-samples must not run a mission")

    monkeypatch.setattr(sample_module, "run_sample", fail_run_sample)
    stream = StringIO()

    exit_code = sample_module.main(["--list-samples"], stdout=stream)

    output = stream.getvalue()
    assert exit_code == 0
    assert "Available offline samples:" in output
    assert "iss" in output
    assert "Bundled stale ISS sample TLE" in output
    assert "OrbitMind offline sample completed" not in output


def test_main_rejects_unknown_sample_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_settings() -> Settings:
        raise AssertionError("unknown sample must not initialize settings")

    def fail_run_sample(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("unknown sample must not run a mission")

    monkeypatch.setattr(sample_module, "_sample_settings", fail_settings)
    monkeypatch.setattr(sample_module, "run_sample", fail_run_sample)

    exit_code = sample_module.main(["--sample", "unknown"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "unknown_sample" in captured.err
    assert "unsupported bundled offline sample 'unknown'" in captured.err
    assert "--list-samples" in captured.err
    assert "Traceback" not in captured.err
    assert "OrbitMind offline sample completed" not in captured.out


def test_main_reports_unexpected_failures_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_run_sample(_settings: Settings) -> object:
        raise RuntimeError("boom with internal detail")

    monkeypatch.setattr(sample_module, "run_sample", fail_run_sample)

    exit_code = sample_module.main([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "unexpected_error" in captured.err
    assert "offline sample could not complete" in captured.err
    assert "Traceback" not in captured.err
    assert "boom with internal detail" not in captured.err
