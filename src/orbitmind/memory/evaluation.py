"""Deterministic, offline retrieval evaluation against a curated gold dataset.

No LLM is used as the evaluator. Relevance is judged by content markers expected in a
relevant chunk.
"""

from __future__ import annotations

import math

from pydantic import BaseModel

from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.memory.retrieval import MemorySearchRequest, MemorySearchService


class GoldItem(BaseModel):
    query: str
    relevant_markers: list[str]
    distractors: list[str] = []


class PerQueryResult(BaseModel):
    query: str
    returned: int
    first_relevant_rank: int | None
    relevant_in_topk: bool


class EvaluationReport(BaseModel):
    k: int
    queries: int
    recall_at_k: float
    mean_reciprocal_rank: float
    ndcg_at_k: float
    citation_completeness: float
    duplicate_rate: float
    zero_result_rate: float
    reproducible: bool
    per_query: list[PerQueryResult]


class RetrievalEvaluator:
    """Evaluates the memory search service against a gold dataset."""

    def __init__(self, search: MemorySearchService) -> None:
        self._search = search

    def evaluate(
        self,
        gold: list[GoldItem],
        repo: SqlAlchemyMemoryRepository,
        *,
        k: int = 5,
        is_postgres: bool = False,
        language: str = "english",
    ) -> EvaluationReport:
        per_query: list[PerQueryResult] = []
        recall_hits = 0
        rr_sum = 0.0
        ndcg_sum = 0.0
        zero_results = 0
        total_results = 0
        unique_chunks = 0
        complete_citations = 0
        signature: list[tuple[str, ...]] = []

        for item in gold:
            request = MemorySearchRequest(query_text=item.query, limit=k)
            result = self._search.search(request, repo, is_postgres=is_postgres, language=language)
            signature.append(tuple(r.chunk_id for r in result.results))
            if result.zero_result:
                zero_results += 1
            total_results += result.returned
            chunk_ids = [r.chunk_id for r in result.results]
            unique_chunks += len(set(chunk_ids))
            complete_citations += sum(
                1 for r in result.results if r.citation.chunk_id and r.citation.checksum
            )

            first_rank: int | None = None
            for rank, r in enumerate(result.results, start=1):
                text = self._chunk_text(repo, r.chunk_id)
                haystack = f"{r.title}\n{r.section_path}\n{text}".lower()
                if any(m.lower() in haystack for m in item.relevant_markers):
                    first_rank = rank
                    break
            per_query.append(
                PerQueryResult(
                    query=item.query,
                    returned=result.returned,
                    first_relevant_rank=first_rank,
                    relevant_in_topk=first_rank is not None,
                )
            )
            if first_rank is not None:
                recall_hits += 1
                rr_sum += 1.0 / first_rank
                ndcg_sum += 1.0 / math.log2(first_rank + 1)  # binary relevance, ideal dcg = 1

        # Reproducibility: run once more and compare result orderings.
        repeat = [
            tuple(
                r.chunk_id
                for r in self._search.search(
                    MemorySearchRequest(query_text=g.query, limit=k),
                    repo,
                    is_postgres=is_postgres,
                    language=language,
                ).results
            )
            for g in gold
        ]
        n = max(len(gold), 1)
        return EvaluationReport(
            k=k,
            queries=len(gold),
            recall_at_k=round(recall_hits / n, 4),
            mean_reciprocal_rank=round(rr_sum / n, 4),
            ndcg_at_k=round(ndcg_sum / n, 4),
            citation_completeness=round(complete_citations / total_results, 4)
            if total_results
            else 1.0,
            duplicate_rate=round((total_results - unique_chunks) / total_results, 4)
            if total_results
            else 0.0,
            zero_result_rate=round(zero_results / n, 4),
            reproducible=signature == repeat,
            per_query=per_query,
        )

    @staticmethod
    def _chunk_text(repo: SqlAlchemyMemoryRepository, chunk_id: str) -> str:
        ctx = repo.get_chunk_context(chunk_id)
        return ctx.chunk.original_text if ctx is not None else ""
