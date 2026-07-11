"""Atomic owner-scoped persistence for governed research memory."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import ColumnElement, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import InstrumentedAttribute, Session

from orbitmind.core.errors import ValidationError
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.persistence.database import Database
from orbitmind.persistence.research_models import (
    ResearchClaimEvidenceRow,
    ResearchClaimGapRow,
    ResearchClaimRow,
    ResearchCycleEvidenceRow,
    ResearchCycleRow,
    ResearchEvidenceRow,
    ResearchGapRow,
    ResearchInputDuplicateRow,
    ResearchInputRow,
    ResearchLearningClaimRow,
    ResearchLearningConflictRow,
    ResearchLearningGapRow,
    ResearchLearningRow,
    ResearchLearningSupportRow,
)
from orbitmind.research.models import (
    RESEARCH_LEARNING_SCHEMA_VERSION,
    ClaimVerifierStatus,
    ConfidenceLabel,
    ConsentScope,
    DerivedResearchClaim,
    EvidenceReliabilityStatus,
    PrivacyClass,
    ResearchClaimType,
    ResearchCycleRecord,
    ResearchEvidence,
    ResearchEvidenceType,
    ResearchGap,
    ResearchGapType,
    ResearchInput,
    ResearchInputStatus,
    ResearchInputType,
    ResearchLearningRecord,
    ResearchLearningStatus,
    ResearchMetadataItem,
    ResearchSourceType,
    RetentionClass,
)
from orbitmind.research.persistence_safety import (
    validate_persisted_identifier,
    validate_research_cycle_persistence_safety,
)


class SqlAlchemyResearchMemoryRepository:
    """Persist and reconstruct complete research cycles using fresh sessions.

    Each save owns one outer transaction. Helpers flush only; they never commit.
    Evidence identity is owner-scoped and reusable across cycle associations.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def find_evidence(
        self, *, owner_id: str, source_identifier: str, checksum: str
    ) -> ResearchEvidence | None:
        owner = normalize_research_owner_id(owner_id)
        _validate_evidence_identity(source_identifier, checksum)
        with self._database.session() as session:
            row = _find_evidence_row(
                session,
                owner_id=owner,
                source_identifier=source_identifier,
                checksum=checksum,
            )
            return _row_to_evidence(row) if row is not None else None

    def get_cycle(self, *, owner_id: str, cycle_id: str) -> ResearchCycleRecord | None:
        owner = normalize_research_owner_id(owner_id)
        if not cycle_id or len(cycle_id) > 160:
            raise ValidationError("cycle_id must be between 1 and 160 characters")
        with self._database.session() as session:
            return _get_cycle(session, owner_id=owner, cycle_id=cycle_id)

    def save_cycle(self, *, owner_id: str, cycle: ResearchCycleRecord) -> ResearchCycleRecord:
        owner = normalize_research_owner_id(owner_id)
        validate_research_cycle_persistence_safety(cycle)
        try:
            validated_cycle = ResearchCycleRecord.model_validate(cycle.model_dump(mode="python"))
        except PydanticValidationError as exc:
            raise ValidationError("research cycle failed aggregate validation") from exc
        validate_research_cycle_persistence_safety(validated_cycle)
        session = self._database.session()
        try:
            with session.begin():
                persisted = self._save_cycle_in_transaction(
                    session,
                    owner_id=owner,
                    cycle=validated_cycle,
                )
            return persisted
        finally:
            session.close()

    def _save_cycle_in_transaction(
        self,
        session: Session,
        *,
        owner_id: str,
        cycle: ResearchCycleRecord,
    ) -> ResearchCycleRecord:
        if _cycle_row(session, owner_id=owner_id, cycle_id=cycle.cycle_id) is not None:
            raise ValidationError("research cycle already exists for owner")

        resolved_cycle = _resolve_preexisting_evidence(session, owner_id, cycle)
        session.add(_cycle_to_row(owner_id, resolved_cycle))
        input_rows = {
            item.input_id: _input_to_row(owner_id, resolved_cycle.cycle_id, ordinal, item)
            for ordinal, item in enumerate(resolved_cycle.inputs)
        }
        session.add_all(input_rows.values())
        session.flush()

        resolved_cycle = self._insert_new_evidence(
            session,
            owner_id=owner_id,
            cycle=resolved_cycle,
            input_rows=input_rows,
        )
        _validate_persisted_references(session, owner_id, resolved_cycle)

        session.add_all(
            _gap_to_row(owner_id, resolved_cycle.cycle_id, ordinal, gap)
            for ordinal, gap in enumerate(resolved_cycle.gaps)
        )
        session.add(_claim_to_row(owner_id, resolved_cycle.cycle_id, resolved_cycle.claim))
        session.add(_learning_to_row(owner_id, resolved_cycle.cycle_id, resolved_cycle.learning))
        session.flush()

        _persist_input_duplicates(session, owner_id, resolved_cycle)
        _persist_cycle_evidence(session, owner_id, resolved_cycle)
        _persist_claim_links(session, owner_id, resolved_cycle.claim)
        _persist_learning_links(session, owner_id, resolved_cycle.learning)
        session.flush()

        reconstructed = _get_cycle(
            session,
            owner_id=owner_id,
            cycle_id=resolved_cycle.cycle_id,
        )
        if reconstructed is None:
            raise ValidationError("persisted research cycle could not be reconstructed")
        return reconstructed

    def _insert_new_evidence(
        self,
        session: Session,
        *,
        owner_id: str,
        cycle: ResearchCycleRecord,
        input_rows: dict[str, ResearchInputRow],
    ) -> ResearchCycleRecord:
        resolved = cycle
        for evidence in cycle.new_evidence:
            if evidence.evidence_id not in {item.evidence_id for item in resolved.new_evidence}:
                continue
            row = _evidence_to_row(owner_id, evidence)
            if self._database.is_postgres:
                try:
                    with session.begin_nested():
                        session.add(row)
                        session.flush()
                except IntegrityError:
                    session.expire_all()
                    existing = _find_evidence_row(
                        session,
                        owner_id=owner_id,
                        source_identifier=evidence.source_identifier,
                        checksum=evidence.checksum,
                    )
                    if existing is None:
                        raise
                    resolved = _remap_evidence_ids(
                        resolved,
                        {evidence.evidence_id: existing.id},
                    )
                    input_row = input_rows[evidence.input_id]
                    input_row.handling_status = ResearchInputStatus.DUPLICATE.value
            else:
                session.add(row)
                session.flush()
        return resolved


