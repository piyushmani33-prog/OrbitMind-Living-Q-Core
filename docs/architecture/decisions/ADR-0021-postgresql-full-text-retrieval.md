# ADR-0021 — Deterministic Retrieval (PostgreSQL Full-Text + SQLite Fallback)

- **Status:** Accepted (2026-06-20)

## Context
Retrieval must be deterministic, explainable, and reproducible, and must return
**ranked evidence passages — not a generated answer** (answer synthesis is deferred,
ADR-0022). It must work in offline SQLite tests and in production PostgreSQL.

## Decision
- **Candidate selection is dialect-aware; ranking is identical across dialects.**
  - On **PostgreSQL**, candidates are selected with native full-text search:
    `to_tsvector('english', search_text) @@ plainto_tsquery('english', :q)`, backed by a
    GIN index (created PostgreSQL-conditionally in the Phase 3B migration).
  - On **SQLite**, candidates are selected by exact-term matching over the same
    `search_text` (no `tsvector`); this is the deterministic lexical fallback.
- **One explicit ranking formula** (`memory/ranking.py`) is applied in Python to the
  candidate set on both dialects: a lexical score (distinct matched terms + a small
  term-frequency component) plus title, section, and identifier boosts. Each result
  records its `RankingComponents`, matched terms, and the `RetrievalBackend` used.
- **Honest about differences**: PostgreSQL FTS uses stemming, so its candidate *set*
  can differ from SQLite's exact-term set. The backend is labelled on every result;
  SQLite retrieval is **not** claimed to be identical to PostgreSQL ranking.
- Common stopwords are ignored in query scoring; queries are typed/validated
  (`MemorySearchRequest`) and never interpolated as raw SQL (parameters only).
- Zero-result and truncated states are explicit; retrieval runs are recorded for
  evaluation.

## Alternatives considered
1. **PostgreSQL `ts_rank` as the sole ranker.** Not reproducible on SQLite tests and
   harder to explain per-component. Rejected; FTS is used as a candidate filter while a
   transparent formula does the ranking.
2. **External search engine (Elasticsearch/OpenSearch).** Heavy operational footprint,
   network dependency, non-deterministic defaults. Rejected for this bounded phase.

## Consequences
- Fast offline tests and explainable, reproducible ranking; production gains indexed
  full-text candidate selection.
- A small dialect-aware seam must be maintained.

## Review trigger
Revisit if ranking quality needs `ts_rank`/BM25, or if corpus size outgrows the
in-process candidate cap.
