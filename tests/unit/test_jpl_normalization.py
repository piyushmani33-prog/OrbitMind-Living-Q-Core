"""Unit tests for JPL response validation + normalization."""

from __future__ import annotations

import datetime as dt

from tests.conftest import load_jpl_fixture

from orbitmind.objects.models import SpaceObjectKind
from orbitmind.smallbody.models import JplSourceRecord
from orbitmind.sources.freshness import fixture_freshness
from orbitmind.sources.jpl.cad_models import CadResponse
from orbitmind.sources.jpl.normalization import normalize_cad, normalize_query, normalize_sbdb
from orbitmind.sources.jpl.query_models import SbdbQueryResponse
from orbitmind.sources.jpl.sbdb_models import SbdbOutcome, SbdbResponse

NOW = dt.datetime(2026, 6, 19, tzinfo=dt.UTC)


def _normalize(name: str, identifier: str):
    resp = SbdbResponse.model_validate(load_jpl_fixture(name))
    return normalize_sbdb(
        resp,
        requested_identifier=identifier,
        source_id="jpl-sbdb",
        fetched_at=NOW,
        checksum="abc",
        schema_version="sbdb-1",
        policy_version="1",
        freshness=fixture_freshness(),
    )


def test_asteroid_normalizes() -> None:
    rec = _normalize("sbdb_asteroid.json", "433")
    assert rec.identity.kind is SpaceObjectKind.ASTEROID
    assert rec.small_body_identity.number == "433"
    assert rec.orbit.elements.semimajor_axis_au == 1.458
    assert rec.classification.orbit_class_code == "AMO"
    assert rec.hazard.near_earth_object_source is True
    assert rec.physical.diameter_km == 16.84


def test_comet_normalizes_as_comet() -> None:
    rec = _normalize("sbdb_comet.json", "1P")
    assert rec.identity.kind is SpaceObjectKind.COMET
    assert rec.orbit.elements.eccentricity == 0.9671
    # Comet absolute magnitude not provided -> None, not zero.
    assert rec.physical.absolute_magnitude_h is None


def test_missing_optional_values_stay_none() -> None:
    rec = _normalize("sbdb_missing_optional.json", "2018 VP1")
    e = rec.orbit.elements
    assert e.eccentricity == 0.4607
    assert e.aphelion_distance_au is None  # not provided -> None (never 0)
    assert e.orbital_period_days is None
    assert rec.physical.diameter_km is None


def test_sbdb_outcomes() -> None:
    assert SbdbResponse.model_validate(load_jpl_fixture("sbdb_asteroid.json")).outcome() is (
        SbdbOutcome.FOUND
    )
    assert SbdbResponse.model_validate(load_jpl_fixture("sbdb_ambiguous.json")).outcome() is (
        SbdbOutcome.AMBIGUOUS
    )
    assert SbdbResponse.model_validate(load_jpl_fixture("sbdb_not_found.json")).outcome() is (
        SbdbOutcome.NOT_FOUND
    )


def test_query_normalization_and_truncation() -> None:
    resp = SbdbQueryResponse.model_validate(load_jpl_fixture("query_response.json"))
    items, total, truncated = normalize_query(resp, limit=2)
    assert total == 5
    assert len(items) == 2
    assert truncated is True
    assert items[0].near_earth_object_source is True


def test_cad_normalization() -> None:
    resp = CadResponse.model_validate(load_jpl_fixture("cad_response.json"))
    source = JplSourceRecord(
        source_id="jpl-cad",
        source_record_id="cad",
        requested_identifier="x",
        checksum="abc",
        schema_version="cad-1",
        policy_version="1",
    )
    records, total, _truncated = normalize_cad(
        resp, default_body="Earth", source=source, freshness=fixture_freshness(), limit=50
    )
    assert total == 3
    assert records[0].body.name == "Earth"
    assert records[0].distance.nominal_au == 0.0123
    assert records[0].velocity.relative_kms == 9.51
    assert records[0].time_utc.year == 2026
