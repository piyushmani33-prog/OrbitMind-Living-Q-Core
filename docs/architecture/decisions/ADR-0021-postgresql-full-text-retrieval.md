# ADR-0021 — Deterministic Retrieval (PostgreSQL Full-Text + SQLite Fallback)

- **Status:** Accepted (2026-06-20)

## Context
Retrieval must be deterministic, explainable, and reproducible, and must return
**ranked evidence passages — not a generated answer** (answer synthesis is deferred,
ADR-0022). It must work in offline SQLite tests and in production PostgreSQL.

## Decision
- **Candidate selection is dialect-aware; ranking is identical across dialects.**
  - On **PostgreSQL**, candidates are selected with native full-text search using
    **OR (any-term) semantics**: the per-term tsqueries are OR'd —
    `to_tsvector('english', search_text) @@ (plainto_tsquery(:t0) || plainto_tsquery(:t1) || …)`
    — backed by a GIN index (created PostgreSQL-conditionally in the Phase 3B migration).
    Per-term OR is used deliberately: a single `plainto_tsquery(:q)` ANDs all terms and
    would zero-result queries that the lexical backend answers (validated 2026-06-20).
    Terms are bound parameters, never interpolated (injection-safe).
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

## Validation (2026-06-20)
Exercised against real PostgreSQL 16.13 (psycopg 3.3.4): the GIN FTS index exists and is
valid; `EXPLAIN` shows a Bitmap Index Scan on it when forced (seq scan only because the
fixture corpus is tiny); all 11 validation queries return `backend=postgres-fts`; gold
evaluation on PostgreSQL scores recall@5 = MRR = nDCG = 1.0 with full citation
completeness and reproducible orderings. See
[POSTGRESQL_LOCAL_OPERATIONS.md](../../operations/POSTGRESQL_LOCAL_OPERATIONS.md).

## Review trigger
Revisit if ranking quality needs `ts_rank`/BM25, or if corpus size outgrows the
in-process candidate cap.
