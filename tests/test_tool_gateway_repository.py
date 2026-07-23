"""Append-only Tool Gateway repository integrity and replay coverage."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.persistence.database import Database
from orbitmind.persistence.tool_gateway_models import OperationToolGatewayDecisionRow
from orbitmind.persistence.tool_gateway_repository import (
    GatewayDecisionCorruptError,
    GatewayDisposition,
    SqlAlchemyToolGatewayRepository,
)
from orbitmind.toolgateway.contracts import GatewayDecisionRecord, GatewayOutcome, GatewayReasonCode

T0 = datetime(2026, 7, 22, tzinfo=UTC)
OWNER = "owner-piyush-01"
OWNER_B = "owner-second-02"


@pytest.fixture
def database(tmp_path: Path) -> Iterator[Database]:
    db = Database(f"sqlite:///{(tmp_path / 'gateway-repository.db').as_posix()}")
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


def _record(**updates: Any) -> GatewayDecisionRecord:
    values: dict[str, Any] = {
        "gateway_decision_id": "tgd-0000000000000000000000000000000000000001",
        "owner_id": OWNER,
        "proposal_id": "proposal-0001",
        "actor_id": "actor-0001",
        "tool_id": "repository_file_reader",
        "tool_version": "1.0.0",
        "referenced_admission_id": "admission-0001",
        "outcome": GatewayOutcome.DENIED,
        "primary_reason_code": GatewayReasonCode.ADMISSION_NOT_FOUND,
        "reason_codes": (GatewayReasonCode.ADMISSION_NOT_FOUND,),
        "evaluated_at": T0,
        "requested_at": T0,
        "proposal_fingerprint": "a" * 64,
        "decision_checksum": "b" * 64,
        "created_at": T0,
    }
    values.update(updates)
    return GatewayDecisionRecord(**values)


def _persist(
    database: Database, record: GatewayDecisionRecord | None = None
) -> GatewayDecisionRecord:
    candidate = record or _record()
    with database.session() as session, session.begin():
        result = SqlAlchemyToolGatewayRepository(session).append_gateway_decision_record(
            candidate, idempotency_key="gateway-key-1"
        )
    assert result.disposition is GatewayDisposition.CREATED
    return result.record


def _row(database: Database) -> OperationToolGatewayDecisionRow:
    with database.session() as session:
        row = session.get(
            OperationToolGatewayDecisionRow,
            ("tgd-0000000000000000000000000000000000000001", OWNER),
        )
        assert row is not None
        session.expunge(row)
        return row


def test_append_get_list_and_disposition_are_owner_scoped(database: Database) -> None:
    stored = _persist(database)
    with database.session() as session, session.begin():
        repo = SqlAlchemyToolGatewayRepository(session)
        replay = repo.append_gateway_decision_record(_record(), idempotency_key="gateway-key-1")
        assert (
            repo.get_gateway_decision_record(
                owner_id=OWNER, gateway_decision_id=stored.gateway_decision_id
            )
            == stored
        )
        assert (
            repo.get_gateway_decision_record(
                owner_id=OWNER_B, gateway_decision_id=stored.gateway_decision_id
            )
            is None
        )
        assert repo.list_gateway_decision_records_bounded(owner_id=OWNER, limit=10) == (stored,)
        assert repo.list_gateway_decision_records_bounded(owner_id=OWNER_B, limit=10) == ()
    assert replay.disposition is GatewayDisposition.REPLAYED
    assert replay.record == stored


def test_historical_replay_miss_match_foreign_and_conflict_are_read_only(
    database: Database,
) -> None:
    stored = _persist(database)
    before = _row(database)
    with database.session() as session, session.begin():
        repo = SqlAlchemyToolGatewayRepository(session)
        assert (
            repo.resolve_historical_replay(
                owner_id=OWNER,
                idempotency_key="missing-key",
                proposal_fingerprint="a" * 64,
            )
            is None
        )
        assert (
            repo.resolve_historical_replay(
                owner_id=OWNER_B,
                idempotency_key="gateway-key-1",
                proposal_fingerprint="a" * 64,
            )
            is None
        )
        assert (
            repo.resolve_historical_replay(
                owner_id=OWNER,
                idempotency_key="gateway-key-1",
                proposal_fingerprint="a" * 64,
            )
            == stored
        )
        with pytest.raises(IdempotencyConflictError):
            repo.resolve_historical_replay(
                owner_id=OWNER,
                idempotency_key="gateway-key-1",
                proposal_fingerprint="c" * 64,
            )
    after = _row(database)
    assert after.record_identity == before.record_identity
    assert after.canonical_payload == before.canonical_payload


@pytest.mark.parametrize("corruption", ["payload", "identity", "non_mapping"])
def test_corrupt_rows_fail_closed_without_repair(database: Database, corruption: str) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        row = session.get(
            OperationToolGatewayDecisionRow,
            ("tgd-0000000000000000000000000000000000000001", OWNER),
        )
        assert row is not None
        if corruption == "payload":
            payload = dict(row.canonical_payload)
            payload["outcome"] = "eligible"
            row.canonical_payload = payload
        elif corruption == "identity":
            row.record_identity = "f" * 64
        else:
            row.canonical_payload = ["not", "a", "mapping"]  # type: ignore[assignment]
    corrupted = _row(database)
    with database.session() as session, session.begin():
        repo = SqlAlchemyToolGatewayRepository(session)
        with pytest.raises(GatewayDecisionCorruptError):
            repo.get_gateway_decision_record(
                owner_id=OWNER,
                gateway_decision_id="tgd-0000000000000000000000000000000000000001",
            )
    unchanged = _row(database)
    assert unchanged.record_identity == corrupted.record_identity
    assert unchanged.canonical_payload == corrupted.canonical_payload


def test_reordered_payload_keys_remain_valid(database: Database) -> None:
    stored = _persist(database)
    with database.session() as session, session.begin():
        row = session.get(
            OperationToolGatewayDecisionRow,
            (stored.gateway_decision_id, OWNER),
        )
        assert row is not None
        row.canonical_payload = dict(reversed(tuple(row.canonical_payload.items())))
    with database.session() as session, session.begin():
        assert (
            SqlAlchemyToolGatewayRepository(session).get_gateway_decision_record(
                owner_id=OWNER, gateway_decision_id=stored.gateway_decision_id
            )
            == stored
        )


def test_append_conflict_does_not_create_a_second_row(database: Database) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        repo = SqlAlchemyToolGatewayRepository(session)
        with pytest.raises(IdempotencyConflictError):
            repo.append_gateway_decision_record(
                _record(proposal_fingerprint="c" * 64), idempotency_key="gateway-key-1"
            )
    with database.session() as session, session.begin():
        assert (
            len(
                SqlAlchemyToolGatewayRepository(session).list_gateway_decision_records_bounded(
                    owner_id=OWNER, limit=10
                )
            )
            == 1
        )


def test_insert_race_reconciles_to_replayed(database: Database) -> None:
    stored = _persist(database)
    row = _row(database)
    with database.session() as session, session.begin():
        repo = SqlAlchemyToolGatewayRepository(session)
        repo._use_savepoint = True
        with (
            patch.object(repo, "_by_key", side_effect=[None, row]),
            patch.object(repo, "_by_id", return_value=None),
        ):
            result = repo.append_gateway_decision_record(stored, idempotency_key="gateway-key-1")
            assert len(session.new) == 0
    assert result.disposition is GatewayDisposition.REPLAYED
    assert result.record == stored
    with database.session() as session, session.begin():
        assert (
            len(
                SqlAlchemyToolGatewayRepository(session).list_gateway_decision_records_bounded(
                    owner_id=OWNER, limit=10
                )
            )
            == 1
        )