def normalize_research_owner_id(owner_id: str) -> str:
    """Validate the explicit authenticated-owner scope used by persistence."""

    if not owner_id or owner_id.strip() != owner_id or len(owner_id) > 120:
        raise ValidationError("owner_id must be non-empty, unpadded, and at most 120 characters")
    validate_persisted_identifier(owner_id, "research_owner.owner_id")
    return owner_id


def _validate_evidence_identity(source_identifier: str, checksum: str) -> None:
    if not source_identifier or len(source_identifier) > 500:
        raise ValidationError("source_identifier must be between 1 and 500 characters")
    validate_persisted_identifier(source_identifier, "research_evidence.source_identifier")
    if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
        raise ValidationError("research evidence checksum must be lowercase SHA-256")


def _resolve_preexisting_evidence(
    session: Session,
    owner_id: str,
    cycle: ResearchCycleRecord,
) -> ResearchCycleRecord:
    remap: dict[str, str] = {}
    seen: dict[tuple[str, str], str] = {}
    for evidence in cycle.new_evidence:
        identity = (evidence.source_identifier, evidence.checksum)
        existing_id = seen.get(identity)
        if existing_id is None:
            existing = _find_evidence_row(
                session,
                owner_id=owner_id,
                source_identifier=evidence.source_identifier,
                checksum=evidence.checksum,
            )
            existing_id = existing.id if existing is not None else evidence.evidence_id
            seen[identity] = existing_id
        if existing_id != evidence.evidence_id:
            remap[evidence.evidence_id] = existing_id
    return _remap_evidence_ids(cycle, remap) if remap else cycle


