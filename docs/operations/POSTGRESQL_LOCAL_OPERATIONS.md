# PostgreSQL Local Operations

PostgreSQL is **optional** locally — SQLite is the default for tests and basic
development (ADR-0023). Use this only to exercise PostgreSQL full-text retrieval.

## Start / stop the local profile
```bash
docker compose --profile postgres up -d      # start PostgreSQL 16 (named volume, healthcheck)
docker compose --profile postgres ps         # check health
docker compose --profile postgres down       # stop (keeps the volume)
docker compose --profile postgres down -v    # stop and DELETE the data volume
```
Credentials come from environment variables (`POSTGRES_USER/PASSWORD/DB`); `.env.example`
holds safe, local-only placeholders. The service binds to `127.0.0.1:5432` only and no
database starts automatically.

## Point the app at PostgreSQL
```bash
pip install -e .[postgres]   # psycopg driver (optional extra)
export ORBITMIND_DATABASE_URL="postgresql+psycopg://orbitmind:orbitmind@localhost:5432/orbitmind"
alembic upgrade head         # applies migrations incl. the FTS GIN index
```

## Verify full-text retrieval
After ingesting documents, the PostgreSQL `ix_document_chunks_fts` GIN index over
`to_tsvector('english', search_text)` is used for candidate selection; results are
labelled `backend = postgres-fts`. On SQLite the same query is labelled
`deterministic-lexical`.

## Integration tests
PostgreSQL integration tests run when a PostgreSQL service is configured and skip (not
fail) otherwise. Ordinary unit tests never require Docker or PostgreSQL.

> If Docker is unavailable, continue on SQLite — the PostgreSQL paths are code-complete,
> dialect-aware, and migration-ready.
