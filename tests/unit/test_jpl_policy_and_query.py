"""Unit tests for JPL source policy, identifier + query allowlists."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.config import Settings
from orbitmind.core.errors import ValidationError
from orbitmind.smallbody.identifiers import validate_small_body_identifier
from orbitmind.smallbody.query import CadQueryFilter, SbdbQueryFilter
from orbitmind.sources.models import SchemaFormat
from orbitmind.sources.policies import SourceCatalog

UTC = dt.UTC


def test_jpl_policies_are_safe() -> None:
    catalog = SourceCatalog(
        Settings(network_enabled=True, jpl_sbdb_enabled=True, jpl_cad_enabled=True)
    )
    for source_id in ("jpl-sbdb", "jpl-sbdb-query", "jpl-cad"):
        policy = catalog.require(source_id).policy
        assert policy.allowed_hostnames == ("ssd-api.jpl.nasa.gov",)
        assert policy.https_only is True
        assert policy.follow_redirects is False
        assert policy.allowed_methods == ("GET",)
        assert policy.schema_format is SchemaFormat.JSON
        assert policy.license.requires_review is True
        assert policy.license.commercial_use_confirmed is False
        assert "inspected 2026-06-19" in policy.documentation_reference
        assert policy.network_enabled is True


def test_jpl_network_gate_requires_both_switches() -> None:
    # Global network off -> not enabled even if source switch on.
    pol = SourceCatalog(Settings(network_enabled=False, jpl_sbdb_enabled=True)).require("jpl-sbdb")
    assert pol.policy.network_enabled is False


def test_identifier_allowlist() -> None:
    for ok in ("433", "Eros", "2021 AB", "1P/Halley", "C/2014 Q2"):
        assert validate_small_body_identifier(ok)
    for bad in ("x&y=1", "a?b", "../etc", "", "  "):
        with pytest.raises(ValidationError):
            validate_small_body_identifier(bad)


def test_query_filter_allowlists() -> None:
    SbdbQueryFilter(orbit_class="AMO", sort_field="a", output_fields=["full_name", "a"])
    with pytest.raises(PydanticValidationError):
        SbdbQueryFilter(orbit_class="NOPE")
    with pytest.raises(PydanticValidationError):
        SbdbQueryFilter(sort_field="drop table")
    with pytest.raises(PydanticValidationError):
        SbdbQueryFilter(output_fields=["evil; select"])
    with pytest.raises(PydanticValidationError):
        SbdbQueryFilter(limit=999)  # exceeds max


def test_cad_filter_validation() -> None:
    CadQueryFilter(
        date_min=dt.datetime(2026, 1, 1, tzinfo=UTC),
        date_max=dt.datetime(2026, 2, 1, tzinfo=UTC),
        body="Earth",
    )
    with pytest.raises(PydanticValidationError):  # naive datetime
        CadQueryFilter(date_min=dt.datetime(2026, 1, 1), date_max=dt.datetime(2026, 2, 1))
    with pytest.raises(PydanticValidationError):  # bad body
        CadQueryFilter(
            date_min=dt.datetime(2026, 1, 1, tzinfo=UTC),
            date_max=dt.datetime(2026, 2, 1, tzinfo=UTC),
            body="Pluto",
        )
    with pytest.raises(PydanticValidationError):  # end before start
        CadQueryFilter(
            date_min=dt.datetime(2026, 2, 1, tzinfo=UTC),
            date_max=dt.datetime(2026, 1, 1, tzinfo=UTC),
        )
