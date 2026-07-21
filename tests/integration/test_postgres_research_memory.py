"""Live PostgreSQL tests for durable governed research memory.

The disposable database must already be migrated to Alembic head. These tests never
call ORM ``create_all()``, so the migration remains the schema authority.
"""

from __future__ import annotations

import itertools
import json
import os
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import event, inspect, select, text

from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import ValidationError
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.persistence.database import Database
from orbitmind.persistence.research_models import (
    ResearchClaimEvidenceRow,
    ResearchClaimRow,
    ResearchGapRow,
)
from orbitmind.persistence.research_repository import SqlAlchemyResearchMemoryRepository
from orbitmind.research.models import (
    ConfidenceLabel,
    EvidenceReliabilityStatus,
    NormalizedResearchDocument,
    ResearchCycleRecord,
    ResearchDocumentAvailability,
    ResearchEvidence,
    ResearchEvidenceType,
    ResearchGapType,
    ResearchInputStatus,
    ResearchInputType,
    ResearchLearningStatus,
    ResearchMetadataItem,
    ResearchRequest,
)
from orbitmind.research.persistence_safety import ResearchPersistenceSafetyError
from orbitmind.research.service import GovernedResearchLearningService

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=UTC)
REQUEST = ResearchRequest(
    topic="durable communication planning fixture",
    question="What is the predicted next communication window?",
)
RAW_PATH_MARKER = "C:\\private\\research-source.txt"
RAW_SECRET_MARKER = "secret-value-must-remain-transient"

_TABLES = (
    "research_learning_gaps",
    "research_learning_claims",
    "research_learning_conflicts",
    "research_learning_support",
    "research_claim_gaps",
    "research_claim_evidence",
    "research_input_duplicates",
    "research_cycle_evidence",
    "research_learning_records",
    "research_claims",
    "research_gaps",
    "research_evidence",
    "research_inputs",
    "research_cycles",
)


class SequentialIds:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self._values = itertools.count(1)

    def __call__(self) -> str:
        return f"{self._prefix}-{next(self._values):04d}"


class CapturingRepository:
    """Build a typed aggregate without durable writes for repository contract tests."""

    def __init__(self) -> None:
        self.cycle: ResearchCycleRecord | None = None
        self.evidence: dict[tuple[str, str, str], ResearchEvidence] = {}

    def find_evidence(
        self, *, owner_id: str, source_identifier: str, checksum: str
    ) -> ResearchEvidence | None:
        return self.evidence.get((owner_id, source_identifier, checksum))

    def save_cycle(self, *, owner_id: str, cycle: ResearchCycleRecord) -> ResearchCycleRecord:
        self.cycle = cycle
        for item in cycle.new_evidence:
            self.evidence[(owner_id, item.source_identifier, item.checksum)] = item
        return cycle

    def get_cycle(self, *, owner_id: str, cycle_id: str) -> ResearchCycleRecord | None:
        del owner_id
        if self.cycle is not None and self.cycle.cycle_id == cycle_id:
            return self.cycle
        return None


@pytest.fixture
def pg_db() -> Database:
    """Return a migrated disposable PostgreSQL database with empty research tables."""

    assert _PG_URL is not None
    database = Database(_PG_URL)
    assert database.is_postgres
    with database.engine.begin() as connection:
        connection.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield database
    database.engine.dispose()


def _metadata(**values: str) -> tuple[ResearchMetadataItem, ...]:
    return tuple(ResearchMetadataItem(key=key, value=value) for key, value in values.items())


def _document(
    source_identifier: str,
    content: str,
    evidence_type: ResearchEvidenceType,
    *,
    reliability: EvidenceReliabilityStatus = EvidenceReliabilityStatus.ACCEPTED,
    metadata: tuple[ResearchMetadataItem, ...] = (),
    provenance_reference: str | None = None,
    usage_restrictions: tuple[str, ...] = ("offline persistence test only",),
) -> NormalizedResearchDocument:
    return NormalizedResearchDocument(
        source_identifier=source_identifier,
        content=content,
        declared_checksum=sha256_text(content),
        captured_at=NOW,
        evidence_type=evidence_type,
        reliability_status=reliability,
        provenance_reference=provenance_reference or f"fixture:{source_identifier}",
        usage_restrictions=usage_restrictions,
        metadata=metadata,
    )


