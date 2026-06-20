# Ingesting Documents

Deterministic, allowlisted ingestion (`memory/ingestion.py`). **No execution of document
contents, no network.** See [ADR-0019](../architecture/decisions/ADR-0019-scientific-memory-model.md).

## Allowlist
Only files under approved roots are ingestible (`memory_ingestion_roots`):
- `docs/reference/extracted`
- `docs/architecture`
- `data/samples/memory`

## What is rejected (and tested)
- Paths outside the allowlist / path traversal (`../`, symlink escape).
- Secret-like names: `.env`, `*.pem`, `*.key`, and names containing `secret`, `token`,
  `credential`, `password`, `apikey`.
- Unsupported extensions (only `.md`, `.txt`).
- Files exceeding `memory_max_file_bytes` (default 2 MiB).
- Malformed (non-UTF-8) content.

## Behaviour
- Content checksum → **duplicate detection** (unchanged content is a no-op duplicate).
- Changed content → a new immutable `DocumentVersion`.
- Deterministic, structure-aware chunking (headings/paragraphs, char-accurate, stable
  ids from `version_id + ordinal`).
- Audit events for every step (`memory.ingestion_*`, `file_accepted/rejected`,
  `duplicate_detected`, `document_version_created`, `chunking_completed`).

## API
```bash
# Explicit allowlisted paths (relative to the project root):
curl -X POST localhost:8000/api/v1/memory/ingestion-runs \
  -H 'content-type: application/json' \
  -d '{"source_id":"repo-docs","paths":["docs/architecture/decisions/ADR-0005-quantum-boundary.md"]}'

# Or an approved root (bounded by max_files):
#   {"source_id":"repo-docs","root":"docs/architecture/decisions"}
```
The response reports per-file outcomes (`created`/`updated`/`duplicate`/`rejected`) and a
memory disclaimer (memory is not truth; retrieval is not verification).
