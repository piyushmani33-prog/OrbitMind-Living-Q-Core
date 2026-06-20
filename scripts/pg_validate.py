"""Phase 3B PostgreSQL validation harness (not a product feature).

Ingests approved fixtures into the configured PostgreSQL database, runs the Phase 3B
validation queries, inspects the query plan for the FTS predicate, and runs the gold
evaluation. Run with ORBITMIND_DATABASE_URL pointing at a DISPOSABLE PostgreSQL DB.
"""

from __future__ import annotations

import json

from sqlalchemy import text

from orbitmind.api.container import AppContainer
from orbitmind.core.config import PROJECT_ROOT
from orbitmind.memory.evaluation import GoldItem
from orbitmind.memory.ingestion import IngestionRequest
from orbitmind.memory.repository import SqlAlchemyMemoryRepository  # noqa: F401
from orbitmind.memory.retrieval import MemorySearchRequest

_MEMORY_TABLES = (
    "evidence_links, citation_records, contradiction_records, scientific_claims, "
    "document_chunks, document_sections, document_versions, scientific_documents, "
    "memory_sources, concept_terms, concept_senses, concept_relationships, "
    "scientific_concepts, memory_graph_edges, ingestion_runs, retrieval_runs"
)

_QUERIES = [
    "OrbitMind first bounded mission",
    "why Qiskit is bounded",
    "why generated tools require approval",
    "why SGP4 is not used for asteroids",
    "CelesTrak two hour polling guidance",
    "close approach versus impact",
    "PostgreSQL versus pgvector strategy",
    "scientific verification requirements",
    "visual intelligence",
    "source rights requirements",
    "25544",
]


def main() -> None:
    container = AppContainer()
    assert container.database.is_postgres, "point ORBITMIND_DATABASE_URL at PostgreSQL"
    with container.database.engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {_MEMORY_TABLES} RESTART IDENTITY CASCADE"))

    svc = container.memory_service
    run, _ = svc.ingest(IngestionRequest(source_id="repo-docs", root="docs/architecture"))
    svc.ingest(IngestionRequest(source_id="samples", paths=["data/samples/memory/glossary.md"]))
    print(f"INGESTED: documents={run.documents} chunks={run.chunks} (+ glossary)")
    print("=" * 90)

    for q in _QUERIES:
        result = svc.search(MemorySearchRequest(query_text=q, limit=3))
        print(f"\nQUERY: {q!r}")
        print(
            f"  backend={result.backend.value}  results={result.returned}  "
            f"zero={result.zero_result}  total_candidates={result.total_candidates}"
        )
        for r in result.results[:1]:
            c = r.explanation.components
            print(f"  TOP: {r.title[:48]!r} / {r.section_path[:48]!r}")
            print(
                f"       score={r.rank_score} components(lex={c.lexical},title={c.title_boost},"
                f"sec={c.section_boost},id={c.identifier_boost})"
            )
            print(f"       matched={r.explanation.matched_terms[:6]}")
            cite = r.citation
            print(
                f"       citation: doc_v{cite.version_no} chunk={cite.chunk_id[-12:]} "
                f"checksum={cite.checksum[:12]} chars={cite.char_start}-{cite.char_end}"
            )

    # Query plan inspection (section 7).
    print("\n" + "=" * 90)
    print("QUERY PLAN (FTS predicate):")
    with container.database.engine.connect() as conn:
        default_plan = conn.execute(
            text(
                "EXPLAIN (ANALYZE, COSTS OFF) SELECT id FROM document_chunks "
                "WHERE to_tsvector('english', search_text) @@ plainto_tsquery('english','asteroid')"
            )
        ).all()
        print("  -- default planner --")
        for row in default_plan:
            print("   ", row[0])
        conn.execute(text("SET enable_seqscan = off"))
        forced_plan = conn.execute(
            text(
                "EXPLAIN (ANALYZE, COSTS OFF) SELECT id FROM document_chunks "
                "WHERE to_tsvector('english', search_text) @@ plainto_tsquery('english','asteroid')"
            )
        ).all()
        print("  -- enable_seqscan=off (proves GIN index is usable) --")
        for row in forced_plan:
            print("   ", row[0])

    # Gold evaluation (section 10).
    print("\n" + "=" * 90)
    gold_data = json.loads(
        (PROJECT_ROOT / "data" / "samples" / "memory" / "eval" / "gold.json").read_text("utf-8")
    )
    report = svc.evaluate([GoldItem(**i) for i in gold_data["items"]], k=5)
    print("GOLD EVALUATION (PostgreSQL):")
    print(
        f"  recall@5={report.recall_at_k}  MRR={report.mean_reciprocal_rank}  "
        f"nDCG={report.ndcg_at_k}"
    )
    print(
        f"  citation_completeness={report.citation_completeness}  "
        f"duplicate_rate={report.duplicate_rate}  zero_result_rate={report.zero_result_rate}  "
        f"reproducible={report.reproducible}"
    )


if __name__ == "__main__":
    main()
