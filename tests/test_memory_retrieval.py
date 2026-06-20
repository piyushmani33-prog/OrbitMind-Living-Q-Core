"""Deterministic retrieval: ranking, filters, citations, dialect labelling."""

from __future__ import annotations

import datetime as dt

from orbitmind.api.container import AppContainer
from orbitmind.core.timeutils import utcnow
from orbitmind.memory.models import RetrievalBackend
from orbitmind.memory.repository import ChunkContext
from orbitmind.memory.retrieval import MemorySearchRequest, MemorySearchService
from orbitmind.persistence.memory_models import DocumentChunkRow, ScientificDocumentRow


def test_search_returns_relevant_ranked_evidence_with_pinned_citation(
    memory_corpus: AppContainer,
) -> None:
    result = memory_corpus.memory_service.search(
        MemorySearchRequest(query_text="why is SGP4 not used for asteroids", limit=5)
    )
    assert not result.zero_result and result.returned >= 1
    assert result.backend is RetrievalBackend.DETERMINISTIC_LEXICAL
    top = result.results[0]
    # Evidence, not a verified answer.
    assert top.epistemic_status == "assumption"
    assert top.verification_status == "not-verified"
    # Citation is version-pinned to the exact stored chunk.
    cite = top.citation
    assert cite.chunk_id == top.chunk_id
    assert cite.version_id and cite.version_no >= 1 and cite.checksum
    assert cite.char_end > cite.char_start
    assert "sgp4" in [t.lower() for t in top.explanation.matched_terms] or top.rank_score > 0
    # Explanation records the ranking components + backend.
    assert top.explanation.components.total == top.rank_score
    assert top.explanation.backend is RetrievalBackend.DETERMINISTIC_LEXICAL


def test_search_is_deterministic(memory_corpus: AppContainer) -> None:
    req = MemorySearchRequest(query_text="close approach impact hazard", limit=5)
    a = memory_corpus.memory_service.search(req)
    b = memory_corpus.memory_service.search(req)
    assert [r.chunk_id for r in a.results] == [r.chunk_id for r in b.results]
    assert [r.rank_score for r in a.results] == [r.rank_score for r in b.results]


def test_identifier_query_matches_identifier_token(memory_corpus: AppContainer) -> None:
    result = memory_corpus.memory_service.search(MemorySearchRequest(query_text="25544", limit=5))
    assert any("25544" in r.explanation.matched_terms for r in result.results)


def test_zero_result_is_explicit(memory_corpus: AppContainer) -> None:
    result = memory_corpus.memory_service.search(
        MemorySearchRequest(query_text="zzzqwxnonexistenttoken", limit=5)
    )
    assert result.zero_result and result.returned == 0 and result.results == []


def test_document_type_filter(memory_corpus: AppContainer) -> None:
    result = memory_corpus.memory_service.search(
        MemorySearchRequest(query_text="heliocentric orbits", document_types=["fixture"], limit=10)
    )
    # The glossary (fixture) is included; ADRs (document_type 'adr') are excluded.
    assert result.returned >= 1
    assert all(r.document_type == "fixture" for r in result.results)


def test_truncation_flag(memory_corpus: AppContainer) -> None:
    result = memory_corpus.memory_service.search(MemorySearchRequest(query_text="orbit", limit=1))
    if result.total_candidates > 1:
        assert result.truncated and result.returned == 1


def test_epistemic_filter_excludes_when_status_absent(memory_corpus: AppContainer) -> None:
    # No chunk is a verified-fact, so filtering for it yields nothing.
    result = memory_corpus.memory_service.search(
        MemorySearchRequest(query_text="orbit", epistemic_statuses=["verified-fact"], limit=5)
    )
    assert result.zero_result


# --- dialect labelling (PostgreSQL path exercised with a stub repo) ---------
class _StubRepo:
    """Minimal repo stub to exercise the PostgreSQL FTS candidate path off-DB."""

    def __init__(self, contexts: list[ChunkContext], fts_ids: set[str]) -> None:
        self._contexts = contexts
        self._fts_ids = fts_ids
        self.fts_called_with: tuple[list[str], str, int] | None = None

    def get_concept(self, _cid: str):
        return None

    def list_concepts(self, _limit: int, _offset: int, _domain):
        return []

    def search_candidates(self, *, source_ids, document_types, cap):
        return list(self._contexts)

    def fts_candidate_ids(self, terms: list[str], language: str, cap: int) -> set[str]:
        self.fts_called_with = (terms, language, cap)
        return set(self._fts_ids)


def _ctx(chunk_id: str, text: str) -> ChunkContext:
    chunk = DocumentChunkRow(
        id=chunk_id,
        document_id="d1",
        version_id="v1",
        section_path="S",
        ordinal=0,
        char_start=0,
        char_end=len(text),
        original_text=text,
        search_text=text.lower(),
        checksum="abc",
        language="english",
        created_at=utcnow(),
    )
    doc = ScientificDocumentRow(
        id="d1",
        source_id="s",
        title="Doc",
        document_type="fixture",
        language="english",
        origin_label="data/samples/memory/x.md",
        rights={},
        tags=[],
        created_at=utcnow(),
    )
    return ChunkContext(chunk=chunk, document=doc, version_no=1)


def test_postgres_backend_uses_fts_filter_and_is_labelled() -> None:
    ctxs = [_ctx("c1", "SGP4 heliocentric asteroid"), _ctx("c2", "unrelated content")]
    stub = _StubRepo(ctxs, fts_ids={"c1"})
    service = MemorySearchService()
    result = service.search(
        MemorySearchRequest(query_text="heliocentric asteroid", limit=5),
        stub,  # type: ignore[arg-type]
        is_postgres=True,
        language="english",
    )
    assert stub.fts_called_with == (["asteroid", "heliocentric"], "english", 2000)
    assert result.backend is RetrievalBackend.POSTGRES_FTS
    # Only the FTS-selected candidate survives.
    assert [r.chunk_id for r in result.results] == ["c1"]


def test_embeddings_and_vector_search_disabled_by_default() -> None:
    import pytest

    from orbitmind.core.config import Settings
    from orbitmind.memory.embeddings import (
        get_embedding_provider,
        get_vector_search_provider,
    )

    settings = Settings(env="test")
    assert settings.memory_embeddings_enabled is False
    embed = get_embedding_provider(settings)
    vectors = get_vector_search_provider(settings)
    assert embed.enabled is False and vectors.enabled is False
    with pytest.raises(RuntimeError):
        embed.embed([("c1", "text")])
    with pytest.raises(RuntimeError):
        vectors.search((0.0, 1.0), 5)


def test_recency_sort_orders_by_document_time() -> None:
    older = _ctx("old", "orbit one")
    newer = _ctx("new", "orbit two")
    object.__setattr__(newer.document, "created_at", utcnow())
    object.__setattr__(older.document, "created_at", utcnow() - dt.timedelta(days=1))
    stub = _StubRepo([older, newer], fts_ids=set())
    service = MemorySearchService()
    result = service.search(
        MemorySearchRequest(query_text="orbit", sort="recency", limit=5),
        stub,  # type: ignore[arg-type]
        is_postgres=False,
        language="english",
    )
    assert [r.chunk_id for r in result.results] == ["new", "old"]