def _remap_evidence_ids(
    cycle: ResearchCycleRecord,
    remap: dict[str, str],
) -> ResearchCycleRecord:
    def resolve(evidence_id: str) -> str:
        seen: set[str] = set()
        while evidence_id in remap and evidence_id not in seen:
            seen.add(evidence_id)
            evidence_id = remap[evidence_id]
        return evidence_id

    remapped_input_ids = {
        evidence.input_id: resolve(evidence.evidence_id)
        for evidence in cycle.new_evidence
        if resolve(evidence.evidence_id) != evidence.evidence_id
    }
    inputs = tuple(
        item.model_copy(
            update={
                "handling_status": ResearchInputStatus.DUPLICATE,
                "duplicate_evidence_id": remapped_input_ids[item.input_id],
            }
        )
        if item.input_id in remapped_input_ids
        else item.model_copy(update={"duplicate_evidence_id": resolve(item.duplicate_evidence_id)})
        if item.duplicate_evidence_id is not None
        else item
        for item in cycle.inputs
    )
    new_evidence = tuple(
        evidence
        for evidence in cycle.new_evidence
        if resolve(evidence.evidence_id) == evidence.evidence_id
    )
    referenced = _deduplicate_ids(tuple(resolve(item) for item in cycle.referenced_evidence_ids))
    claim = cycle.claim.model_copy(
        update={
            "evidence_ids": _deduplicate_ids(
                tuple(resolve(item) for item in cycle.claim.evidence_ids)
            )
        }
    )
    learning = cycle.learning.model_copy(
        update={
            "supporting_evidence_ids": _deduplicate_ids(
                tuple(resolve(item) for item in cycle.learning.supporting_evidence_ids)
            ),
            "contradicted_evidence_ids": _deduplicate_ids(
                tuple(resolve(item) for item in cycle.learning.contradicted_evidence_ids)
            ),
        }
    )
    return cycle.model_copy(
        update={
            "inputs": inputs,
            "new_evidence": new_evidence,
            "referenced_evidence_ids": referenced,
            "claim": claim,
            "learning": learning,
        }
    )


