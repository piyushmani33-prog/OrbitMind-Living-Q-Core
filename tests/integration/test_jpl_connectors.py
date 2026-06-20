"""Integration tests for the JPL connectors using mocked HTTP responses."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest
from tests.conftest import load_jpl_fixture, make_jpl_transport

from orbitmind.core.errors import ValidationError
from orbitmind.objects.models import SpaceObjectKind
from orbitmind.persistence.database import Database
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.smallbody.query import CadQueryFilter, SbdbQueryFilter
from orbitmind.sources.cache import SourceCacheStore
from orbitmind.sources.errors import (
    AmbiguousIdentifierError,
    DisallowedRequestError,
    NetworkDisabledError,
    ObjectNotFoundError,
    SourceSchemaError,
)
from orbitmind.sources.jpl.cad_connector import CadConnector
from orbitmind.sources.jpl.query_connector import SbdbQueryConnector
from orbitmind.sources.jpl.sbdb_connector import SbdbConnector
from orbitmind.sources.policies import SourceCatalog

pytestmark = pytest.mark.integration
UTC = dt.UTC


def _sbdb(
    catalog: SourceCatalog,
    store: SourceCacheStore,
    transport: httpx.MockTransport,
    **overrides: object,
) -> SbdbConnector:
    definition = catalog.require("jpl-sbdb")
    if overrides:
        definition = definition.model_copy(
            update={"policy": definition.policy.model_copy(update=overrides)}
        )
    return SbdbConnector(definition, store, transport=transport, sleep=lambda _: None)


def _lookup(db: Database, conn: SbdbConnector, identifier: str):
    with db.session() as s:
        result = conn.lookup(identifier, SqlAlchemySourceRepository(s))
        s.commit()
        return result


def test_lookup_found(jpl_db, jpl_store, jpl_catalog) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_asteroid.json"))
    result = _lookup(jpl_db, _sbdb(jpl_catalog, jpl_store, transport), "433")
    assert result.record.identity.kind is SpaceObjectKind.ASTEROID
    assert result.record.small_body_identity.number == "433"
    assert result.from_cache is False


def test_lookup_not_found(jpl_db, jpl_store, jpl_catalog) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_not_found.json"))
    with pytest.raises(ObjectNotFoundError):
        _lookup(jpl_db, _sbdb(jpl_catalog, jpl_store, transport), "ZZZ")


def test_lookup_ambiguous(jpl_db, jpl_store, jpl_catalog) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_ambiguous.json"))
    with pytest.raises(AmbiguousIdentifierError):
        _lookup(jpl_db, _sbdb(jpl_catalog, jpl_store, transport), "AB")


def test_lookup_malformed(jpl_db, jpl_store, jpl_catalog) -> None:
    transport = make_jpl_transport(sbdb=load_jpl_fixture("sbdb_malformed.json"))
    with pytest.raises(SourceSchemaError):
        _lookup(jpl_db, _sbdb(jpl_catalog, jpl_store, transport), "433")


def test_lookup_cache_hit(jpl_db, jpl_store, jpl_catalog) -> None:
    conn = _sbdb(
        jpl_catalog, jpl_store, make_jpl_transport(sbdb=load_jpl_fixture("sbdb_asteroid.json"))
    )
    assert _lookup(jpl_db, conn, "433").from_cache is False
    assert _lookup(jpl_db, conn, "433").from_cache is True


def test_lookup_network_disabled(jpl_db, jpl_store, jpl_catalog) -> None:
    conn = _sbdb(
        jpl_catalog,
        jpl_store,
        make_jpl_transport(sbdb=load_jpl_fixture("sbdb_asteroid.json")),
        network_enabled=False,
    )
    with pytest.raises(NetworkDisabledError):
        _lookup(jpl_db, conn, "433")


def test_lookup_wrong_content_type(jpl_db, jpl_store, jpl_catalog) -> None:
    transport = make_jpl_transport(
        sbdb=load_jpl_fixture("sbdb_asteroid.json"), content_type="text/html"
    )
    with pytest.raises(DisallowedRequestError):
        _lookup(jpl_db, _sbdb(jpl_catalog, jpl_store, transport), "433")


def test_query_truncation(jpl_db, jpl_store, jpl_catalog) -> None:
    definition = jpl_catalog.require("jpl-sbdb-query")
    conn = SbdbQueryConnector(
        definition,
        jpl_store,
        max_results=200,
        transport=make_jpl_transport(query=load_jpl_fixture("query_response.json")),
        sleep=lambda _: None,
    )
    with jpl_db.session() as s:
        result = conn.query(
            SbdbQueryFilter(limit=2, output_fields=["full_name", "neo", "a"], sort_field="a"),
            SqlAlchemySourceRepository(s),
        )
        s.commit()
    assert result.total_reported == 5
    assert result.returned == 2
    assert result.truncated is True
    # Deterministic sort by semimajor axis (ascending; None last).
    axes = [i.semimajor_axis_au for i in result.items]
    assert axes == sorted(axes, key=lambda v: (v is None, v))


def test_cad_query(jpl_db, jpl_store, jpl_catalog) -> None:
    definition = jpl_catalog.require("jpl-cad")
    conn = CadConnector(
        definition,
        jpl_store,
        max_results=200,
        max_query_span_days=366,
        transport=make_jpl_transport(cad=load_jpl_fixture("cad_response.json")),
        sleep=lambda _: None,
    )
    with jpl_db.session() as s:
        result = conn.close_approaches(
            CadQueryFilter(
                date_min=dt.datetime(2026, 1, 1, tzinfo=UTC),
                date_max=dt.datetime(2026, 6, 1, tzinfo=UTC),
            ),
            SqlAlchemySourceRepository(s),
        )
        s.commit()
    assert result.returned == 3
    assert result.records[0].body.name == "Earth"


def test_cad_span_too_large(jpl_db, jpl_store, jpl_catalog) -> None:
    definition = jpl_catalog.require("jpl-cad")
    conn = CadConnector(
        definition,
        jpl_store,
        max_results=200,
        max_query_span_days=30,
        transport=make_jpl_transport(cad=load_jpl_fixture("cad_response.json")),
        sleep=lambda _: None,
    )
    with jpl_db.session() as s, pytest.raises(ValidationError):
        conn.close_approaches(
            CadQueryFilter(
                date_min=dt.datetime(2026, 1, 1, tzinfo=UTC),
                date_max=dt.datetime(2026, 12, 1, tzinfo=UTC),
            ),
            SqlAlchemySourceRepository(s),
        )
