# PostgreSQL Architecture

See [ADR-0018](decisions/ADR-0018-postgresql-production-system-of-record.md) and
[ADR-0023](decisions/ADR-0023-local-test-database-strategy.md).

## Roles
- **PostgreSQL** — production system-of-record (durable scientific memory + full-text
  retrieval).
- **SQLite** — default for fast, offline unit tests and basic local development.

Only `ORBITMIND_DATABASE_URL` changes between them; the domain layer is unchanged
because persistence goes through repository interfaces. Production behaviour must not
depend on SQLite-only features.

## Dialect-aware seams (the only places dialect matters)
- `Database.is_postgres` / `Database.dialect` expose the active dialect.
- Retrieval candidate selection: PostgreSQL FTS vs SQLite exact-term
  ([DETERMINISTIC_RETRIEVAL.md](DETERMINISTIC_RETRIEVAL.md)).
- The full-text **GIN index** `ix_document_chunks_fts` over
  `to_tsvector('english', search_text)` is created **PostgreSQL-conditionally** in the
  Phase 3B migration (`if op.get_bind().dialect.name == "postgresql"`).

## Searchable vs authoritative text
`document_chunks.original_text` preserves the authoritative text verbatim (Unicode,
units, punctuation, identifiers). `document_chunks.search_text` holds a separate
normalized representation used for lexical/FTS matching. The initial FTS language
assumption is **English** (`memory_fts_language`); it is configurable.

## Driver & profile
The `psycopg` driver is an optional extra (`pip install -e .[postgres]`). A local
PostgreSQL 16 profile is provided via Docker Compose
(`docker compose --profile postgres up -d`) with a persistent named volume and a health
check. Credentials come from environment variables; `.env.example` holds safe
placeholders. No database starts automatically; no cloud resource is created.

## Migrations & data safety
Additive, reversible Alembic migrations; **no destructive migration of user data** and
no automatic migration of an owner's production database without explicit approval. See
[../operations/DATABASE_MIGRATION_BACKUP.md](../operations/DATABASE_MIGRATION_BACKUP.md).

## Validated against real PostgreSQL (2026-06-20)
Exercised on PostgreSQL **16.13** (psycopg **3.3.4**): fresh-DB migration to head (39
tables), FTS GIN index verified by query-plan inspection, 13 live `postgres` integration
tests, gold evaluation recall@5 = 1.0, and a `pg_dump`/`pg_restore` smoke test. A real
FK-ordering defect (insert children before parents) that SQLite's FK-off default had
masked was found and fixed. The local Compose service publishes host port **55432**
(→ container 5432) to avoid colliding with any host PostgreSQL on 5432; on Windows connect
via `127.0.0.1` (not `localhost`). See
[../operations/POSTGRESQL_LOCAL_OPERATIONS.md](../operations/POSTGRESQL_LOCAL_OPERATIONS.md).
