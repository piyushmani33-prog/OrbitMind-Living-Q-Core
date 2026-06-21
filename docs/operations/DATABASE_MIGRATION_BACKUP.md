# Database: Migration & Backup (PostgreSQL / SQLite)

PostgreSQL is the production system-of-record; SQLite is the default for unit tests and
basic local development (see
[ADR-0018](../architecture/decisions/ADR-0018-postgresql-production-system-of-record.md),
[ADR-0023](../architecture/decisions/ADR-0023-local-test-database-strategy.md)).

## Local PostgreSQL (optional)
PostgreSQL is **not** required for tests or basic development. To exercise PostgreSQL
full-text retrieval locally:

```bash
docker compose --profile postgres up -d postgres          # start a local PostgreSQL 16
pip install -e .[postgres]                        # install the psycopg driver

# Local-only, throwaway credentials (never use in production, never commit real ones):
export ORBITMIND_DATABASE_URL="postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind"

alembic upgrade head                              # apply all migrations
```

The Phase 3B migration creates a PostgreSQL-only GIN full-text index over
`document_chunks.search_text` (`ix_document_chunks_fts`). On SQLite this index is
skipped and retrieval uses the deterministic lexical fallback.

> If Docker or PostgreSQL is unavailable, continue on SQLite. The PostgreSQL paths are
> code-complete and migration-ready; they are exercised in CI/integration when a
> PostgreSQL service is present and skipped (not failed) otherwise.

## Migrations
Migrations are additive and reversible — **no destructive migration of user data**.

```bash
alembic upgrade head        # apply
alembic downgrade -1        # revert the most recent migration
alembic current             # show the applied revision
alembic history             # show the chain
```

Migration chain: `b38aa92661c2` (Phase 1) → `080f934b44d1` (Phase 2) →
`233729f6fa57` (Phase 3A) → `1673553df3f1` (Phase 3B scientific memory).

When autogenerating a migration that uses timezone-aware columns, ensure the file
imports `orbitmind.persistence.database` (for the `UTCDateTime` type).

## Backup & restore (PostgreSQL)
```bash
# Backup (custom format; do NOT commit dumps — see .gitignore)
pg_dump --format=custom --dbname="$ORBITMIND_DATABASE_URL" --file orbitmind.dump

# Restore into a fresh database
pg_restore --clean --if-exists --dbname="$ORBITMIND_DATABASE_URL" orbitmind.dump
```

Dumps, the `pgdata/` volume, `.env`, generated databases, ingestion output, and
embeddings are all git-ignored and must never be committed.

## Switching SQLite ↔ PostgreSQL
Only `ORBITMIND_DATABASE_URL` changes; the domain layer is unchanged (repository
pattern). Re-run `alembic upgrade head` against the target database.
