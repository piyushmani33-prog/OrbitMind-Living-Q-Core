# Scientific Memory (Phase 3B)

Durable, queryable memory for scientific documents, concepts, claims, evidence,
citations, lightweight relations, and **deterministic retrieval**. Memory is evidence,
not truth; retrieval returns ranked, citable passages — **never a generated answer**
(answer synthesis is deferred, see [ADR-0022](decisions/ADR-0022-vector-retrieval-deferred.md)).

See ADRs [0018](decisions/ADR-0018-postgresql-production-system-of-record.md),
[0019](decisions/ADR-0019-scientific-memory-model.md),
[0020](decisions/ADR-0020-claims-evidence-citations.md),
[0021](decisions/ADR-0021-postgresql-full-text-retrieval.md),
[0022](decisions/ADR-0022-vector-retrieval-deferred.md),
[0023](decisions/ADR-0023-local-test-database-strategy.md).

## Module layout (`src/orbitmind/memory/`)
| File | Responsibility |
|------|----------------|
| `models.py` | Typed domain models (documents, chunks, concepts, claims, evidence, citations, retrieval, graph). |
| `normalization.py` | Deterministic line-ending normalization, search-text normalization, checksums, tokenization. Authoritative text preserved verbatim. |
| `chunking.py` | Structure-aware, char-accurate, reproducible Markdown chunking. |
| `ingestion.py` | Allowlisted, secret-rejecting, dedup + versioning ingestion (no execution, no network). |
| `ranking.py` | The single explicit ranking formula (lexical + title/section/identifier boosts). |
| `retrieval.py` | Typed search request + dialect-aware retrieval (PostgreSQL FTS / SQLite lexical). |
| `citations.py` | Version-pinned citation construction. |
| `concepts.py` / `claims.py` / `evidence.py` | Curated registration services with validation. |
| `graph.py` | Bounded, cycle-safe relational-graph traversal. |
| `evaluation.py` | Offline gold-dataset retrieval evaluation (no LLM evaluator). |
| `repository.py` | SQLAlchemy persistence boundary. |
| `service.py` | Facade: session management + audit around the modules. |

Dependency rule holds: `api → memory (domain) → persistence/sources → core`. The
memory module never imports `api`.

## Data model
`MemorySource → ScientificDocument → DocumentVersion → DocumentChunk`, with
`DocumentSection`s per version. Concepts: `ScientificConcept` + `ConceptTerm` +
`ConceptSense` + `ConceptRelationship`. Assertions: `ScientificClaim` (subject /
predicate / object + units, `ClaimStatus` **and** `EpistemicStatus`, provenance +
`QuoteSpan`), `EvidenceLink`, `ContradictionRecord`, `CitationRecord`. Relations:
`memory_graph_edges` with typed entity references. Run records: `ingestion_runs`,
`retrieval_runs`. ORM rows live in `persistence/memory_models.py`.

## Retrieval (deterministic, explainable)
1. The query is tokenized; stopwords are dropped; concept/domain terms optionally
   expand the query (a soft signal).
2. **Candidate selection is dialect-aware:** PostgreSQL uses
   `to_tsvector @@ plainto_tsquery` (GIN-indexed); SQLite uses exact-term matching over
   the same `search_text`.
3. **One ranking formula** scores candidates on both dialects and records
   `RankingComponents`, matched terms, and the `RetrievalBackend` per result.
4. Results carry version-pinned citations, an epistemic label (`assumption` — source
   text is a source assertion) and `not-verified` status. Zero-result and truncated
   states are explicit.

PostgreSQL FTS stems, so its candidate *set* can differ from SQLite's exact-term set;
the backend is labelled on every result and the difference is intentional and honest.

## Security & boundaries
- **Allowlisted ingestion** only: `docs/reference/extracted`, `docs/architecture`,
  `data/samples/memory`. Path-traversal, secret-like names (`.env`, `*.pem`, `*.key`,
  `*secret*`, `*token*`, `*credential*`), non-approved extensions, oversized and
  non-UTF-8 files are rejected.
- **Document contents are never executed.** No network, no model downloads, no API
  keys. Embeddings are disabled by default (null provider).
- Citations expose a safe relative `origin_label`, never a full local path.
- Every operation emits audit events (`memory.*` actions).

## What this phase does NOT do
No generative/conversational answer synthesis, no LLM, no mandatory `pgvector`, no
embeddings by default, no network. Retrieval output is evidence records and ranked
passages.
