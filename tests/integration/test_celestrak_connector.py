"""Integration tests for the CelesTrak connector using mocked HTTP responses."""

from __future__ import annotations

import httpx
import pytest
from tests.conftest import build_celestrak_omm, make_transport

from orbitmind.persistence.database import Database
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.sources.cache import SourceCacheStore
from orbitmind.sources.celestrak.connector import CelestrakConnector
from orbitmind.sources.errors import (
    DisallowedRequestError,
    SourceSchemaError,
    SourceUnavailableError,
)
from orbitmind.sources.models import ElementFetchResult, FetchOutcome, FreshnessState
from orbitmind.sources.policies import SourceCatalog

pytestmark = pytest.mark.integration


def _connector(
    catalog: SourceCatalog,
    store: SourceCacheStore,
    transport: httpx.MockTransport,
    **policy_overrides: object,
) -> CelestrakConnector:
    definition = catalog.get("celestrak")
    assert definition is not None
    if policy_overrides:
        policy = definition.policy.model_copy(update=policy_overrides)
        definition = definition.model_copy(update={"policy": policy})
    return CelestrakConnector(definition, store, transport=transport, sleep=lambda _: None)


def _run(db: Database, connector: CelestrakConnector, *, force: bool = False) -> ElementFetchResult:
    with db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        result = connector.get_element_record("25544", repo, force_refresh=force)
        session.commit()
        return result


def test_successful_fetch(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    transport = make_transport(records=[build_celestrak_omm()])
    result = _run(celestrak_db, _connector(celestrak_catalog, celestrak_store, transport))
    assert result.fetch.outcome is FetchOutcome.FETCHED
    assert result.record.tle_line1.startswith("1 25544")
    assert result.record.freshness.state is FreshnessState.CURRENT
    assert result.record.checksum


def test_cache_hit_on_second_call(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    connector = _connector(
        celestrak_catalog, celestrak_store, make_transport(records=[build_celestrak_omm()])
    )
    assert _run(celestrak_db, connector).fetch.outcome is FetchOutcome.FETCHED
    assert _run(celestrak_db, connector).fetch.outcome is FetchOutcome.CACHED


def test_refresh_suppressed_within_min_interval(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    connector = _connector(
        celestrak_catalog,
        celestrak_store,
        make_transport(records=[build_celestrak_omm()]),
        cache_ttl_seconds=0,  # cache immediately stale
        min_refresh_seconds=3600,  # but refresh not yet allowed
    )
    assert _run(celestrak_db, connector).fetch.outcome is FetchOutcome.FETCHED
    assert _run(celestrak_db, connector).fetch.outcome is FetchOutcome.SUPPRESSED


def test_expired_cache_is_refetched(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    connector = _connector(
        celestrak_catalog,
        celestrak_store,
        make_transport(records=[build_celestrak_omm()]),
        cache_ttl_seconds=0,
        min_refresh_seconds=0,
    )
    assert _run(celestrak_db, connector).fetch.outcome is FetchOutcome.FETCHED
    assert _run(celestrak_db, connector).fetch.outcome is FetchOutcome.FETCHED


def test_timeout_is_unavailable(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    transport = make_transport(exc=httpx.ConnectTimeout)
    with pytest.raises(SourceUnavailableError):
        _run(celestrak_db, _connector(celestrak_catalog, celestrak_store, transport))


def test_http_500_is_unavailable(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    transport = make_transport(records=[], status_code=503)
    with pytest.raises(SourceUnavailableError):
        _run(celestrak_db, _connector(celestrak_catalog, celestrak_store, transport))


def test_malformed_json_rejected(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    transport = make_transport(raw_body=b"this is not json")
    with pytest.raises(SourceSchemaError):
        _run(celestrak_db, _connector(celestrak_catalog, celestrak_store, transport))


def test_empty_array_rejected(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    transport = make_transport(records=[])
    with pytest.raises(SourceSchemaError):
        _run(celestrak_db, _connector(celestrak_catalog, celestrak_store, transport))


def test_wrong_content_type_rejected(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    transport = make_transport(records=[build_celestrak_omm()], content_type="text/html")
    with pytest.raises(DisallowedRequestError):
        _run(celestrak_db, _connector(celestrak_catalog, celestrak_store, transport))


def test_oversized_response_rejected(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    transport = make_transport(records=[build_celestrak_omm()])
    connector = _connector(celestrak_catalog, celestrak_store, transport, max_response_bytes=10)
    with pytest.raises(DisallowedRequestError):
        _run(celestrak_db, connector)


def test_stale_cache_served_when_suppressed(
    celestrak_db: Database, celestrak_store: SourceCacheStore, celestrak_catalog: SourceCatalog
) -> None:
    # Old epoch => stale/expired data; suppressed refresh still serves it, labelled stale.
    transport = make_transport(records=[build_celestrak_omm("2019-12-09T16:38:29.000000")])
    connector = _connector(
        celestrak_catalog, celestrak_store, transport, cache_ttl_seconds=0, min_refresh_seconds=3600
    )
    _run(celestrak_db, connector)
    second = _run(celestrak_db, connector)
    assert second.fetch.outcome is FetchOutcome.SUPPRESSED
    assert second.record.freshness.state is FreshnessState.EXPIRED
