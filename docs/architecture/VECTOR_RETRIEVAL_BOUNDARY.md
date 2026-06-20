# Vector Retrieval Boundary

See [ADR-0022](decisions/ADR-0022-vector-retrieval-deferred.md). **Vector/embedding
retrieval is deferred and disabled by default.** Phase 3B proves deterministic lexical +
PostgreSQL full-text retrieval first.

## The interface (`memory/embeddings.py`)
- `EmbeddingProvider` (Protocol): `embed(items)`, `name`, `enabled`.
- `VectorSearchProvider` (Protocol): `search(vector, k)`, `name`, `enabled`.
- `EmbeddingRecord`: `chunk_id`, `vector`, `dim`, `provider`, `provider_version`.
- Defaults: `NullEmbeddingProvider` and `NullVectorSearchProvider` — `enabled = False`;
  their methods **raise** rather than silently no-op.

`get_embedding_provider(settings)` / `get_vector_search_provider(settings)` return the
null providers; `memory_embeddings_enabled` defaults to `False`.

## Guarantees in the default path
- No network embedding calls.
- No hidden model download.
- No external API key.
- No mandatory GPU or large local model.
- **No pgvector requirement** for standard tests or local development.
- Exact lexical / full-text retrieval is always preserved as the fallback.
- Approximate retrieval is **never** labelled as exact.

## If pgvector is added later
Enable via an explicit config flag; make extension creation idempotent; support tests
that skip cleanly when unavailable; document dimensionality and provider version; keep
lexical retrieval as the fallback. Optional vector search must never delay or gate the
core deterministic-memory release.
