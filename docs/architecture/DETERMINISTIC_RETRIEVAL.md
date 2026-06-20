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
2. **Dialect-aware candidate selection (OR semantics on both):**
   - **PostgreSQL:** the per-term tsqueries are OR'd —
     `to_tsvector('english', search_text) @@ (plainto_tsquery(:t0) || plainto_tsquery(:t1) || …)`,
     backed by the `ix_document_chunks_fts` GIN index. (Per-term OR is used deliberately
     instead of a single `plainto_tsquery`, which would AND all terms and could
     zero-result a query that the lexical backend would answer.) Terms are bound
     parameters, never interpolated.
   - **SQLite:** exact-term (any-term) matching over the same `search_text`.
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
The **ranking formula is identical** and both backends use **OR (any-term) matching**, so
the candidate *sets* now align except for one intended difference: **PostgreSQL stems**
(e.g. "asteroids" matches "asteroid"), while the SQLite fallback matches exact terms. The
backend (`postgres-fts` vs `deterministic-lexical`) is labelled on every result; SQLite
retrieval is **not** claimed identical to PostgreSQL ranking. Asserted in
`test_postgres_backend_uses_fts_filter_and_is_labelled` (SQLite) and the live
`tests/integration/test_postgres_memory.py` suite.

## Query plan (validated 2026-06-20)
On the bundled corpus (~324 chunks) the planner chooses a **sequential scan** for the FTS
predicate because the table is tiny — this is correct cost-based behaviour, not a missing
index. Forcing `enable_seqscan=off` produces a **Bitmap Index Scan on
`ix_document_chunks_fts`** (~0.3 ms vs ~33 ms), confirming the GIN index is valid and
used once the table is large enough to warrant it.
