"""Offline retrieval evaluation against the bundled gold dataset (no LLM evaluator)."""

from __future__ import annotations

import json

from orbitmind.api.container import AppContainer
from orbitmind.core.config import PROJECT_ROOT
from orbitmind.memory.evaluation import GoldItem


def _load_gold() -> list[GoldItem]:
    data = json.loads(
        (PROJECT_ROOT / "data" / "samples" / "memory" / "eval" / "gold.json").read_text(
            encoding="utf-8"
        )
    )
    return [GoldItem(**item) for item in data["items"]]


def test_gold_evaluation_meets_thresholds_and_is_reproducible(
    memory_corpus: AppContainer,
) -> None:
    report = memory_corpus.memory_service.evaluate(_load_gold(), k=5)
    assert report.queries == 5
    assert report.recall_at_k >= 0.8  # the glossary answers each query
    assert report.mean_reciprocal_rank > 0.0
    assert report.ndcg_at_k > 0.0
    assert report.zero_result_rate == 0.0
    assert report.citation_completeness == 1.0  # every result carries a complete citation
    assert report.reproducible  # identical orderings across two runs


def test_evaluation_reports_per_query_detail(memory_corpus: AppContainer) -> None:
    report = memory_corpus.memory_service.evaluate(_load_gold(), k=5)
    assert len(report.per_query) == 5
    assert all(
        pq.first_relevant_rank is None or pq.first_relevant_rank >= 1 for pq in report.per_query
    )
