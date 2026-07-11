"""SQLAlchemy rows for durable governed research memory.

Only bounded structured records are represented here. Raw research document content,
provider bodies, credentials, and filesystem paths have no persistence columns.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime


class ResearchCycleRow(Base):
    __tablename__ = "research_cycles"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_research_cycles_owner"),
        Index("ix_research_cycles_owner_created", "owner_id", "created_at"),
        CheckConstraint("length(owner_id) > 0", name="ck_research_cycles_owner"),
        CheckConstraint("length(request_checksum) = 64", name="ck_research_cycles_checksum"),
        CheckConstraint(
            "schema_version = 'governed-research-learning-v1'",
            name="ck_research_cycles_schema",
        ),
        CheckConstraint(
            "status IN ('recorded', 'partial', 'insufficient_evidence')",
            name="ck_research_cycles_status",
        ),
        CheckConstraint("completed_at >= created_at", name="ck_research_cycles_completed"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    schema_version: Mapped[str] = mapped_column(String(48))
    request_checksum: Mapped[str] = mapped_column(String(64))
    request_reference: Mapped[str] = mapped_column(String(96))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(32))
    result_reference: Mapped[str] = mapped_column(String(500))


class ResearchInputRow(Base):
    __tablename__ = "research_inputs"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_research_inputs_owner"),
        UniqueConstraint("owner_id", "cycle_id", "ordinal", name="uq_research_inputs_order"),
        ForeignKeyConstraint(
            ["cycle_id", "owner_id"],
            ["research_cycles.id", "research_cycles.owner_id"],
            name="fk_research_inputs_cycle_owner",
        ),
        Index("ix_research_inputs_cycle", "owner_id", "cycle_id"),
        CheckConstraint("ordinal >= 0", name="ck_research_inputs_ordinal"),
        CheckConstraint(
            "handling_status IN ('accepted', 'duplicate', 'rejected', 'unavailable')",
            name="ck_research_inputs_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    cycle_id: Mapped[str] = mapped_column(String(160))
    ordinal: Mapped[int] = mapped_column(Integer)
    input_type: Mapped[str] = mapped_column(String(32))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    source_type: Mapped[str] = mapped_column(String(32))
    source_identifier: Mapped[str] = mapped_column(String(500))
    content_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_scope: Mapped[str] = mapped_column(String(32))
    privacy_class: Mapped[str] = mapped_column(String(16))
    retention_class: Mapped[str] = mapped_column(String(32))
    mission_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    handling_status: Mapped[str] = mapped_column(String(16))
    metadata_json: Mapped[list[dict[str, str]]] = mapped_column(JSON)


class ResearchEvidenceRow(Base):
    __tablename__ = "research_evidence"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_research_evidence_owner"),
        UniqueConstraint(
            "owner_id",
            "source_identifier",
            "checksum",
            name="uq_research_evidence_identity",
        ),
        ForeignKeyConstraint(
            ["originating_input_id", "owner_id"],
            ["research_inputs.id", "research_inputs.owner_id"],
            name="fk_research_evidence_input_owner",
        ),
        Index("ix_research_evidence_owner_source", "owner_id", "source_identifier"),
        CheckConstraint("length(checksum) = 64", name="ck_research_evidence_checksum"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    originating_input_id: Mapped[str] = mapped_column(String(160))
    source_identifier: Mapped[str] = mapped_column(String(500))
    checksum: Mapped[str] = mapped_column(String(64))
    evidence_type: Mapped[str] = mapped_column(String(32))
    captured_at: Mapped[datetime] = mapped_column(UTCDateTime)
    reliability_status: Mapped[str] = mapped_column(String(16))
    provenance_reference: Mapped[str] = mapped_column(String(500))
    usage_restrictions_json: Mapped[list[str]] = mapped_column(JSON)
    metadata_json: Mapped[list[dict[str, str]]] = mapped_column(JSON)


class ResearchInputDuplicateRow(Base):
    __tablename__ = "research_input_duplicates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["input_id", "owner_id"],
            ["research_inputs.id", "research_inputs.owner_id"],
            name="fk_research_input_duplicates_input",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "owner_id"],
            ["research_evidence.id", "research_evidence.owner_id"],
            name="fk_research_input_duplicates_evidence",
        ),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    input_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(160), index=True)


class ResearchCycleEvidenceRow(Base):
    __tablename__ = "research_cycle_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["cycle_id", "owner_id"],
            ["research_cycles.id", "research_cycles.owner_id"],
            name="fk_research_cycle_evidence_cycle",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "owner_id"],
            ["research_evidence.id", "research_evidence.owner_id"],
            name="fk_research_cycle_evidence_evidence",
        ),
        UniqueConstraint(
            "owner_id", "cycle_id", "new_ordinal", name="uq_research_cycle_evidence_new_order"
        ),
        UniqueConstraint(
            "owner_id",
            "cycle_id",
            "reference_ordinal",
            name="uq_research_cycle_evidence_ref_order",
        ),
        Index("ix_research_cycle_evidence_cycle", "owner_id", "cycle_id"),
        CheckConstraint(
            "new_ordinal IS NOT NULL OR reference_ordinal IS NOT NULL",
            name="ck_research_cycle_evidence_role",
        ),
        CheckConstraint(
            "new_ordinal IS NULL OR new_ordinal >= 0",
            name="ck_research_cycle_evidence_new_order",
        ),
        CheckConstraint(
            "reference_ordinal IS NULL OR reference_ordinal >= 0",
            name="ck_research_cycle_evidence_ref_order",
        ),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    cycle_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    new_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reference_ordinal: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ResearchGapRow(Base):
    __tablename__ = "research_gaps"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_research_gaps_owner"),
        UniqueConstraint("owner_id", "cycle_id", "ordinal", name="uq_research_gaps_order"),
        ForeignKeyConstraint(
            ["cycle_id", "owner_id"],
            ["research_cycles.id", "research_cycles.owner_id"],
            name="fk_research_gaps_cycle_owner",
        ),
        ForeignKeyConstraint(
            ["related_input_id", "owner_id"],
            ["research_inputs.id", "research_inputs.owner_id"],
            name="fk_research_gaps_input_owner",
        ),
        Index("ix_research_gaps_cycle", "owner_id", "cycle_id"),
        CheckConstraint("ordinal >= 0", name="ck_research_gaps_ordinal"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    cycle_id: Mapped[str] = mapped_column(String(160))
    ordinal: Mapped[int] = mapped_column(Integer)
    gap_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(500))
    detected_at: Mapped[datetime] = mapped_column(UTCDateTime)
    related_input_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    effect_on_result: Mapped[str] = mapped_column(String(500))
    recoverable: Mapped[bool] = mapped_column(Boolean)
    metadata_json: Mapped[list[dict[str, str]]] = mapped_column(JSON)


class ResearchClaimRow(Base):
    __tablename__ = "research_claims"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_research_claims_owner"),
        UniqueConstraint("owner_id", "cycle_id", name="uq_research_claims_cycle"),
        ForeignKeyConstraint(
            ["cycle_id", "owner_id"],
            ["research_cycles.id", "research_cycles.owner_id"],
            name="fk_research_claims_cycle_owner",
        ),
        Index("ix_research_claims_cycle", "owner_id", "cycle_id"),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    cycle_id: Mapped[str] = mapped_column(String(160))
    claim_type: Mapped[str] = mapped_column(String(32))
    statement: Mapped[str] = mapped_column(String(2_000))
    epistemic_status: Mapped[str] = mapped_column(String(48))
    confidence_label: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    verifier_status: Mapped[str] = mapped_column(String(32))
    limitations_json: Mapped[list[str]] = mapped_column(JSON)


class ResearchClaimEvidenceRow(Base):
    __tablename__ = "research_claim_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["claim_id", "owner_id"],
            ["research_claims.id", "research_claims.owner_id"],
            name="fk_research_claim_evidence_claim",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "owner_id"],
            ["research_evidence.id", "research_evidence.owner_id"],
            name="fk_research_claim_evidence_evidence",
        ),
        UniqueConstraint(
            "owner_id", "claim_id", "ordinal", name="uq_research_claim_evidence_order"
        ),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class ResearchClaimGapRow(Base):
    __tablename__ = "research_claim_gaps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["claim_id", "owner_id"],
            ["research_claims.id", "research_claims.owner_id"],
            name="fk_research_claim_gaps_claim",
        ),
        ForeignKeyConstraint(
            ["gap_id", "owner_id"],
            ["research_gaps.id", "research_gaps.owner_id"],
            name="fk_research_claim_gaps_gap",
        ),
        UniqueConstraint("owner_id", "claim_id", "ordinal", name="uq_research_claim_gaps_order"),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    gap_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class ResearchLearningRow(Base):
    __tablename__ = "research_learning_records"
    __table_args__ = (
        UniqueConstraint("id", "owner_id", name="uq_research_learning_owner"),
        UniqueConstraint("owner_id", "cycle_id", name="uq_research_learning_cycle"),
        ForeignKeyConstraint(
            ["cycle_id", "owner_id"],
            ["research_cycles.id", "research_cycles.owner_id"],
            name="fk_research_learning_cycle_owner",
        ),
        Index("ix_research_learning_cycle", "owner_id", "cycle_id"),
        CheckConstraint(
            "status IN ('recorded', 'partial', 'insufficient_evidence')",
            name="ck_research_learning_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(120))
    cycle_id: Mapped[str] = mapped_column(String(160))
    topic: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(32))


class ResearchLearningSupportRow(Base):
    __tablename__ = "research_learning_support"
    __table_args__ = (
        ForeignKeyConstraint(
            ["learning_id", "owner_id"],
            ["research_learning_records.id", "research_learning_records.owner_id"],
            name="fk_rls_learning_owner",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "owner_id"],
            ["research_evidence.id", "research_evidence.owner_id"],
            name="fk_rls_evidence_owner",
        ),
        UniqueConstraint("owner_id", "learning_id", "ordinal", name="uq_rls_order"),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    learning_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class ResearchLearningConflictRow(Base):
    __tablename__ = "research_learning_conflicts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["learning_id", "owner_id"],
            ["research_learning_records.id", "research_learning_records.owner_id"],
            name="fk_rlc_learning_owner",
        ),
        ForeignKeyConstraint(
            ["evidence_id", "owner_id"],
            ["research_evidence.id", "research_evidence.owner_id"],
            name="fk_rlc_evidence_owner",
        ),
        UniqueConstraint("owner_id", "learning_id", "ordinal", name="uq_rlc_order"),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    learning_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class ResearchLearningClaimRow(Base):
    __tablename__ = "research_learning_claims"
    __table_args__ = (
        ForeignKeyConstraint(
            ["learning_id", "owner_id"],
            ["research_learning_records.id", "research_learning_records.owner_id"],
            name="fk_rll_claim_learning_owner",
        ),
        ForeignKeyConstraint(
            ["claim_id", "owner_id"],
            ["research_claims.id", "research_claims.owner_id"],
            name="fk_rll_claim_owner",
        ),
        UniqueConstraint("owner_id", "learning_id", "ordinal", name="uq_rll_claim_order"),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    learning_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)


class ResearchLearningGapRow(Base):
    __tablename__ = "research_learning_gaps"
    __table_args__ = (
        ForeignKeyConstraint(
            ["learning_id", "owner_id"],
            ["research_learning_records.id", "research_learning_records.owner_id"],
            name="fk_rll_gap_learning_owner",
        ),
        ForeignKeyConstraint(
            ["gap_id", "owner_id"],
            ["research_gaps.id", "research_gaps.owner_id"],
            name="fk_rll_gap_owner",
        ),
        UniqueConstraint("owner_id", "learning_id", "ordinal", name="uq_rll_gap_order"),
    )

    owner_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    learning_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    gap_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
