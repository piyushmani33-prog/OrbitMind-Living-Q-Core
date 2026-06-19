"""Unit tests for deterministic verification checks."""

from __future__ import annotations

import datetime as dt

from orbitmind.mission.models import MissionRequest
from orbitmind.space.models import SampleStatus, ScientificResult
from orbitmind.verification.checks import VerificationService
from orbitmind.verification.models import FindingStatus, Severity


def _findings(result: ScientificResult, request: MissionRequest) -> dict[str, FindingStatus]:
    findings = VerificationService().verify(result, request)
    return {f.check_id: f.status for f in findings}


def test_all_checks_pass_on_good_result(
    scientific_result: ScientificResult, mission_request: MissionRequest
) -> None:
    statuses = _findings(scientific_result, mission_request)
    assert set(statuses.values()) == {FindingStatus.PASSED}
    # Required check identifiers are present.
    for check in (
        "timestamps_utc",
        "monotonic_times",
        "sample_count",
        "finite_values",
        "coordinate_bounds",
        "altitude_bounds",
        "propagation_errors",
        "unit_consistency",
        "provenance_completeness",
    ):
        assert check in statuses


def test_sample_count_mismatch_fails(
    scientific_result: ScientificResult, mission_request: MissionRequest
) -> None:
    truncated = scientific_result.model_copy(update={"samples": scientific_result.samples[:-1]})
    assert _findings(truncated, mission_request)["sample_count"] is FindingStatus.FAILED


def test_propagation_error_sample_is_flagged(
    scientific_result: ScientificResult, mission_request: MissionRequest
) -> None:
    bad = scientific_result.samples[0].model_copy(
        update={"status": SampleStatus.ERROR, "error": "synthetic failure", "altitude_km": None}
    )
    mutated = scientific_result.model_copy(
        update={"samples": [bad, *scientific_result.samples[1:]]}
    )
    statuses = _findings(mutated, mission_request)
    assert statuses["propagation_errors"] is FindingStatus.FAILED


def test_finding_has_required_fields(
    scientific_result: ScientificResult, mission_request: MissionRequest
) -> None:
    finding = VerificationService().verify(scientific_result, mission_request)[0]
    assert finding.check_id
    assert isinstance(finding.severity, Severity)
    assert isinstance(finding.status, FindingStatus)
    assert finding.explanation
    assert isinstance(finding.values, dict)


def test_out_of_range_coordinate_fails(
    scientific_result: ScientificResult, mission_request: MissionRequest
) -> None:
    bad = scientific_result.samples[0].model_copy(update={"latitude_deg": 120.0})
    mutated = scientific_result.model_copy(
        update={"samples": [bad, *scientific_result.samples[1:]]}
    )
    assert _findings(mutated, mission_request)["coordinate_bounds"] is FindingStatus.FAILED


def test_naive_timestamp_fails(
    scientific_result: ScientificResult, mission_request: MissionRequest
) -> None:
    naive_sample = scientific_result.samples[0].model_copy(
        update={"timestamp": dt.datetime(2019, 12, 9, 17, 0, 0)}  # naive (no tzinfo)
    )
    mutated = scientific_result.model_copy(
        update={"samples": [naive_sample, *scientific_result.samples[1:]]}
    )
    assert _findings(mutated, mission_request)["timestamps_utc"] is FindingStatus.FAILED
