"""SQLAlchemy ORM models for scientific memory (Phase 3B).

Dialect-portable: ``document_chunks.search_text`` holds the normalized searchable text;
the PostgreSQL FTS GIN index over ``to_tsvector(...)`` is created conditionally in the
Alembic migration. Original text is preserved separately from search text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime


class MemorySourceRow(Base):
    __tablename__ = "memory_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    rights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ScientificDocumentRow(Base):
    __tablename__ = "scientific_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    document_type: Mapped[str] = mapped_column(String(32), index=True)
    language: Mapped[str] = mapped_column(String(16))
    origin_label: Mapped[str] = mapped_column(String(255))
    rights: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("scientific_documents.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    content_checksum: Mapped[str] = mapped_column(String(64), index=True)
    normalized_checksum: Mapped[str] = mapped_column(String(64))
    original_length: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DocumentSectionRow(Base):
    __tablename__ = "document_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    section_path: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)


class DocumentChunkRow(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("scientific_documents.id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("document_versions.id"), index=True)
    section_path: Mapped[str] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    original_text: Mapped[str] = mapped_column(Text)  # authoritative (not lowercased)
    search_text: Mapped[str] = mapped_column(Text)  # normalized for lexical/FTS matching
    checksum: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ScientificConceptRow(Base):
    __tablename__ = "scientific_concepts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128), index=True)
    domain: Mapped[str] = mapped_column(String(32), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    definition: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(64))
    language: Mapped[str] = mapped_column(String(16))
    parent_concept_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ConceptTermRow(Base):
    __tablename__ = "concept_terms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("scientific_concepts.id"), index=True)
    term: Mapped[str] = mapped_column(String(128), index=True)
    normalized_term: Mapped[str] = mapped_column(String(128), index=True)
    language: Mapped[str] = mapped_column(String(16))
    is_canonical: Mapped[bool] = mapped_column(Boolean, default=False)


class ConceptSenseRow(Base):
    __tablename__ = "concept_senses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(ForeignKey("scientific_concepts.id"), index=True)
    gloss: Mapped[str] = mapped_column(Text)
    sense_rank: Mapped[int] = mapped_column(Integer, default=1)


class ConceptRelationshipRow(Base):
    __tablename__ = "concept_relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    from_concept_id: Mapped[str] = mapped_column(String(36), index=True)
    to_concept_id: Mapped[str] = mapped_column(String(36), index=True)
    relation: Mapped[str] = mapped_column(String(32))
    provenance: Mapped[str] = mapped_column(String(64))


class ScientificClaimRow(Base):
    __tablename__ = "scientific_claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject: Mapped[str] = mapped_column(Text)
    subject_concept_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    predicate: Mapped[str] = mapped_column(Text)
    object_value: Mapped[str] = mapped_column(Text)
    object_units: Mapped[str | None] = mapped_column(String(32), nullable=True)
    object_concept_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    epistemic_status: Mapped[str] = mapped_column(String(32))
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quote_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    extractor_version: Mapped[str] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(24))
    limitations: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class EvidenceLinkRow(Base):
    __tablename__ = "evidence_links"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("scientific_claims.id"), index=True)
    chunk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    support_type: Mapped[str] = mapped_column(String(24))
    source: Mapped[str] = mapped_column(String(128))
    explanation: Mapped[str] = mapped_column(Text)
    registrar_version: Mapped[str] = mapped_column(String(32))
    verification_state: Mapped[str] = mapped_column(String(24))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class CitationRecordRow(Base):
    __tablename__ = "citation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    chunk_id: Mapped[str] = mapped_column(String(64), index=True)
    document_id: Mapped[str] = mapped_column(String(36), index=True)
    version_id: Mapped[str] = mapped_column(String(36))
    version_no: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    checksum: Mapped[str] = mapped_column(String(64))
    origin_label: Mapped[str] = mapped_column(String(255))
    rights_note: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ContradictionRecordRow(Base):
    __tablename__ = "contradiction_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(36), index=True)
    contradicting_claim_id: Mapped[str] = mapped_column(String(36), index=True)
    explanation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class IngestionRunRow(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    roots: Mapped[list[str]] = mapped_column(JSON, default=list)
    requested: Mapped[int] = mapped_column(Integer)
    accepted: Mapped[int] = mapped_column(Integer)
    rejected: Mapped[int] = mapped_column(Integer)
    duplicates: Mapped[int] = mapped_column(Integer)
    documents: Mapped[int] = mapped_column(Integer)
    versions: Mapped[int] = mapped_column(Integer)
    chunks: Mapped[int] = mapped_column(Integer)
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class RetrievalRunRow(Base):
    __tablename__ = "retrieval_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    query_checksum: Mapped[str] = mapped_column(String(64), index=True)
    backend: Mapped[str] = mapped_column(String(24))
    returned: Mapped[int] = mapped_column(Integer)
    total_candidates: Mapped[int] = mapped_column(Integer)
    zero_result: Mapped[bool] = mapped_column(Boolean)
    latency_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class MemoryGraphEdgeRow(Base):
    __tablename__ = "memory_graph_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    from_kind: Mapped[str] = mapped_column(String(32), index=True)
    from_id: Mapped[str] = mapped_column(String(64), index=True)
    edge_kind: Mapped[str] = mapped_column(String(32))
    to_kind: Mapped[str] = mapped_column(String(32))
    to_id: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(64))
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Benchmark that created this edge (fifth review, High #3). NULL for non-optimization edges.
    benchmark_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    __table_args__ = (Index("ix_memory_graph_edges_from", "from_kind", "from_id"),)
