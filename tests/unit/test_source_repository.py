"""Unit tests for the SQLAlchemy source repository."""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from orbitmind.persistence import source_repository as source_repository_module
from orbitmind.persistence.database import Database
from orbitmind.persistence.models import SourceDefinitionRow, SourcePolicyRow
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
LATER = NOW + dt.timedelta(hours=1)


@contextmanager
def _observe_source_writes(database: Database) -> Iterator[list[str]]:
    statements: list[str] = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.lower().split())
        if normalized.startswith(("insert ", "update ", "delete ")) and any(
            table in normalized for table in ("source_definitions", "source_policies")
        ):
            statements.append(normalized)

    event.listen(database.engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(database.engine, "before_cursor_execute", record)


def _write_counts(statements: list[str]) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for statement in statements:
        operation = statement.split(" ", maxsplit=1)[0]
        for table in ("source_definitions", "source_policies"):
            if table in statement:
                counts[(operation, table)] += 1
    return counts


def _source_rows(session: Session, source_id: str) -> tuple[SourceDefinitionRow, SourcePolicyRow]:
    definition = session.get(SourceDefinitionRow, source_id)
    assert definition is not None
    policy = session.scalars(
        select(SourcePolicyRow).where(SourcePolicyRow.source_id == source_id)
    ).one()
    return definition, policy


def _clock(monkeypatch: pytest.MonkeyPatch, *values: dt.datetime) -> list[dt.datetime]:
    remaining = iter(values)
    calls: list[dt.datetime] = []

    def now() -> dt.datetime:
        value = next(remaining)
        calls.append(value)
        return value

    monkeypatch.setattr(source_repository_module, "utcnow", now)
    return calls


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


def test_sync_definition_creates_definition_and_policy_once(
    celestrak_db: Database,
    celestrak_catalog: SourceCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = celestrak_catalog.require("sample")
    calls = _clock(monkeypatch, NOW)

    with (
        _observe_source_writes(celestrak_db) as statements,
        celestrak_db.session() as session,
    ):
        SqlAlchemySourceRepository(session).sync_definition(definition)
        session.commit()
        row, policy = _source_rows(session, definition.source_id)

    assert row.source_id == definition.source_id
    assert policy.source_id == definition.source_id
    assert row.updated_at == NOW
    assert policy.recorded_at == NOW
    assert calls == [NOW]
    assert _write_counts(statements) == Counter(
        {("insert", "source_definitions"): 1, ("insert", "source_policies"): 1}
    )


def test_identical_sync_preserves_timestamps_and_session_cleanliness(
    celestrak_db: Database,
    celestrak_catalog: SourceCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = celestrak_catalog.require("sample")
    calls = _clock(monkeypatch, NOW)
    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        repo.sync_definition(definition)
        session.commit()
        original_row, original_policy = _source_rows(session, definition.source_id)
        original_policy_id = original_policy.id

        with _observe_source_writes(celestrak_db) as statements:
            repo.sync_definition(definition)
            row, policy = _source_rows(session, definition.source_id)
            assert not session.new
            assert not session.dirty
            assert not session.deleted
            assert not session.is_modified(row, include_collections=True)
            assert not session.is_modified(policy, include_collections=True)
            session.commit()

    assert row.updated_at == original_row.updated_at == NOW
    assert policy.recorded_at == original_policy.recorded_at == NOW
    assert policy.id == original_policy_id
    assert calls == [NOW]
    assert statements == []


def test_definition_only_change_updates_definition_once(
    celestrak_db: Database,
    celestrak_catalog: SourceCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = celestrak_catalog.require("sample")
    changed = definition.model_copy(update={"description": f"{definition.description} Updated."})
    calls = _clock(monkeypatch, NOW, LATER)

    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        repo.sync_definition(definition)
        session.commit()
        _, original_policy = _source_rows(session, definition.source_id)
        original_snapshot = original_policy.snapshot
        original_recorded_at = original_policy.recorded_at

        with _observe_source_writes(celestrak_db) as statements:
            repo.sync_definition(changed)
            session.commit()
        row, policy = _source_rows(session, definition.source_id)

    assert row.description == changed.description
    assert row.updated_at == LATER
    assert policy.snapshot == original_snapshot
    assert policy.recorded_at == original_recorded_at == NOW
    assert calls == [NOW, LATER]
    assert _write_counts(statements) == Counter({("update", "source_definitions"): 1})


def test_policy_only_change_updates_policy_once(
    celestrak_db: Database,
    celestrak_catalog: SourceCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = celestrak_catalog.require("sample")
    changed_policy = definition.policy.model_copy(update={"policy_version": "2"})
    changed = definition.model_copy(update={"policy": changed_policy})
    calls = _clock(monkeypatch, NOW, LATER)

    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        repo.sync_definition(definition)
        session.commit()
        original_row, _ = _source_rows(session, definition.source_id)
        original_updated_at = original_row.updated_at

        with _observe_source_writes(celestrak_db) as statements:
            repo.sync_definition(changed)
            session.commit()
        row, policy = _source_rows(session, definition.source_id)

    assert row.updated_at == original_updated_at == NOW
    assert policy.policy_version == "2"
    assert policy.snapshot["policy_version"] == "2"
    assert policy.recorded_at == LATER
    assert calls == [NOW, LATER]
    assert _write_counts(statements) == Counter({("update", "source_policies"): 1})


def test_definition_and_policy_changes_refresh_both_timestamps_once(
    celestrak_db: Database,
    celestrak_catalog: SourceCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = celestrak_catalog.require("sample")
    changed_policy = definition.policy.model_copy(update={"network_enabled": True})
    changed = definition.model_copy(update={"name": "Updated sample", "policy": changed_policy})
    calls = _clock(monkeypatch, NOW, LATER)

    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        repo.sync_definition(definition)
        session.commit()
        original_row, original_policy = _source_rows(session, definition.source_id)
        original_policy_id = original_policy.id

        with _observe_source_writes(celestrak_db) as statements:
            repo.sync_definition(changed)
            session.commit()
        row, policy = _source_rows(session, definition.source_id)

    assert row.name == "Updated sample"
    assert row.updated_at == LATER
    assert policy.network_enabled is True
    assert policy.recorded_at == LATER
    assert policy.id == original_policy_id
    assert original_row.source_id == row.source_id
    assert calls == [NOW, LATER]
    assert _write_counts(statements) == Counter(
        {("update", "source_definitions"): 1, ("update", "source_policies"): 1}
    )


def test_reopened_session_identical_sync_emits_no_update(
    celestrak_db: Database,
    celestrak_catalog: SourceCatalog,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = celestrak_catalog.require("sample")
    calls = _clock(monkeypatch, NOW)
    with celestrak_db.session() as session:
        SqlAlchemySourceRepository(session).sync_definition(definition)
        session.commit()
        row, policy = _source_rows(session, definition.source_id)
        original = (row.updated_at, policy.recorded_at, policy.id)

    with (
        _observe_source_writes(celestrak_db) as statements,
        celestrak_db.session() as session,
    ):
        SqlAlchemySourceRepository(session).sync_definition(definition)
        assert not session.new
        assert not session.dirty
        assert not session.deleted
        session.commit()
        row, policy = _source_rows(session, definition.source_id)

    assert (row.updated_at, policy.recorded_at, policy.id) == original
    assert calls == [NOW]
    assert statements == []


def test_current_catalog_second_sync_emits_no_source_writes(
    celestrak_db: Database,
    celestrak_catalog: SourceCatalog,
) -> None:
    definitions = celestrak_catalog.list()
    assert len(definitions) == 5
    with celestrak_db.session() as session:
        repo = SqlAlchemySourceRepository(session)
        for definition in definitions:
            repo.sync_definition(definition)
        session.commit()
        initial_timestamps = {
            definition.source_id: (
                _source_rows(session, definition.source_id)[0].updated_at,
                _source_rows(session, definition.source_id)[1].recorded_at,
            )
            for definition in definitions
        }

    with (
        _observe_source_writes(celestrak_db) as statements,
        celestrak_db.session() as session,
    ):
        repo = SqlAlchemySourceRepository(session)
        for definition in definitions:
            repo.sync_definition(definition)
        assert not session.new
        assert not session.dirty
        assert not session.deleted
        session.commit()
        final_timestamps = {
            definition.source_id: (
                _source_rows(session, definition.source_id)[0].updated_at,
                _source_rows(session, definition.source_id)[1].recorded_at,
            )
            for definition in definitions
        }
        assert session.scalar(select(func.count()).select_from(SourceDefinitionRow)) == 5
        assert session.scalar(select(func.count()).select_from(SourcePolicyRow)) == 5

    assert final_timestamps == initial_timestamps
    assert statements == []
