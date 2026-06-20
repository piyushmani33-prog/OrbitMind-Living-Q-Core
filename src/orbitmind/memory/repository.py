"""SQLAlchemy repository for scientific memory (persistence boundary)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.memory.models import (
    ClaimObject,
    ClaimPredicate,
    ClaimStatus,
    ClaimSubject,
    ConceptDomain,
    ConceptKind,
    ConceptRelationship,
    ConceptSense,
    ConceptTerm,
    ContradictionRecord,
    DocumentChunk,
    DocumentMetadata,
    DocumentSection,
    DocumentType,
    DocumentVersion,
    EvidenceLink,
    EvidenceSupportType,
    GraphEdge,
    IngestionRun,
    MemorySource,
    QuoteSpan,
    RetrievalResult,
    ScientificClaim,
    ScientificConcept,
    ScientificDocument,
)
from orbitmind.memory.normalization import search_normalize
from orbitmind.persistence.memory_models import (
    ConceptRelationshipRow,
    ConceptSenseRow,
    ConceptTermRow,
    ContradictionRecordRow,
    DocumentChunkRow,
    DocumentSectionRow,
    DocumentVersionRow,
    EvidenceLinkRow,
    IngestionRunRow,
    MemoryGraphEdgeRow,
    MemorySourceRow,
    RetrievalRunRow,
    ScientificClaimRow,
    ScientificConceptRow,
    ScientificDocumentRow,
)


@dataclass(frozen=True)
class ChunkContext:
    """A chunk joined with its document/version metadata (for retrieval + citation)."""

    chunk: DocumentChunkRow
    document: ScientificDocumentRow
    version_no: int


class SqlAlchemyMemoryRepository:
    """Persistence + reads for documents, concepts, claims, evidence, graph."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def flush(self) -> None:
        """Flush pending inserts so FK parents exist before children (PostgreSQL)."""
        self._s.flush()

    # ---- sources / documents / versions / chunks --------------------------
    def upsert_source(self, source: MemorySource) -> None:
        row = (
            self._s.execute(
                select(MemorySourceRow).where(MemorySourceRow.source_id == source.source_id)
            )
            .scalars()
            .first()
        )
        if row is None:
            self._s.add(
                MemorySourceRow(
                    id=source.id,
                    source_id=source.source_id,
                    name=source.name,
                    kind=source.kind,
                    rights=source.rights.model_dump(mode="json"),
                    created_at=utcnow(),
                )
            )

    def find_document(self, source_id: str, origin_label: str) -> ScientificDocumentRow | None:
        return (
            self._s.execute(
                select(ScientificDocumentRow).where(
                    ScientificDocumentRow.source_id == source_id,
                    ScientificDocumentRow.origin_label == origin_label,
                )
            )
            .scalars()
            .first()
        )

    def add_document(self, document: ScientificDocument) -> None:
        self._s.add(
            ScientificDocumentRow(
                id=document.id,
                source_id=document.source_id,
                title=document.metadata.title,
                document_type=document.metadata.document_type.value,
                language=document.metadata.language,
                origin_label=document.metadata.origin_label,
                rights=document.rights.model_dump(mode="json"),
                tags=list(document.metadata.tags),
                created_at=document.created_at,
            )
        )

    def latest_version(self, document_id: str) -> DocumentVersionRow | None:
        return (
            self._s.execute(
                select(DocumentVersionRow)
                .where(DocumentVersionRow.document_id == document_id)
                .order_by(DocumentVersionRow.version_no.desc())
            )
            .scalars()
            .first()
        )

    def add_version(self, version: DocumentVersion) -> None:
        self._s.add(
            DocumentVersionRow(
                id=version.id,
                document_id=version.document_id,
                version_no=version.version_no,
                content_checksum=version.content_checksum,
                normalized_checksum=version.normalized_checksum,
                original_length=version.original_length,
                created_at=version.created_at,
            )
        )

    def add_sections(self, version_id: str, sections: list[DocumentSection]) -> None:
        for sec in sections:
            self._s.add(
                DocumentSectionRow(
                    id=new_id(),
                    version_id=version_id,
                    section_path=sec.section_path,
                    ordinal=sec.ordinal,
                    title=sec.title,
                )
            )

    def add_chunks(self, chunks: list[DocumentChunk]) -> None:
        for c in chunks:
            self._s.add(
                DocumentChunkRow(
                    id=c.id,
                    document_id=c.document_id,
                    version_id=c.version_id,
                    section_path=c.section_path,
                    ordinal=c.ordinal,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    original_text=c.original_text,
                    search_text=c.search_text,
                    checksum=c.checksum,
                    language=c.language,
                    created_at=c.created_at,
                )
            )

    def add_ingestion_run(self, run: IngestionRun) -> None:
        self._s.add(
            IngestionRunRow(
                id=run.id,
                status=run.status.value,
                roots=list(run.roots),
                requested=run.requested,
                accepted=run.accepted,
                rejected=run.rejected,
                duplicates=run.duplicates,
                documents=run.documents,
                versions=run.versions,
                chunks=run.chunks,
                errors=list(run.errors),
                started_at=run.started_at,
                finished_at=run.finished_at,
            )
        )

    def get_ingestion_run(self, run_id: str) -> IngestionRunRow | None:
        return self._s.get(IngestionRunRow, run_id)

    def list_documents(self, limit: int, offset: int) -> list[ScientificDocument]:
        stmt = (
            select(ScientificDocumentRow)
            .order_by(ScientificDocumentRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [_to_document(r) for r in self._s.execute(stmt).scalars().all()]

    def count_documents(self) -> int:
        return int(
            self._s.execute(select(func.count()).select_from(ScientificDocumentRow)).scalar_one()
        )

    def get_document(self, document_id: str) -> ScientificDocument | None:
        row = self._s.get(ScientificDocumentRow, document_id)
        return _to_document(row) if row is not None else None

    def get_chunks(self, document_id: str) -> list[DocumentChunk]:
        version = self.latest_version(document_id)
        if version is None:
            return []
        stmt = (
            select(DocumentChunkRow)
            .where(DocumentChunkRow.version_id == version.id)
            .order_by(DocumentChunkRow.ordinal)
        )
        return [_to_chunk(r) for r in self._s.execute(stmt).scalars().all()]

    def chunk_exists(self, chunk_id: str) -> bool:
        return self._s.get(DocumentChunkRow, chunk_id) is not None

    def get_chunk_context(self, chunk_id: str) -> ChunkContext | None:
        chunk = self._s.get(DocumentChunkRow, chunk_id)
        if chunk is None:
            return None
        document = self._s.get(ScientificDocumentRow, chunk.document_id)
        version = self._s.get(DocumentVersionRow, chunk.version_id)
        if document is None or version is None:
            return None
        return ChunkContext(chunk=chunk, document=document, version_no=version.version_no)

    # ---- retrieval candidates ---------------------------------------------
    def search_candidates(
        self,
        *,
        source_ids: list[str] | None,
        document_types: list[str] | None,
        cap: int,
    ) -> list[ChunkContext]:
        """Metadata-filtered chunk candidates (dialect-agnostic; ranked in Python)."""
        stmt = (
            select(DocumentChunkRow, ScientificDocumentRow, DocumentVersionRow)
            .join(ScientificDocumentRow, DocumentChunkRow.document_id == ScientificDocumentRow.id)
            .join(DocumentVersionRow, DocumentChunkRow.version_id == DocumentVersionRow.id)
        )
        if source_ids:
            stmt = stmt.where(ScientificDocumentRow.source_id.in_(source_ids))
        if document_types:
            stmt = stmt.where(ScientificDocumentRow.document_type.in_(document_types))
        stmt = stmt.order_by(DocumentChunkRow.document_id, DocumentChunkRow.ordinal).limit(cap)
        return [
            ChunkContext(chunk=c, document=d, version_no=v.version_no)
            for c, d, v in self._s.execute(stmt).all()
        ]

    def fts_candidate_ids(self, terms: list[str], language: str, cap: int) -> set[str]:
        """PostgreSQL FTS candidate chunk ids (only used on the postgresql dialect).

        Uses OR semantics across terms (per-term ``plainto_tsquery`` OR'd) so the
        candidate *set* matches the deterministic lexical backend's any-term matching;
        the only intended difference from SQLite is PostgreSQL stemming. Terms are bound
        parameters, never interpolated, so this is injection-safe.
        """
        from sqlalchemy import text

        if not terms:
            return set()
        params: dict[str, object] = {"lang": language, "cap": cap}
        clauses: list[str] = []
        for i, term in enumerate(terms):
            params[f"t{i}"] = term
            clauses.append(f"plainto_tsquery(:lang, :t{i})")
        tsquery = " || ".join(clauses)  # '||' ORs tsqueries
        sql = text(
            "SELECT id FROM document_chunks "
            f"WHERE to_tsvector(:lang, search_text) @@ ({tsquery}) LIMIT :cap"
        )
        rows = self._s.execute(sql, params).all()
        return {r[0] for r in rows}

    def add_retrieval_run(
        self, result: RetrievalResult, latency_ms: float, query_checksum: str
    ) -> None:
        self._s.add(
            RetrievalRunRow(
                id=new_id(),
                query_checksum=query_checksum,
                backend=result.backend.value,
                returned=result.returned,
                total_candidates=result.total_candidates,
                zero_result=result.zero_result,
                latency_ms=latency_ms,
                created_at=utcnow(),
            )
        )

    # ---- concepts ----------------------------------------------------------
    def add_concept(self, concept: ScientificConcept) -> None:
        self._s.add(
            ScientificConceptRow(
                id=concept.id,
                canonical_name=concept.canonical_name,
                domain=concept.domain.value,
                kind=concept.kind.value,
                definition=concept.definition,
                source=concept.source,
                language=concept.language,
                parent_concept_id=concept.parent_concept_id,
            )
        )
        self._s.flush()  # concept row must exist before its FK terms/senses
        for term in concept.terms:
            self._s.add(
                ConceptTermRow(
                    id=term.id,
                    concept_id=concept.id,
                    term=term.term,
                    normalized_term=search_normalize(term.term),
                    language=term.language,
                    is_canonical=term.is_canonical,
                )
            )
        for sense in concept.senses:
            self._s.add(
                ConceptSenseRow(
                    id=sense.id,
                    concept_id=concept.id,
                    gloss=sense.gloss,
                    sense_rank=sense.sense_rank,
                )
            )

    def add_concept_relationship(self, rel: ConceptRelationship) -> None:
        self._s.add(
            ConceptRelationshipRow(
                id=rel.id,
                from_concept_id=rel.from_concept_id,
                to_concept_id=rel.to_concept_id,
                relation=rel.relation,
                provenance=rel.provenance,
            )
        )

    def list_concepts(self, limit: int, offset: int, domain: str | None) -> list[ScientificConcept]:
        stmt = select(ScientificConceptRow).order_by(ScientificConceptRow.canonical_name)
        if domain:
            stmt = stmt.where(ScientificConceptRow.domain == domain)
        stmt = stmt.limit(limit).offset(offset)
        return [self._to_concept(r) for r in self._s.execute(stmt).scalars().all()]

    def get_concept(self, concept_id: str) -> ScientificConcept | None:
        row = self._s.get(ScientificConceptRow, concept_id)
        return self._to_concept(row) if row is not None else None

    def find_concept_ids_by_term(self, normalized_term: str) -> set[str]:
        rows = (
            self._s.execute(
                select(ConceptTermRow.concept_id).where(
                    ConceptTermRow.normalized_term == normalized_term
                )
            )
            .scalars()
            .all()
        )
        return set(rows)

    def _to_concept(self, row: ScientificConceptRow) -> ScientificConcept:
        terms = (
            self._s.execute(select(ConceptTermRow).where(ConceptTermRow.concept_id == row.id))
            .scalars()
            .all()
        )
        senses = (
            self._s.execute(select(ConceptSenseRow).where(ConceptSenseRow.concept_id == row.id))
            .scalars()
            .all()
        )
        return ScientificConcept(
            id=row.id,
            canonical_name=row.canonical_name,
            domain=ConceptDomain(row.domain),
            kind=ConceptKind(row.kind),
            definition=row.definition,
            source=row.source,
            language=row.language,
            parent_concept_id=row.parent_concept_id,
            terms=[
                ConceptTerm(id=t.id, term=t.term, language=t.language, is_canonical=t.is_canonical)
                for t in terms
            ],
            senses=[ConceptSense(id=s.id, gloss=s.gloss, sense_rank=s.sense_rank) for s in senses],
        )

    # ---- claims / evidence -------------------------------------------------
    def add_claim(self, claim: ScientificClaim) -> None:
        self._s.add(
            ScientificClaimRow(
                id=claim.id,
                subject=claim.subject.value,
                subject_concept_id=claim.subject.concept_id,
                predicate=claim.predicate.value,
                object_value=claim.object.value,
                object_units=claim.object.units,
                object_concept_id=claim.object.concept_id,
                status=claim.status.value,
                epistemic_status=claim.epistemic_status.value,
                document_id=claim.document_id,
                version_id=claim.version_id,
                chunk_id=claim.chunk_id,
                quote_start=claim.quote_span.char_start if claim.quote_span else None,
                quote_end=claim.quote_span.char_end if claim.quote_span else None,
                quote=claim.quote_span.quote if claim.quote_span else None,
                extractor_version=claim.extractor_version,
                verification_status=claim.verification_status,
                limitations=claim.limitations,
                created_at=claim.created_at,
            )
        )

    def claim_exists(self, claim_id: str) -> bool:
        return self._s.get(ScientificClaimRow, claim_id) is not None

    def get_claim(self, claim_id: str) -> ScientificClaim | None:
        row = self._s.get(ScientificClaimRow, claim_id)
        return _to_claim(row) if row is not None else None

    def list_claims(self, limit: int, offset: int, status: str | None) -> list[ScientificClaim]:
        stmt = select(ScientificClaimRow).order_by(ScientificClaimRow.created_at.desc())
        if status:
            stmt = stmt.where(ScientificClaimRow.status == status)
        stmt = stmt.limit(limit).offset(offset)
        return [_to_claim(r) for r in self._s.execute(stmt).scalars().all()]

    def add_evidence(self, link: EvidenceLink) -> None:
        self._s.add(
            EvidenceLinkRow(
                id=link.id,
                claim_id=link.claim_id,
                chunk_id=link.chunk_id,
                record_ref=link.record_ref,
                support_type=link.support_type.value,
                source=link.source,
                explanation=link.explanation,
                registrar_version=link.registrar_version,
                verification_state=link.verification_state,
                created_at=link.created_at,
            )
        )

    def get_evidence_for_claim(self, claim_id: str) -> list[EvidenceLink]:
        rows = (
            self._s.execute(select(EvidenceLinkRow).where(EvidenceLinkRow.claim_id == claim_id))
            .scalars()
            .all()
        )
        return [
            EvidenceLink(
                id=r.id,
                claim_id=r.claim_id,
                chunk_id=r.chunk_id,
                record_ref=r.record_ref,
                support_type=EvidenceSupportType(r.support_type),
                source=r.source,
                explanation=r.explanation,
                registrar_version=r.registrar_version,
                verification_state=r.verification_state,
                created_at=r.created_at,
            )
            for r in rows
        ]

    def add_contradiction(self, record: ContradictionRecord) -> None:
        self._s.add(
            ContradictionRecordRow(
                id=record.id,
                claim_id=record.claim_id,
                contradicting_claim_id=record.contradicting_claim_id,
                explanation=record.explanation,
                created_at=record.created_at,
            )
        )

    # ---- graph -------------------------------------------------------------
    def add_graph_edge(self, edge: GraphEdge) -> None:
        self._s.add(
            MemoryGraphEdgeRow(
                id=edge.id,
                from_kind=edge.from_ref.kind.value,
                from_id=edge.from_ref.entity_id,
                edge_kind=edge.edge_kind.value,
                to_kind=edge.to_ref.kind.value,
                to_id=edge.to_ref.entity_id,
                source=edge.source,
                weight=edge.weight,
                created_at=edge.created_at,
            )
        )

    def edges_from(self, entity_id: str, limit: int) -> list[MemoryGraphEdgeRow]:
        return list(
            self._s.execute(
                select(MemoryGraphEdgeRow)
                .where(MemoryGraphEdgeRow.from_id == entity_id)
                .limit(limit)
            )
            .scalars()
            .all()
        )

    def edges_to(self, entity_id: str, limit: int) -> list[MemoryGraphEdgeRow]:
        return list(
            self._s.execute(
                select(MemoryGraphEdgeRow).where(MemoryGraphEdgeRow.to_id == entity_id).limit(limit)
            )
            .scalars()
            .all()
        )


def _to_document(row: ScientificDocumentRow) -> ScientificDocument:
    rights_data = row.rights or {}
    from orbitmind.memory.models import DocumentRights

    return ScientificDocument(
        id=row.id,
        source_id=row.source_id,
        metadata=DocumentMetadata(
            title=row.title,
            document_type=DocumentType(row.document_type),
            language=row.language,
            origin_label=row.origin_label,
            tags=list(row.tags or []),
        ),
        rights=DocumentRights(**rights_data) if rights_data else DocumentRights(),
        created_at=row.created_at,
    )


def _to_chunk(row: DocumentChunkRow) -> DocumentChunk:
    return DocumentChunk(
        id=row.id,
        document_id=row.document_id,
        version_id=row.version_id,
        section_path=row.section_path,
        ordinal=row.ordinal,
        char_start=row.char_start,
        char_end=row.char_end,
        original_text=row.original_text,
        search_text=row.search_text,
        checksum=row.checksum,
        language=row.language,
        created_at=row.created_at,
    )


def _to_claim(row: ScientificClaimRow) -> ScientificClaim:
    quote = (
        QuoteSpan(char_start=row.quote_start, char_end=row.quote_end, quote=row.quote or "")
        if row.quote_start is not None and row.quote_end is not None
        else None
    )
    return ScientificClaim(
        id=row.id,
        subject=ClaimSubject(value=row.subject, concept_id=row.subject_concept_id),
        predicate=ClaimPredicate(value=row.predicate),
        object=ClaimObject(
            value=row.object_value, units=row.object_units, concept_id=row.object_concept_id
        ),
        status=ClaimStatus(row.status),
        epistemic_status=EpistemicStatus(row.epistemic_status),
        document_id=row.document_id,
        version_id=row.version_id,
        chunk_id=row.chunk_id,
        quote_span=quote,
        extractor_version=row.extractor_version,
        verification_status=row.verification_status,
        limitations=row.limitations,
        created_at=row.created_at,
    )
