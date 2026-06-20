# ADR-0019 — Scientific Memory Model (Documents, Versions, Chunks, Concepts)

- **Status:** Accepted (2026-06-20)

## Context
Durable scientific memory must store source documents with provenance, support
deterministic retrieval, and remain reproducible. It must NOT execute document
contents, ingest secrets, or treat stored text as truth.

## Decision
- **Layered entities** (`memory/models.py`), separate from ORM rows
  (`persistence/memory_models.py`) and API schemas (`api/memory_schemas.py`):
  `MemorySource → ScientificDocument → DocumentVersion → DocumentChunk`, plus
  `ScientificConcept`/`ConceptTerm`/`ConceptSense` for terminology.
- **Authoritative text is preserved verbatim** (only line-ending normalized). A
  separate `search_text` (lowercased, whitespace-collapsed, Unicode preserved) is used
  for lexical/full-text matching. Punctuation and units are never stripped from the
  authoritative text.
- **Deterministic, structure-aware chunking** (`memory/chunking.py`): Markdown
  heading/paragraph aware, char-range accurate, reproducible from
  `version_id + position`. Over-long segments are windowed with a controlled overlap.
- **Versioning + dedup**: re-ingesting unchanged content (by content checksum) is a
  no-op duplicate; changed content creates a new immutable version. Citations pin the
  exact version (ADR-0020).
- **Ingestion is allowlisted** to approved roots (`docs/reference/extracted`,
  `docs/architecture`, `data/samples/memory`); secret-like names and non-approved
  extensions/sizes are rejected. Contents are never executed; no network.

## Alternatives considered
1. **Store only normalized text.** Loses fidelity for scientific units/symbols and
   makes exact citation impossible. Rejected.
2. **Token-count chunking with an external tokenizer.** Adds a model dependency and
   non-determinism. Rejected in favour of deterministic char/section chunking.

## Consequences
- Reproducible chunk ids and citations; safe, bounded ingestion.
- Memory is evidence, not truth: a stored passage is a source assertion.

## Review trigger
Revisit when adding non-Markdown formats or a different chunking strategy.
