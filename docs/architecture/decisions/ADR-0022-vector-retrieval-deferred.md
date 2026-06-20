# ADR-0022 — Vector/Embedding Retrieval Deferred (Optional, Disabled by Default)

- **Status:** Accepted (2026-06-20)

## Context
Semantic (vector) retrieval via embeddings + `pgvector` is attractive but introduces a
model dependency, potential network/model downloads, and non-determinism that would
make default tests and local development fragile. Phase 3B must first prove a
deterministic, offline retrieval baseline.

## Decision
- **Design an embedding interface; do not require it.** Embeddings and vector storage
  are **optional and disabled by default** (`memory_embeddings_enabled = false`; a null
  embedding provider). Default operation requires **no embeddings and no external
  model**.
- **Prove deterministic PostgreSQL full-text retrieval first** (ADR-0021). Vector
  retrieval (`pgvector`) may be added **only if** it can be introduced without making
  default tests or local development fragile (no mandatory model download, no network,
  no non-determinism in the default path).
- **No hidden model downloads, no external API keys, no network** in the default path.

## Alternatives considered
1. **Require pgvector + embeddings now.** Adds a model/network dependency and
   non-deterministic ranking to the default path. Rejected for this phase.
2. **Forbid embeddings entirely.** Forecloses a useful future capability. Rejected;
   instead we leave a clean, optional interface.

## Consequences
- Default retrieval stays deterministic, offline, and reproducible.
- A future ADR can enable vector retrieval behind the existing optional boundary.

## Review trigger
Revisit when there is a concrete, offline-friendly embedding provider and a measured
retrieval-quality gap that lexical+FTS cannot close.