def _deduplicate_ids(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _validate_persisted_references(
    session: Session,
    owner_id: str,
    cycle: ResearchCycleRecord,
) -> None:
    required_evidence_ids = set(cycle.referenced_evidence_ids)
    required_evidence_ids.update(item.evidence_id for item in cycle.new_evidence)
    required_evidence_ids.update(
        item.duplicate_evidence_id
        for item in cycle.inputs
        if item.duplicate_evidence_id is not None
    )
    if required_evidence_ids:
        found = set(
            session.execute(
                select(ResearchEvidenceRow.id).where(
                    ResearchEvidenceRow.owner_id == owner_id,
                    ResearchEvidenceRow.id.in_(required_evidence_ids),
                )
            ).scalars()
        )
        if found != required_evidence_ids:
            raise ValidationError("research cycle references missing or cross-owner evidence")

    gap_ids = {gap.gap_id for gap in cycle.gaps}
    if not set(cycle.claim.gap_ids).issubset(gap_ids):
        raise ValidationError("research claim references a gap outside its cycle")
    if not set(cycle.learning.unresolved_gap_ids).issubset(gap_ids):
        raise ValidationError("research learning references a gap outside its cycle")
    if cycle.learning.resulting_claim_ids != (cycle.claim.claim_id,):
        raise ValidationError("research learning references a claim outside its cycle")
    if (
        cycle.claim.epistemic_status is not EpistemicStatus.HYPOTHESIS
        and not cycle.claim.evidence_ids
    ):
        raise ValidationError("non-hypothesis research claims require evidence")


def _cycle_to_row(owner_id: str, cycle: ResearchCycleRecord) -> ResearchCycleRow:
    return ResearchCycleRow(
        id=cycle.cycle_id,
        owner_id=owner_id,
        schema_version=cycle.schema_version,
        request_checksum=cycle.request_checksum,
        request_reference=cycle.request_reference,
        created_at=cycle.created_at,
        completed_at=cycle.completed_at,
        status=cycle.status.value,
        result_reference=cycle.result_reference,
    )


def _input_to_row(
    owner_id: str,
    cycle_id: str,
    ordinal: int,
    item: ResearchInput,
) -> ResearchInputRow:
    return ResearchInputRow(
        id=item.input_id,
        owner_id=owner_id,
        cycle_id=cycle_id,
        ordinal=ordinal,
        input_type=item.input_type.value,
        received_at=item.received_at,
        source_type=item.source_type.value,
        source_identifier=item.source_identifier,
        content_checksum=item.content_checksum,
        consent_scope=item.consent_scope.value,
        privacy_class=item.privacy_class.value,
        retention_class=item.retention_class.value,
        mission_id=item.mission_id,
        handling_status=item.handling_status.value,
        metadata_json=_metadata_to_json(item.metadata),
    )


def _evidence_to_row(owner_id: str, item: ResearchEvidence) -> ResearchEvidenceRow:
    return ResearchEvidenceRow(
        id=item.evidence_id,
        owner_id=owner_id,
        originating_input_id=item.input_id,
        source_identifier=item.source_identifier,
        checksum=item.checksum,
        evidence_type=item.evidence_type.value,
        captured_at=item.captured_at,
        reliability_status=item.reliability_status.value,
        provenance_reference=item.provenance_reference,
        usage_restrictions_json=list(item.usage_restrictions),
        metadata_json=_metadata_to_json(item.metadata),
    )


def _gap_to_row(
    owner_id: str,
    cycle_id: str,
    ordinal: int,
    item: ResearchGap,
) -> ResearchGapRow:
    return ResearchGapRow(
        id=item.gap_id,
        owner_id=owner_id,
        cycle_id=cycle_id,
        ordinal=ordinal,
        gap_type=item.gap_type.value,
        description=item.description,
        detected_at=item.detected_at,
        related_input_id=item.related_input_id,
        effect_on_result=item.effect_on_result,
        recoverable=item.recoverable,
        metadata_json=_metadata_to_json(item.metadata),
    )


def _claim_to_row(
    owner_id: str,
    cycle_id: str,
    item: DerivedResearchClaim,
) -> ResearchClaimRow:
    return ResearchClaimRow(
        id=item.claim_id,
        owner_id=owner_id,
        cycle_id=cycle_id,
        claim_type=item.claim_type.value,
        statement=item.statement,
        epistemic_status=item.epistemic_status.value,
        confidence_label=item.confidence_label.value,
        created_at=item.created_at,
        verifier_status=item.verifier_status.value,
        limitations_json=list(item.limitations),
    )


def _learning_to_row(
    owner_id: str,
    cycle_id: str,
    item: ResearchLearningRecord,
) -> ResearchLearningRow:
    return ResearchLearningRow(
        id=item.learning_id,
        owner_id=owner_id,
        cycle_id=cycle_id,
        topic=item.topic,
        created_at=item.created_at,
        status=item.status.value,
    )


def _persist_input_duplicates(
    session: Session,
    owner_id: str,
    cycle: ResearchCycleRecord,
) -> None:
    for item in cycle.inputs:
        if item.handling_status is ResearchInputStatus.DUPLICATE:
            if item.duplicate_evidence_id is None:
                raise ValidationError("duplicate research input requires an evidence reference")
            session.add(
                ResearchInputDuplicateRow(
                    owner_id=owner_id,
                    input_id=item.input_id,
                    evidence_id=item.duplicate_evidence_id,
                )
            )
        elif item.duplicate_evidence_id is not None:
            raise ValidationError(
                "non-duplicate research input cannot reference duplicate evidence"
            )


def _persist_cycle_evidence(
    session: Session,
    owner_id: str,
    cycle: ResearchCycleRecord,
) -> None:
    new_order = {item.evidence_id: ordinal for ordinal, item in enumerate(cycle.new_evidence)}
    reference_order = {
        evidence_id: ordinal for ordinal, evidence_id in enumerate(cycle.referenced_evidence_ids)
    }
    evidence_ids = tuple(dict.fromkeys((*new_order, *reference_order)))
    session.add_all(
        ResearchCycleEvidenceRow(
            owner_id=owner_id,
            cycle_id=cycle.cycle_id,
            evidence_id=evidence_id,
            new_ordinal=new_order.get(evidence_id),
            reference_ordinal=reference_order.get(evidence_id),
        )
        for evidence_id in evidence_ids
    )


def _persist_claim_links(
    session: Session,
    owner_id: str,
    claim: DerivedResearchClaim,
) -> None:
    session.add_all(
        ResearchClaimEvidenceRow(
            owner_id=owner_id,
            claim_id=claim.claim_id,
            evidence_id=evidence_id,
            ordinal=ordinal,
        )
        for ordinal, evidence_id in enumerate(claim.evidence_ids)
    )
    session.add_all(
        ResearchClaimGapRow(
            owner_id=owner_id,
            claim_id=claim.claim_id,
            gap_id=gap_id,
            ordinal=ordinal,
        )
        for ordinal, gap_id in enumerate(claim.gap_ids)
    )


def _persist_learning_links(
    session: Session,
    owner_id: str,
    learning: ResearchLearningRecord,
) -> None:
    _add_ordered_links(
        session,
        learning.supporting_evidence_ids,
        lambda value, ordinal: ResearchLearningSupportRow(
            owner_id=owner_id,
            learning_id=learning.learning_id,
            evidence_id=value,
            ordinal=ordinal,
        ),
    )
    _add_ordered_links(
        session,
        learning.contradicted_evidence_ids,
        lambda value, ordinal: ResearchLearningConflictRow(
            owner_id=owner_id,
            learning_id=learning.learning_id,
            evidence_id=value,
            ordinal=ordinal,
        ),
    )
    _add_ordered_links(
        session,
        learning.resulting_claim_ids,
        lambda value, ordinal: ResearchLearningClaimRow(
            owner_id=owner_id,
            learning_id=learning.learning_id,
            claim_id=value,
            ordinal=ordinal,
        ),
    )
    _add_ordered_links(
        session,
        learning.unresolved_gap_ids,
        lambda value, ordinal: ResearchLearningGapRow(
            owner_id=owner_id,
            learning_id=learning.learning_id,
            gap_id=value,
            ordinal=ordinal,
        ),
    )


def _add_ordered_links(
    session: Session,
    values: Sequence[str],
    row_factory: Callable[[str, int], object],
) -> None:
    session.add_all(row_factory(value, ordinal) for ordinal, value in enumerate(values))


def _get_cycle(
    session: Session,
    *,
    owner_id: str,
    cycle_id: str,
) -> ResearchCycleRecord | None:
    cycle_row = _cycle_row(session, owner_id=owner_id, cycle_id=cycle_id)
    if cycle_row is None:
        return None

    input_rows = tuple(
        session.execute(
            select(ResearchInputRow)
            .where(
                ResearchInputRow.owner_id == owner_id,
                ResearchInputRow.cycle_id == cycle_id,
            )
            .order_by(ResearchInputRow.ordinal)
        ).scalars()
    )
    input_ids = tuple(row.id for row in input_rows)
    duplicate_by_input: dict[str, str] = {}
    if input_ids:
        duplicate_by_input = {
            row.input_id: row.evidence_id
            for row in session.execute(
                select(ResearchInputDuplicateRow).where(
                    ResearchInputDuplicateRow.owner_id == owner_id,
                    ResearchInputDuplicateRow.input_id.in_(input_ids),
                )
            ).scalars()
        }

    cycle_evidence_rows = tuple(
        session.execute(
            select(ResearchCycleEvidenceRow).where(
                ResearchCycleEvidenceRow.owner_id == owner_id,
                ResearchCycleEvidenceRow.cycle_id == cycle_id,
            )
        ).scalars()
    )
    evidence_ids = tuple(row.evidence_id for row in cycle_evidence_rows)
    evidence_by_id: dict[str, ResearchEvidence] = {}
    if evidence_ids:
        evidence_by_id = {
            row.id: _row_to_evidence(row)
            for row in session.execute(
                select(ResearchEvidenceRow).where(
                    ResearchEvidenceRow.owner_id == owner_id,
                    ResearchEvidenceRow.id.in_(evidence_ids),
                )
            ).scalars()
        }
    new_evidence = tuple(
        evidence_by_id[row.evidence_id]
        for row in sorted(
            (item for item in cycle_evidence_rows if item.new_ordinal is not None),
            key=lambda item: item.new_ordinal if item.new_ordinal is not None else -1,
        )
    )
    referenced_evidence_ids = tuple(
        row.evidence_id
        for row in sorted(
            (item for item in cycle_evidence_rows if item.reference_ordinal is not None),
            key=lambda item: item.reference_ordinal if item.reference_ordinal is not None else -1,
        )
    )

    gap_rows = tuple(
        session.execute(
            select(ResearchGapRow)
            .where(
                ResearchGapRow.owner_id == owner_id,
                ResearchGapRow.cycle_id == cycle_id,
            )
            .order_by(ResearchGapRow.ordinal)
        ).scalars()
    )
    claim_row = session.execute(
        select(ResearchClaimRow).where(
            ResearchClaimRow.owner_id == owner_id,
            ResearchClaimRow.cycle_id == cycle_id,
        )
    ).scalar_one()
    learning_row = session.execute(
        select(ResearchLearningRow).where(
            ResearchLearningRow.owner_id == owner_id,
            ResearchLearningRow.cycle_id == cycle_id,
        )
    ).scalar_one()

    claim_evidence_ids = _ordered_link_values(
        session,
        ResearchClaimEvidenceRow.evidence_id,
        ResearchClaimEvidenceRow.ordinal,
        ResearchClaimEvidenceRow.claim_id == claim_row.id,
        ResearchClaimEvidenceRow.owner_id == owner_id,
    )
    claim_gap_ids = _ordered_link_values(
        session,
        ResearchClaimGapRow.gap_id,
        ResearchClaimGapRow.ordinal,
        ResearchClaimGapRow.claim_id == claim_row.id,
        ResearchClaimGapRow.owner_id == owner_id,
    )
    learning_support = _ordered_link_values(
        session,
        ResearchLearningSupportRow.evidence_id,
        ResearchLearningSupportRow.ordinal,
        ResearchLearningSupportRow.learning_id == learning_row.id,
        ResearchLearningSupportRow.owner_id == owner_id,
    )
    learning_conflicts = _ordered_link_values(
        session,
        ResearchLearningConflictRow.evidence_id,
        ResearchLearningConflictRow.ordinal,
        ResearchLearningConflictRow.learning_id == learning_row.id,
        ResearchLearningConflictRow.owner_id == owner_id,
    )
    learning_claims = _ordered_link_values(
        session,
        ResearchLearningClaimRow.claim_id,
        ResearchLearningClaimRow.ordinal,
        ResearchLearningClaimRow.learning_id == learning_row.id,
        ResearchLearningClaimRow.owner_id == owner_id,
    )
    learning_gaps = _ordered_link_values(
        session,
        ResearchLearningGapRow.gap_id,
        ResearchLearningGapRow.ordinal,
        ResearchLearningGapRow.learning_id == learning_row.id,
        ResearchLearningGapRow.owner_id == owner_id,
    )

    claim = DerivedResearchClaim(
        claim_id=claim_row.id,
        claim_type=ResearchClaimType(claim_row.claim_type),
        statement=claim_row.statement,
        epistemic_status=EpistemicStatus(claim_row.epistemic_status),
        confidence_label=ConfidenceLabel(claim_row.confidence_label),
        evidence_ids=claim_evidence_ids,
        gap_ids=claim_gap_ids,
        created_at=claim_row.created_at,
        verifier_status=ClaimVerifierStatus(claim_row.verifier_status),
        limitations=tuple(claim_row.limitations_json),
    )
    learning = ResearchLearningRecord(
        learning_id=learning_row.id,
        cycle_id=learning_row.cycle_id,
        topic=learning_row.topic,
        supporting_evidence_ids=learning_support,
        contradicted_evidence_ids=learning_conflicts,
        resulting_claim_ids=learning_claims,
        unresolved_gap_ids=learning_gaps,
        created_at=learning_row.created_at,
        status=ResearchLearningStatus(learning_row.status),
    )
    return ResearchCycleRecord(
        schema_version=RESEARCH_LEARNING_SCHEMA_VERSION,
        cycle_id=cycle_row.id,
        request_checksum=cycle_row.request_checksum,
        request_reference=cycle_row.request_reference,
        created_at=cycle_row.created_at,
        completed_at=cycle_row.completed_at,
        status=ResearchLearningStatus(cycle_row.status),
        result_reference=cycle_row.result_reference,
        inputs=tuple(_row_to_input(row, duplicate_by_input.get(row.id)) for row in input_rows),
        new_evidence=new_evidence,
        referenced_evidence_ids=referenced_evidence_ids,
        gaps=tuple(_row_to_gap(row) for row in gap_rows),
        claim=claim,
        learning=learning,
    )


def _ordered_link_values(
    session: Session,
    value_column: InstrumentedAttribute[str],
    order_column: InstrumentedAttribute[int],
    *conditions: ColumnElement[bool],
) -> tuple[str, ...]:
    return tuple(
        session.execute(select(value_column).where(*conditions).order_by(order_column)).scalars()
    )


def _cycle_row(
    session: Session,
    *,
    owner_id: str,
    cycle_id: str,
) -> ResearchCycleRow | None:
    return session.execute(
        select(ResearchCycleRow).where(
            ResearchCycleRow.id == cycle_id,
            ResearchCycleRow.owner_id == owner_id,
        )
    ).scalar_one_or_none()


def _find_evidence_row(
    session: Session,
    *,
    owner_id: str,
    source_identifier: str,
    checksum: str,
) -> ResearchEvidenceRow | None:
    return session.execute(
        select(ResearchEvidenceRow).where(
            ResearchEvidenceRow.owner_id == owner_id,
            ResearchEvidenceRow.source_identifier == source_identifier,
            ResearchEvidenceRow.checksum == checksum,
        )
    ).scalar_one_or_none()


def _row_to_input(row: ResearchInputRow, duplicate_id: str | None) -> ResearchInput:
    return ResearchInput(
        input_id=row.id,
        input_type=ResearchInputType(row.input_type),
        received_at=row.received_at,
        source_type=ResearchSourceType(row.source_type),
        source_identifier=row.source_identifier,
        content_checksum=row.content_checksum,
        consent_scope=ConsentScope(row.consent_scope),
        privacy_class=PrivacyClass(row.privacy_class),
        retention_class=RetentionClass(row.retention_class),
        handling_status=ResearchInputStatus(row.handling_status),
        mission_id=row.mission_id,
        duplicate_evidence_id=duplicate_id,
        metadata=_metadata_from_json(row.metadata_json),
    )


def _row_to_evidence(row: ResearchEvidenceRow) -> ResearchEvidence:
    return ResearchEvidence(
        evidence_id=row.id,
        input_id=row.originating_input_id,
        source_identifier=row.source_identifier,
        captured_at=row.captured_at,
        checksum=row.checksum,
        evidence_type=ResearchEvidenceType(row.evidence_type),
        reliability_status=EvidenceReliabilityStatus(row.reliability_status),
        provenance_reference=row.provenance_reference,
        usage_restrictions=tuple(row.usage_restrictions_json),
        metadata=_metadata_from_json(row.metadata_json),
    )


def _row_to_gap(row: ResearchGapRow) -> ResearchGap:
    return ResearchGap(
        gap_id=row.id,
        gap_type=ResearchGapType(row.gap_type),
        description=row.description,
        detected_at=row.detected_at,
        related_input_id=row.related_input_id,
        effect_on_result=row.effect_on_result,
        recoverable=row.recoverable,
        metadata=_metadata_from_json(row.metadata_json),
    )


def _metadata_to_json(items: Sequence[ResearchMetadataItem]) -> list[dict[str, str]]:
    return [item.model_dump(mode="json") for item in items]


def _metadata_from_json(items: Sequence[dict[str, str]]) -> tuple[ResearchMetadataItem, ...]:
    return tuple(ResearchMetadataItem.model_validate(item) for item in items)
