"""Deterministic memory retrieval (PostgreSQL FTS primary; SQLite lexical fallback).

Returns ranked, citable evidence passages — NEVER a generated answer. The ranking
formula is identical across dialects; only candidate selection differs (PostgreSQL
uses stemmed FTS, SQLite uses exact-term matching), which is recorded on each result.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field, model_validator

from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.memory.citations import build_citation
from orbitmind.memory.models import (
    DocumentType,
    RankedChunk,
    RankingComponents,
    RetrievalBackend,
    RetrievalResult,
)
from orbitmind.memory.normalization import tokenize
from orbitmind.memory.ranking import score
from orbitmind.memory.repository import ChunkContext, SqlAlchemyMemoryRepository

_CANDIDATE_CAP = 2000
_CHUNK_EPISTEMIC = EpistemicStatus.ASSUMPTION.value  # retrieved text is a source assertion
_CHUNK_VERIFICATION = "not-verified"
_SORTS = frozenset({"relevance", "recency"})
# Common English stopwords ignored in query scoring (deterministic, curated).
_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "of",
        "for",
        "to",
        "in",
        "on",
        "at",
        "and",
        "or",
        "not",
        "no",
        "this",
        "that",
        "these",
        "those",
        "with",
        "as",
        "by",
        "it",
        "its",
        "from",
        "into",
        "than",
        "then",
        "why",
        "how",
        "what",
        "which",
        "who",
        "whom",
        "do",
        "does",
        "did",
        "has",
        "have",
        "had",
        "can",
        "could",
        "should",
        "would",
        "will",
    ]
)


def _query_terms(text: str) -> set[str]:
    terms = set(tokenize(text))
    meaningful = terms - _STOPWORDS
    return meaningful or terms


class MemorySearchRequest(BaseModel):
    """Typed, allowlisted memory search request (no raw SQL / query syntax)."""

    query_text: str = Field(min_length=2, max_length=256)
    domains: list[str] = Field(default_factory=list, max_length=12)
    source_ids: list[str] = Field(default_factory=list, max_length=20)
    document_types: list[str] = Field(default_factory=list, max_length=10)
    concept_ids: list[str] = Field(default_factory=list, max_length=20)
    epistemic_statuses: list[str] = Field(default_factory=list, max_length=10)
    verification_statuses: list[str] = Field(default_factory=list, max_length=10)
    date_from: dt.datetime | None = None
    date_to: dt.datetime | None = None
    limit: int = Field(default=10, ge=1, le=50)
    offset: int = Field(default=0, ge=0)
    sort: str = "relevance"

    @model_validator(mode="after")
    def _check(self) -> MemorySearchRequest:
        if self.sort not in _SORTS:
            raise ValueError(f"unsupported sort: {self.sort}")
        valid_types = {t.value for t in DocumentType}
        bad = [t for t in self.document_types if t not in valid_types]
        if bad:
            raise ValueError(f"unsupported document_types: {', '.join(bad)}")
        valid_epi = {e.value for e in EpistemicStatus}
        bad_epi = [e for e in self.epistemic_statuses if e not in valid_epi]
        if bad_epi:
            raise ValueError(f"unsupported epistemic_statuses: {', '.join(bad_epi)}")
        return self


class MemorySearchService:
    """Ranks evidence chunks for a query against scientific memory."""

    def search(
        self,
        request: MemorySearchRequest,
        repo: SqlAlchemyMemoryRepository,
        *,
        is_postgres: bool,
        language: str,
    ) -> RetrievalResult:
        query_terms = _query_terms(request.query_text)
        # Concept expansion (soft signal): add concept/domain terms to the query.
        for concept_id in request.concept_ids:
            concept = repo.get_concept(concept_id)
            if concept is not None:
                for term in concept.terms:
                    query_terms |= set(tokenize(term.term))
        for domain in request.domains:
            for concept in repo.list_concepts(100, 0, domain):
                query_terms |= set(tokenize(concept.canonical_name))

        candidates = repo.search_candidates(
            source_ids=request.source_ids or None,
            document_types=request.document_types or None,
            cap=_CANDIDATE_CAP,
        )

        backend = RetrievalBackend.DETERMINISTIC_LEXICAL
        if is_postgres and query_terms:
            fts_ids = repo.fts_candidate_ids(sorted(query_terms), language, _CANDIDATE_CAP)
            candidates = [c for c in candidates if c.chunk.id in fts_ids]
            backend = RetrievalBackend.POSTGRES_FTS

        if not self._passes_status_filters(request):
            return RetrievalResult(
                query_text=request.query_text,
                backend=backend,
                total_candidates=0,
                returned=0,
                truncated=False,
                zero_result=True,
                results=[],
            )

        scored: list[tuple[float, ChunkContext, RankedChunk]] = []
        for ctx in candidates:
            if not self._passes_date_filter(request, ctx):
                continue
            tokens = tokenize(ctx.chunk.search_text)
            title_tokens = set(tokenize(ctx.document.title))
            section_tokens = set(tokenize(ctx.chunk.section_path))
            components, matched = score(query_terms, tokens, title_tokens, section_tokens)
            if components.total <= 0.0:
                if backend is RetrievalBackend.POSTGRES_FTS:
                    components = components.model_copy(update={"total": 0.01})  # FTS-only match
                else:
                    continue
            ranked = self._ranked_chunk(ctx, components, matched, backend)
            scored.append((components.total, ctx, ranked))

        if request.sort == "recency":
            scored.sort(key=lambda x: (x[1].document.created_at, x[0]), reverse=True)
        else:
            scored.sort(key=lambda x: (-x[0], x[1].chunk.document_id, x[1].chunk.ordinal))

        total = len(scored)
        page = scored[request.offset : request.offset + request.limit]
        return RetrievalResult(
            query_text=request.query_text,
            backend=backend,
            total_candidates=total,
            returned=len(page),
            truncated=total > request.offset + request.limit,
            zero_result=len(page) == 0,
            results=[ranked for _score, _ctx, ranked in page],
        )

    @staticmethod
    def _passes_status_filters(request: MemorySearchRequest) -> bool:
        epistemic_ok = (
            not request.epistemic_statuses or _CHUNK_EPISTEMIC in request.epistemic_statuses
        )
        verification_ok = (
            not request.verification_statuses
            or _CHUNK_VERIFICATION in request.verification_statuses
        )
        return epistemic_ok and verification_ok

    @staticmethod
    def _passes_date_filter(request: MemorySearchRequest, ctx: ChunkContext) -> bool:
        created = ctx.document.created_at
        if request.date_from is not None and created < request.date_from:
            return False
        return not (request.date_to is not None and created > request.date_to)

    @staticmethod
    def _ranked_chunk(
        ctx: ChunkContext,
        components: RankingComponents,
        matched: list[str],
        backend: RetrievalBackend,
    ) -> RankedChunk:
        from orbitmind.memory.models import RetrievalExplanation

        excerpt = ctx.chunk.original_text.strip().replace("\n", " ")[:280]
        rights = ctx.document.rights or {}
        selector = "PostgreSQL full-text" if backend.value == "postgres-fts" else "exact-term"
        reason = f"matched {len(matched)} term(s); {selector} candidate"
        return RankedChunk(
            chunk_id=ctx.chunk.id,
            document_id=ctx.chunk.document_id,
            version_id=ctx.chunk.version_id,
            title=ctx.document.title,
            section_path=ctx.chunk.section_path,
            rank_score=components.total,
            explanation=RetrievalExplanation(
                matched_terms=matched, components=components, backend=backend, reason=reason
            ),
            source_id=ctx.document.source_id,
            document_type=ctx.document.document_type,
            rights_note=str(rights.get("license_note", "internal repository document")),
            epistemic_status=_CHUNK_EPISTEMIC,
            verification_status=_CHUNK_VERIFICATION,
            excerpt=excerpt,
            citation=build_citation(ctx),
        )
