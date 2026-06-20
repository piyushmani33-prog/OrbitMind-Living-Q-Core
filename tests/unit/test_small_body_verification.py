"""Unit tests for deterministic small-body verification."""

from __future__ import annotations

import datetime as dt

from tests.conftest import load_jpl_fixture

from orbitmind.objects.models import ObjectVerificationStatus
from orbitmind.smallbody.models import (
    CloseApproachBody,
    CloseApproachDistance,
    CloseApproachRecord,
    CloseApproachVelocity,
    JplSourceRecord,
)
from orbitmind.smallbody.verification import SmallBodyVerificationService, overall_status
from orbitmind.sources.freshness import fixture_freshness
from orbitmind.sources.jpl.normalization import normalize_sbdb
from orbitmind.sources.jpl.sbdb_models import SbdbResponse
from orbitmind.verification.models import CheckCategory, FindingStatus

NOW = dt.datetime(2026, 6, 19, tzinfo=dt.UTC)


def _record(name: str):
    resp = SbdbResponse.model_validate(load_jpl_fixture(name))
    return normalize_sbdb(
        resp,
        requested_identifier="x",
        source_id="jpl-sbdb",
        fetched_at=NOW,
        checksum="abc",
        schema_version="sbdb-1",
        policy_version="1",
        freshness=fixture_freshness(),
    )


def test_good_asteroid_passes() -> None:
    findings = SmallBodyVerificationService().verify(_record("sbdb_asteroid.json"))
    failed = [f for f in findings if f.status is FindingStatus.FAILED]
    assert not failed
    assert overall_status(findings) is ObjectVerificationStatus.PASSED
    # Findings carry a category + (where relevant) units.
    by_id = {f.check_id: f for f in findings}
    assert by_id["positive_semimajor_axis"].category is CheckCategory.MATHEMATICS
    assert by_id["positive_semimajor_axis"].units == "au"


def test_negative_eccentricity_fails() -> None:
    rec = _record("sbdb_asteroid.json")
    bad = rec.model_copy(
        update={
            "orbit": rec.orbit.model_copy(
                update={"elements": rec.orbit.elements.model_copy(update={"eccentricity": -0.1})}
            )
        }
    )
    findings = SmallBodyVerificationService().verify(bad)
    by_id = {f.check_id: f for f in findings}
    assert by_id["eccentricity_bounds"].status is FindingStatus.FAILED
    assert overall_status(findings) is ObjectVerificationStatus.FAILED


def test_comet_semimajor_axis_check_skipped() -> None:
    findings = SmallBodyVerificationService().verify(_record("sbdb_comet.json"))
    by_id = {f.check_id: f for f in findings}
    # Comets can be parabolic/hyperbolic; the positive-a check is skipped for comets.
    assert by_id["positive_semimajor_axis"].status is FindingStatus.SKIPPED


def test_close_approach_checks() -> None:
    source = JplSourceRecord(
        source_id="jpl-cad",
        source_record_id="cad",
        requested_identifier="x",
        checksum="abc",
        schema_version="cad-1",
        policy_version="1",
    )
    records = [
        CloseApproachRecord(
            designation="X",
            time_utc=NOW,
            body=CloseApproachBody(name="Earth"),
            distance=CloseApproachDistance(nominal_au=0.01),
            velocity=CloseApproachVelocity(relative_kms=9.0),
            source=source,
            freshness=fixture_freshness(),
        )
    ]
    findings = SmallBodyVerificationService().verify_close_approaches(records)
    by_id = {f.check_id: f.status for f in findings}
    assert by_id["ca_distance_positive"] is FindingStatus.PASSED
    assert by_id["ca_velocity_positive"] is FindingStatus.PASSED