def _trajectory(
    *,
    source_identifier: str = "trajectory-source",
    content: str = f"Trajectory fixture {RAW_PATH_MARKER} {RAW_SECRET_MARKER}",
    start: str = "2026-07-11T12:30:00Z",
    end: str = "2026-07-11T12:40:00Z",
    reliability: EvidenceReliabilityStatus = EvidenceReliabilityStatus.ACCEPTED,
) -> NormalizedResearchDocument:
    return _document(
        source_identifier,
        content,
        ResearchEvidenceType.TRAJECTORY_SOURCE,
        reliability=reliability,
        metadata=_metadata(window_start_utc=start, window_end_utc=end),
    )


def _observer(*, source_identifier: str = "observer-source") -> NormalizedResearchDocument:
    return _document(
        source_identifier,
        "Observer fixture coordinates.",
        ResearchEvidenceType.OBSERVER_CONTEXT,
    )


def _invalid_document() -> NormalizedResearchDocument:
    return NormalizedResearchDocument(
        source_identifier="invalid-source",
        content="checksum-invalid content",
        declared_checksum="0" * 64,
        captured_at=NOW,
        provenance_reference="fixture:invalid-source",
        usage_restrictions=("offline persistence test only",),
    )


def _unavailable_document() -> NormalizedResearchDocument:
    return NormalizedResearchDocument(
        source_identifier="unavailable-source",
        availability=ResearchDocumentAvailability.UNAVAILABLE,
    )


def _make_cycle(
    prefix: str,
    documents: Sequence[NormalizedResearchDocument] | None = None,
) -> ResearchCycleRecord:
    repository = CapturingRepository()
    service = GovernedResearchLearningService(
        repository=repository,
        owner_id="owner-a",
        id_factory=SequentialIds(prefix),
        clock=lambda: NOW,
    )
    service.run_cycle(REQUEST, tuple(documents or (_trajectory(), _observer())))
    assert repository.cycle is not None
    return repository.cycle


def _run_cycle(
    database: Database,
    *,
    owner_id: str,
    prefix: str,
    documents: Sequence[NormalizedResearchDocument] | None = None,
) -> ResearchCycleRecord:
    repository = SqlAlchemyResearchMemoryRepository(database)
    result = GovernedResearchLearningService(
        repository=repository,
        owner_id=owner_id,
        id_factory=SequentialIds(prefix),
        clock=lambda: NOW,
    ).run_cycle(REQUEST, tuple(documents or (_trajectory(), _observer())))
    cycle_id = result.method_and_evidence_reference.removeprefix("research-cycle:")
    cycle = repository.get_cycle(owner_id=owner_id, cycle_id=cycle_id)
    assert cycle is not None
    return cycle


def _count(database: Database, table: str) -> int:
    with database.engine.connect() as connection:
        return int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


type CycleMutation = Callable[[ResearchCycleRecord, str], ResearchCycleRecord]


def _replace_input(
    cycle: ResearchCycleRecord,
    *,
    index: int,
    updates: dict[str, Any],
) -> ResearchCycleRecord:
    inputs = list(cycle.inputs)
    inputs[index] = inputs[index].model_copy(update=updates)
    return cycle.model_copy(update={"inputs": tuple(inputs)})


def _replace_evidence(
    cycle: ResearchCycleRecord,
    *,
    index: int,
    updates: dict[str, Any],
) -> ResearchCycleRecord:
    evidence = list(cycle.new_evidence)
    evidence[index] = evidence[index].model_copy(update=updates)
    return cycle.model_copy(update={"new_evidence": tuple(evidence)})


