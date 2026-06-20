# Deterministic Retrieval

See [ADR-0021](decisions/ADR-0021-postgresql-full-text-retrieval.md). Retrieval returns
**ranked, citable evidence passages — not a generated answer** (answer synthesis is
deferred, [ADR-0022](decisions/ADR-0022-vector-retrieval-deferred.md)).

## Request (`MemorySearchRequest`)
Typed and validated: `query_text` (2–256 chars), `domains`, `source_ids`,
`document_types`, `concept_ids`, `epistemic_statuses`, `verification_statuses`,
`date_from`/`date_to`, `limit` (≤50), `offset`, `sort` (`relevance`|`recency`). Filter
lists are length-bounded. **No raw SQL, no PostgreSQL query syntax passthrough, no
arbitrary field selection** — the query is tokenized and passed only as bound
parameters.

## Pipeline
1. Tokenize the query; drop curated stopwords; optionally expand with concept/domain
   terms (a soft signal).
2. **Dialect-aware candidate selection:**
   - **PostgreSQL:** `to_tsvector('english', search_text) @@ plainto_tsquery('english', :q)`,
     backed by the `ix_document_chunks_fts` GIN index.
   - **SQLite:** exact-term matching over the same `search_text` (deterministic fallback).
3. **One explicit ranking formula** (`ranking.py`) scores candidates identically on both
   dialects:
   `total = lexical(distinct matched terms + 0.05·occurrences) + title_boost(0.5) +
   section_boost(0.3) + identifier_boost(0.5·matched identifiers)`.
4. Sort by `(score desc, document_id, ordinal)` (relevance) or document time (recency).

## Result (`RankedChunk`)
chunk/document/version ids, title, section path, `rank_score`, `RetrievalExplanation`
(matched terms, `RankingComponents`, `RetrievalBackend`, reason), source, rights note,
epistemic status (`assumption` — source text is a source assertion), verification status
(`not-verified`), excerpt, and a version-pinned `CitationRecord`. Zero-result and
truncated states are explicit.

## SQLite vs PostgreSQL — an honest difference
The **ranking formula is identical**; only candidate *selection* differs. PostgreSQL FTS
stems, so its candidate set can differ from SQLite's exact-term set. The backend is
labelled on every result; SQLite retrieval is **not** claimed identical to PostgreSQL
ranking. This is asserted in tests (`test_postgres_backend_uses_fts_filter_and_is_labelled`).
