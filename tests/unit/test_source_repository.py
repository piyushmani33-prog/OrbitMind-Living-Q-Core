"""Unit tests for the SQLAlchemy source repository."""

from __future__ import annotations

import datetime as dt

from orbitmind.persistence.database import Database
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.sources.freshness import fixture_freshness
from orbitmind.sources.models import (
    FetchOutcome,
    OrbitalElementRecord,
    SourceCacheRecord,
    SourceFetchRecord,
    SourceHealth,
)
from orbitmind.sources.policies import SourceCatalog

NOW = dt.datetime(2026, 6, 19, 12, 0, 0, tzinfo=dt.UTC)


def _element() -> OrbitalElementRecord:
    return OrbitalElementRecord(
        satellite_id="25544",
        object_name="ISS (ZARYA)",
        norad_cat_id=25544,
        epoch=NOW,
        tle_line1="1 25544U ...",
        tle_line2="2 25544 ...",
        source_id="celestrak",
        schema_version="omm-1",
        checksum="abc123",
        freshness=fixture_freshness(),
    )


def test_sync_definition_and_cache_round_trip(
    celestrak_db: Database, celestrak_catalog: SourceCatalog
) -> None:
    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        for definition in celestrak_catalog.list():
            repo.sync_definition(definition)
        repo.upsert_cache_entry(
            SourceCacheRecord(
                cache_key="celestrak:25544",
                source_id="celestrak",
                url="https://celestrak.org/x",
                body_path="celestrak/abc.json",
                checksum="abc",
                schema_version="omm-1",
                http_status=200,
                content_type="application/json",
                fetched_at=NOW,
                expires_at=NOW + dt.timedelta(hours=2),
            )
        )
        session.commit()

    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        cached = repo.get_cache_entry("celestrak:25544")
        assert cached is not None
        assert cached.http_status == 200
        assert cached.fetched_at.tzinfo is not None
        assert len(repo.list_cache_for_source("celestrak")) == 1


def test_fetch_outcomes_and_element_source_data(celestrak_db: Database) -> None:
    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        repo.add_fetch(
            SourceFetchRecord(
                source_id="celestrak",
                cache_key="celestrak:25544",
                url="u",
                outcome=FetchOutcome.FETCHED,
                completed_at=NOW,
            )
        )
        repo.add_fetch(
            SourceFetchRecord(
                source_id="celestrak",
                cache_key="celestrak:25544",
                url="u",
                outcome=FetchOutcome.FAILED,
                error="boom",
            )
        )
        repo.add_health_event("celestrak", SourceHealth.DEGRADED, "most recent fetch failed")
        repo.add_element_record(_element(), "mission-x", "1")
        session.commit()

    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        last_success, last_failure, reason = repo.last_fetch_outcomes("celestrak")
        assert last_success is not None
        assert last_failure is not None
        assert reason == "boom"

        data = repo.get_mission_source_data("mission-x")
        assert data is not None
        assert data.source_id == "celestrak"
        assert data.record_identifier == "25544"
        assert "review" in data.limitations