def _with_input_source(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return _replace_input(cycle, index=1, updates={"source_identifier": marker})


def _with_evidence_source(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return _replace_evidence(cycle, index=0, updates={"source_identifier": marker})


def _with_provenance(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return _replace_evidence(cycle, index=0, updates={"provenance_reference": marker})


def _with_metadata_key(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    metadata = (ResearchMetadataItem.model_construct(key=marker, value="fixture-value"),)
    return _replace_input(cycle, index=1, updates={"metadata": metadata})


def _with_metadata_value(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    metadata = (ResearchMetadataItem.model_construct(key="note", value=marker),)
    return _replace_evidence(cycle, index=0, updates={"metadata": metadata})


def _with_usage_restriction(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return _replace_evidence(cycle, index=0, updates={"usage_restrictions": (marker,)})


def _with_learning_topic(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return cycle.model_copy(
        update={"learning": cycle.learning.model_copy(update={"topic": marker})}
    )


def _with_result_reference(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return cycle.model_copy(update={"result_reference": marker})


def _with_request_reference(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return cycle.model_copy(update={"request_reference": marker})


def _with_claim_statement(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return cycle.model_copy(update={"claim": cycle.claim.model_copy(update={"statement": marker})})


def _with_gap_description(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    gaps = list(cycle.gaps)
    gaps[0] = gaps[0].model_copy(update={"description": marker})
    return cycle.model_copy(update={"gaps": tuple(gaps)})


def _with_mission_reference(cycle: ResearchCycleRecord, marker: str) -> ResearchCycleRecord:
    return _replace_input(cycle, index=1, updates={"mission_id": marker})


def _research_rows_json(database: Database) -> str:
    with database.engine.connect() as connection:
        rows = {
            table: [
                dict(row) for row in connection.execute(text(f"SELECT * FROM {table}")).mappings()
            ]
            for table in _TABLES
        }
    return json.dumps(rows, default=str, sort_keys=True)


def test_complete_cycle_round_trips_in_a_new_session_without_raw_content(pg_db: Database) -> None:
    expected = _make_cycle("roundtrip")
    repository = SqlAlchemyResearchMemoryRepository(pg_db)

    saved = repository.save_cycle(owner_id="owner-a", cycle=expected)
    loaded = SqlAlchemyResearchMemoryRepository(pg_db).get_cycle(
        owner_id="owner-a",
        cycle_id=expected.cycle_id,
    )

    assert saved == expected
    assert loaded == expected
    assert loaded is not None
    assert loaded.claim.evidence_ids == loaded.referenced_evidence_ids
    assert loaded.learning.resulting_claim_ids == (loaded.claim.claim_id,)

    inspector = inspect(pg_db.engine)
    all_columns = {column["name"] for table in _TABLES for column in inspector.get_columns(table)}
    assert "content" not in all_columns
    assert "raw_body" not in all_columns
    assert "filesystem_path" not in all_columns
    with pg_db.engine.connect() as connection:
        stored_text = json.dumps(
            {
                "inputs": connection.execute(
                    text("SELECT source_identifier, metadata_json FROM research_inputs")
                )
                .mappings()
                .all(),
                "evidence": connection.execute(
                    text(
                        "SELECT source_identifier, provenance_reference, metadata_json "
                        "FROM research_evidence"
                    )
                )
                .mappings()
                .all(),
                "claims": connection.execute(
                    text("SELECT statement, limitations_json FROM research_claims")
                )
                .mappings()
                .all(),
            },
            default=str,
        )
    assert RAW_PATH_MARKER not in stored_text
    assert RAW_SECRET_MARKER not in stored_text


@pytest.mark.parametrize(
    ("case_name", "marker", "mutation"),
    (
        ("windows input source", r"C:\private\research.txt", _with_input_source),
        ("posix evidence source", "/tmp/provider-response.json", _with_evidence_source),
        ("file provenance", "file:///home/user/research.json", _with_provenance),
        ("sensitive metadata key", "api_key", _with_metadata_key),
        (
            "token metadata value",
            "ghp_abcdefghijklmnopqrstuvwxyz1234567890",
            _with_metadata_value,
        ),
        ("authorization restriction", "Authorization: Bearer abc123", _with_usage_restriction),
        ("learning path", "/home/user/private-topic.txt", _with_learning_topic),
        (
            "credential https result",
            "https://user:password@example.com/data",
            _with_result_reference,
        ),
        (
            "credential database request",
            "postgresql://user:password@localhost/db",
            _with_request_reference,
        ),
        ("claim secret", "client_secret=claim-secret-value", _with_claim_statement),
        ("gap secret", "password=gap-secret-value", _with_gap_description),
        ("mission path", r"D:\private\mission.txt", _with_mission_reference),
    ),
)
def test_sensitive_structured_fields_fail_before_any_postgres_row_remains(
    pg_db: Database,
    case_name: str,
    marker: str,
    mutation: CycleMutation,
) -> None:
    del case_name
    base_cycle = _make_cycle(
        "sensitive",
        (_trajectory(), _observer(), _invalid_document()),
    )
    unsafe_cycle = mutation(base_cycle, marker)

    with pytest.raises(ResearchPersistenceSafetyError) as exc_info:
        SqlAlchemyResearchMemoryRepository(pg_db).save_cycle(
            owner_id="owner-a",
            cycle=unsafe_cycle,
        )

    assert exc_info.value.code == "research_persistence_policy"
    assert marker not in str(exc_info.value)
    remaining = {table: _count(pg_db, table) for table in _TABLES}
    assert set(remaining.values()) == {0}
    assert marker not in _research_rows_json(pg_db)


def test_safe_structured_values_persist_without_false_positives(pg_db: Database) -> None:
    trajectory = _document(
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544",
        "Bounded trajectory fixture.",
        ResearchEvidenceType.TRAJECTORY_SOURCE,
        provenance_reference="https://celestrak.org/NORAD/documentation/gp-data-formats.php",
        usage_restrictions=("token budget is bounded; fixture use only",),
        metadata=_metadata(
            window_start_utc="2026-07-11T12:30:00Z",
            window_end_utc="2026-07-11T12:40:00Z",
            note="secret-sharing protocol review",
        ),
    )
    observer = _document(
        "urn:orbitmind:evidence:observer-123",
        "Bounded observer fixture.",
        ResearchEvidenceType.OBSERVER_CONTEXT,
        provenance_reference="source:celestrak:25544",
        usage_restrictions=("credential model documentation; no credentials stored",),
        metadata=_metadata(method="private orbit determination review"),
    )

    cycle = _run_cycle(
        pg_db,
        owner_id="owner-a",
        prefix="safe-values",
        documents=(trajectory, observer),
    )

    assert len(cycle.new_evidence) == 2
    assert {item.source_identifier for item in cycle.new_evidence} == {
        "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544",
        "urn:orbitmind:evidence:observer-123",
    }


def test_within_and_cross_cycle_duplicate_evidence_reuses_rows(pg_db: Database) -> None:
    first = _run_cycle(
        pg_db,
        owner_id="owner-a",
        prefix="dedup-a",
        documents=(_trajectory(), _observer(), _trajectory()),
    )
    second = _run_cycle(
        pg_db,
        owner_id="owner-a",
        prefix="dedup-b",
    )

    assert len(first.new_evidence) == 2
    assert any(item.handling_status is ResearchInputStatus.DUPLICATE for item in first.inputs)
    assert second.new_evidence == ()
    assert all(
        item.handling_status is ResearchInputStatus.DUPLICATE
        for item in second.inputs
        if item.input_type is not ResearchInputType.USER_COMMAND
    )
    assert _count(pg_db, "research_evidence") == 2
    assert _count(pg_db, "research_input_duplicates") == 3


def test_evidence_identity_preserves_changes_sources_and_conflicts(pg_db: Database) -> None:
    first = _run_cycle(pg_db, owner_id="owner-a", prefix="identity-a")
    changed = _run_cycle(
        pg_db,
        owner_id="owner-a",
        prefix="identity-b",
        documents=(
            _trajectory(content="Changed trajectory source content."),
            _observer(),
        ),
    )
    other_source = _run_cycle(
        pg_db,
        owner_id="owner-a",
        prefix="identity-c",
        documents=(
            _trajectory(source_identifier="trajectory-source-copy"),
            _observer(),
        ),
    )
    conflicting = _run_cycle(
        pg_db,
        owner_id="owner-a",
        prefix="identity-d",
        documents=(
            _trajectory(),
            _trajectory(
                source_identifier="conflicting-trajectory",
                content="Conflicting trajectory source.",
                start="2026-07-11T13:00:00Z",
                end="2026-07-11T13:10:00Z",
                reliability=EvidenceReliabilityStatus.CONFLICTING,
            ),
            _observer(),
        ),
    )

    assert first.new_evidence
    assert {item.source_identifier for item in changed.new_evidence} == {"trajectory-source"}
    assert {item.source_identifier for item in other_source.new_evidence} == {
        "trajectory-source-copy"
    }
    assert any(
        item.reliability_status is EvidenceReliabilityStatus.CONFLICTING
        for item in conflicting.new_evidence
    )
    assert ResearchGapType.CONFLICTING_EVIDENCE in {gap.gap_type for gap in conflicting.gaps}
    assert conflicting.learning.status is ResearchLearningStatus.INSUFFICIENT_EVIDENCE
    assert _count(pg_db, "research_evidence") == 5


def test_gaps_and_claim_associations_remain_cycle_scoped(pg_db: Database) -> None:
    cycle = _run_cycle(
        pg_db,
        owner_id="owner-a",
        prefix="gaps",
        documents=(_trajectory(), _observer(), _invalid_document(), _unavailable_document()),
    )

    assert {gap.gap_type for gap in cycle.gaps} == {
        ResearchGapType.INVALID_CHECKSUM,
        ResearchGapType.SOURCE_UNAVAILABLE,
    }
    assert cycle.claim.gap_ids == tuple(gap.gap_id for gap in cycle.gaps)
    with pg_db.session() as session:
        persisted_gap_ids = set(
            session.execute(
                select(ResearchGapRow.id).where(
                    ResearchGapRow.owner_id == "owner-a",
                    ResearchGapRow.cycle_id == cycle.cycle_id,
                )
            ).scalars()
        )
        claim_links = set(
            session.execute(
                select(ResearchClaimEvidenceRow.evidence_id).where(
                    ResearchClaimEvidenceRow.owner_id == "owner-a",
                    ResearchClaimEvidenceRow.claim_id == cycle.claim.claim_id,
                )
            ).scalars()
        )
    assert persisted_gap_ids == {gap.gap_id for gap in cycle.gaps}
    assert claim_links == set(cycle.claim.evidence_ids)


def test_missing_evidence_and_non_hypothesis_without_evidence_fail_closed(
    pg_db: Database,
) -> None:
    repository = SqlAlchemyResearchMemoryRepository(pg_db)
    valid = _make_cycle("invalid-ref")
    missing_id = "missing-evidence"
    missing_claim = valid.claim.model_copy(update={"evidence_ids": (missing_id,)})
    missing_learning = valid.learning.model_copy(update={"supporting_evidence_ids": (missing_id,)})
    missing_cycle = valid.model_copy(
        update={
            "new_evidence": (),
            "referenced_evidence_ids": (missing_id,),
            "claim": missing_claim,
            "learning": missing_learning,
        }
    )
    with pytest.raises(ValidationError, match="missing or cross-owner evidence"):
        repository.save_cycle(owner_id="owner-a", cycle=missing_cycle)

    unsupported_claim = valid.claim.model_copy(
        update={
            "epistemic_status": EpistemicStatus.MODEL_ESTIMATE,
            "confidence_label": ConfidenceLabel.SUPPORTED,
            "evidence_ids": (),
        }
    )
    unsupported_learning = valid.learning.model_copy(update={"supporting_evidence_ids": ()})
    unsupported_cycle = valid.model_copy(
        update={
            "referenced_evidence_ids": (),
            "claim": unsupported_claim,
            "learning": unsupported_learning,
        }
    )
    with pytest.raises(ValidationError, match="aggregate validation"):
        repository.save_cycle(owner_id="owner-a", cycle=unsupported_cycle)
    assert _count(pg_db, "research_cycles") == 0


def test_owner_isolation_and_deduplication_do_not_cross_owners(pg_db: Database) -> None:
    owner_a = _run_cycle(pg_db, owner_id="owner-a", prefix="owner-a")
    owner_b = _run_cycle(pg_db, owner_id="owner-b", prefix="owner-b")
    repository = SqlAlchemyResearchMemoryRepository(pg_db)

    assert repository.get_cycle(owner_id="owner-a", cycle_id=owner_a.cycle_id) == owner_a
    assert repository.get_cycle(owner_id="owner-b", cycle_id=owner_a.cycle_id) is None
    assert (
        repository.find_evidence(
            owner_id="owner-b",
            source_identifier=owner_a.new_evidence[0].source_identifier,
            checksum=owner_a.new_evidence[0].checksum,
        )
        == owner_b.new_evidence[0]
    )
    assert owner_a.new_evidence[0].evidence_id != owner_b.new_evidence[0].evidence_id
    assert _count(pg_db, "research_evidence") == 4


def test_claim_cannot_link_to_evidence_owned_by_another_owner(pg_db: Database) -> None:
    owner_a = _run_cycle(pg_db, owner_id="owner-a", prefix="foreign-a")
    owner_b = _make_cycle("foreign-b")
    foreign_ids = owner_a.referenced_evidence_ids
    duplicate_inputs = []
    evidence_index = 0
    for item in owner_b.inputs:
        if item.input_type is ResearchInputType.USER_COMMAND:
            duplicate_inputs.append(item)
            continue
        duplicate_inputs.append(
            item.model_copy(
                update={
                    "handling_status": ResearchInputStatus.DUPLICATE,
                    "duplicate_evidence_id": foreign_ids[evidence_index],
                }
            )
        )
        evidence_index += 1
    foreign_claim = owner_b.claim.model_copy(update={"evidence_ids": foreign_ids})
    foreign_learning = owner_b.learning.model_copy(update={"supporting_evidence_ids": foreign_ids})
    foreign_cycle = owner_b.model_copy(
        update={
            "inputs": tuple(duplicate_inputs),
            "new_evidence": (),
            "referenced_evidence_ids": foreign_ids,
            "claim": foreign_claim,
            "learning": foreign_learning,
        }
    )

    with pytest.raises(ValidationError, match="missing or cross-owner evidence"):
        SqlAlchemyResearchMemoryRepository(pg_db).save_cycle(
            owner_id="owner-b",
            cycle=foreign_cycle,
        )
    assert (
        SqlAlchemyResearchMemoryRepository(pg_db).get_cycle(
            owner_id="owner-b",
            cycle_id=foreign_cycle.cycle_id,
        )
        is None
    )


def test_forced_mid_save_failure_rolls_back_every_research_row(pg_db: Database) -> None:
    cycle = _make_cycle(
        "rollback",
        (_trajectory(), _observer(), _invalid_document()),
    )

    def fail_claim_insert(
        mapper: Any,
        connection: Any,
        target: ResearchClaimRow,
    ) -> None:
        del mapper, connection, target
        raise RuntimeError("forced research claim persistence failure")

    event.listen(ResearchClaimRow, "before_insert", fail_claim_insert)
    try:
        with pytest.raises(RuntimeError, match="forced research claim persistence failure"):
            SqlAlchemyResearchMemoryRepository(pg_db).save_cycle(
                owner_id="owner-a",
                cycle=cycle,
            )
    finally:
        event.remove(ResearchClaimRow, "before_insert", fail_claim_insert)

    with pg_db.engine.connect() as connection:
        remaining = {
            table: int(connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())
            for table in _TABLES
        }
    assert set(remaining.values()) == {0}


def test_migrated_postgres_schema_has_owner_scoped_integrity_constraints(
    pg_db: Database,
) -> None:
    with pg_db.engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == (
            "a1f4c7e9b230"
        )
    inspector = inspect(pg_db.engine)
    evidence_uniques = {
        item["name"] for item in inspector.get_unique_constraints("research_evidence")
    }
    cycle_evidence_fks = {
        item["name"] for item in inspector.get_foreign_keys("research_cycle_evidence")
    }
    claim_evidence_fks = {
        item["name"] for item in inspector.get_foreign_keys("research_claim_evidence")
    }

    assert "uq_research_evidence_identity" in evidence_uniques
    assert cycle_evidence_fks == {
        "fk_research_cycle_evidence_cycle",
        "fk_research_cycle_evidence_evidence",
    }
    assert claim_evidence_fks == {
        "fk_research_claim_evidence_claim",
        "fk_research_claim_evidence_evidence",
    }
    assert _count(pg_db, "research_cycles") == 0
