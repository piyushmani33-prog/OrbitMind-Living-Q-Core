# Memory Backup & Recovery

Scientific memory (documents, versions, chunks, concepts, claims, evidence, citations,
graph edges, run records) lives in the production PostgreSQL database. Full migration
mechanics are in
[DATABASE_MIGRATION_BACKUP.md](DATABASE_MIGRATION_BACKUP.md); this page covers the
memory-specific recovery posture.

## What to back up
- The PostgreSQL database (all `memory_*`, `scientific_*`, `document_*`, `concept_*`,
  `evidence_links`, `citation_records`, `*_runs` tables).
- The cited **source documents** remain in the repository under the allowlisted roots;
  citations are version-pinned by checksum, so a restored database + the repo at the
  matching commit reproduces every citation exactly.

## What NOT to back up / commit
Database volumes (`pgdata/`), dumps (`*.dump`, `*.sql.gz`), `.env`, generated databases,
cache, ingestion output, and embeddings — all git-ignored.

## Backup
```bash
pg_dump --format=custom --dbname="$ORBITMIND_DATABASE_URL" --file orbitmind-memory.dump
```

## Restore
```bash
pg_restore --clean --if-exists --dbname="$ORBITMIND_DATABASE_URL" orbitmind-memory.dump
alembic current   # confirm the schema revision matches the dump
```

## Recovery integrity
After restore, run the offline retrieval evaluation
([RETRIEVAL_EVALUATION.md](RETRIEVAL_EVALUATION.md)) against the bundled gold dataset to
confirm retrieval is healthy and reproducible. Because citations carry the chunk
checksum and version, any drift between the restored database and the source documents is
detectable rather than silent.

## Migrations are non-destructive
Phase 3B migrations are additive and reversible; an owner's production database is never
migrated automatically without explicit approval (ADR-0018).
