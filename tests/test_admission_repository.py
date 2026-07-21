"""Repository-level coverage for Operation Admission v0 persistence (offline SQLite)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest

from orbitmind.admission.contracts import (
    AdmissionOutcome,
    AdmissionReasonCode,
    AdmissionRecord,
    AdmissionRiskClass,
    AdmissionSideEffectClass,
    ProposalActorType,
    ProposalScope,
)
from orbitmind.core.errors import IdempotencyConflictError
from orbitmind.persistence.admission_models import OperationAdmissionRecordRow
from orbitmind.persistence.admission_repository import (
    AdmissionRecordCorruptError,
    SqlAlchemyAdmissionRepository,
)
from orbitmind.persistence.database import Database

T0 = datetime(2026, 7, 21, tzinfo=UTC)
OWNER = "owner-piyush-01"
OWNER_B = "owner-second-02"
HEX = "a" * 64


@pytest.fixture
def database(tmp_path: Any) -> Iterator[Database]:
    db = Database(f"sqlite:///{tmp_path / 'admission-repo.db'}")
    db.create_all()
    try:
        yield db
    finally:
        db.dispose()


def _record(**overrides: Any) -> AdmissionRecord:
    values: dict[str, Any] = {
        "admission_id": "adm-00000001",
        "owner_id": OWNER,
        "proposal_id": "prop-00000001",
        "actor_id": "agent-dev-0001",
        "actor_type": ProposalActorType.AGENT,
        "operation_kind": "read_repository",
        "requested_capability": "repository_read",
        "requested_scope": ProposalScope(resource_type="repository", resource_id="orbitmind-main"),
        "side_effect_class": AdmissionSideEffectClass.LOCAL_READ,
        "risk_class": AdmissionRiskClass.LOW,
        "outcome": AdmissionOutcome.ADMITTED,
        "primary_reason_code": AdmissionReasonCode.ADMITTED_BY_POLICY,
        "reason_codes": (AdmissionReasonCode.ADMITTED_BY_POLICY,),
        "evaluated_at": T0,
        "requested_at": T0,
        "proposal_fingerprint": HEX,
        "decision_checksum": "b" * 64,
        "created_at": T0,
        "provenance_refs": (),
    }
    values.update(overrides)
    return AdmissionRecord(**values)


def test_append_get_and_list_are_owner_scoped(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        stored = repo.append_admission_record(_record(), idempotency_key="key-1")
    assert stored.admission_id == "adm-00000001"

    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        assert repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001") is not None
        # Owner-scoped: another owner cannot read it.
        assert repo.get_admission_record(owner_id=OWNER_B, admission_id="adm-00000001") is None
        assert len(repo.list_admission_records(owner_id=OWNER)) == 1
        assert repo.list_admission_records(owner_id=OWNER_B) == ()


def test_replay_same_fingerprint_returns_stored_record(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        first = repo.append_admission_record(_record(), idempotency_key="key-1")
        second = repo.append_admission_record(_record(), idempotency_key="key-1")
    assert first == second
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        assert len(repo.list_admission_records(owner_id=OWNER)) == 1


def test_replay_conflict_on_different_fingerprint(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        repo.append_admission_record(_record(), idempotency_key="key-1")
        with pytest.raises(IdempotencyConflictError):
            repo.append_admission_record(
                _record(proposal_fingerprint="c" * 64), idempotency_key="key-1"
            )


def test_record_identity_is_derived_from_canonical_payload(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        repo.append_admission_record(_record(), idempotency_key="key-1")
    with database.session() as session:
        row = session.get(OperationAdmissionRecordRow, ("adm-00000001", OWNER))
        assert row is not None
        assert len(row.record_identity) == 64
        # The canonical payload is self-reference-free: it stores neither the
        # record_identity nor a nested canonical_payload key.
        assert "record_identity" not in row.canonical_payload
        assert "canonical_payload" not in row.canonical_payload


def test_read_fails_closed_on_a_tampered_payload(database: Database) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        repo.append_admission_record(_record(), idempotency_key="key-1")
    # Tamper the stored canonical payload directly.
    with database.session() as session, session.begin():
        row = session.get(OperationAdmissionRecordRow, ("adm-00000001", OWNER))
        assert row is not None
        payload = dict(row.canonical_payload)
        payload["outcome"] = "not-a-valid-outcome"
        row.canonical_payload = payload
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        with pytest.raises(AdmissionRecordCorruptError):
            repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001")


# --- canonical-payload identity verification on read ---


def _persist(database: Database) -> None:
    with database.session() as session, session.begin():
        SqlAlchemyAdmissionRepository(session).append_admission_record(
            _record(), idempotency_key="key-1"
        )


def _row(session: Any) -> OperationAdmissionRecordRow:
    row = session.get(OperationAdmissionRecordRow, ("adm-00000001", OWNER))
    assert row is not None
    return row


def test_valid_unchanged_payload_reads_successfully(database: Database) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        loaded = repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001")
    assert loaded is not None
    assert loaded.admission_id == "adm-00000001"


def test_mutating_a_payload_field_without_updating_identity_fails_closed(
    database: Database,
) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        row = _row(session)
        payload = dict(row.canonical_payload)
        # Change a semantic field while leaving record_identity untouched.
        payload["requested_at"] = "2099-01-01T00:00:00Z"
        row.canonical_payload = payload
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        with pytest.raises(AdmissionRecordCorruptError):
            repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001")


def test_mutating_record_identity_without_changing_payload_fails_closed(
    database: Database,
) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        row = _row(session)
        row.record_identity = "f" * 64  # valid length, wrong value
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        with pytest.raises(AdmissionRecordCorruptError):
            repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001")


def test_reordering_payload_keys_preserves_validity(database: Database) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        row = _row(session)
        # Rebuild the payload dict with the keys in reversed order; canonical bytes
        # sort keys, so the identity is unchanged and the read remains valid.
        reordered = {k: row.canonical_payload[k] for k in reversed(list(row.canonical_payload))}
        row.canonical_payload = reordered
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        loaded = repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001")
    assert loaded is not None
    assert loaded.admission_id == "adm-00000001"


def test_non_mapping_payload_fails_closed(database: Database) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        row = _row(session)
        row.canonical_payload = ["not", "a", "mapping"]  # type: ignore[assignment]
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        with pytest.raises(AdmissionRecordCorruptError):
            repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001")


def test_failed_verification_does_not_mutate_or_repair_the_row(database: Database) -> None:
    _persist(database)
    with database.session() as session, session.begin():
        row = _row(session)
        payload = dict(row.canonical_payload)
        payload["requested_at"] = "2099-01-01T00:00:00Z"
        row.canonical_payload = payload
        tampered_payload = dict(payload)
        stored_identity = row.record_identity
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        with pytest.raises(AdmissionRecordCorruptError):
            repo.get_admission_record(owner_id=OWNER, admission_id="adm-00000001")
    # The row is unchanged: verification neither repaired the payload nor the identity.
    with database.session() as session:
        row = _row(session)
        assert dict(row.canonical_payload) == tampered_payload
        assert row.record_identity == stored_identity


def test_replay_and_conflict_behaviour_unchanged_after_identity_verification(
    database: Database,
) -> None:
    with database.session() as session, session.begin():
        repo = SqlAlchemyAdmissionRepository(session)
        first = repo.append_admission_record(_record(), idempotency_key="key-1")
        second = repo.append_admission_record(_record(), idempotency_key="key-1")
        assert first == second
        with pytest.raises(IdempotencyConflictError):
            repo.append_admission_record(
                _record(proposal_fingerprint="c" * 64), idempotency_key="key-1"
            )
