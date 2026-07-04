# PostgreSQL Local Operations

PostgreSQL is **optional** locally — SQLite is the default for tests and basic
development (ADR-0023). Use this only to exercise PostgreSQL full-text retrieval.

## Start / stop the local profile
```bash
docker compose --profile postgres up -d postgres      # start PostgreSQL 16 (named volume, healthcheck)
docker compose --profile postgres ps         # check health
docker compose --profile postgres down       # stop (keeps the volume)
docker compose --profile postgres down -v    # stop and DELETE the data volume
```
Credentials come from environment variables (`POSTGRES_USER/PASSWORD/DB`); `.env.example`
holds safe, local-only placeholders. The service binds to `127.0.0.1:55432` only (host
port 55432 → container 5432, chosen so it cannot collide with any PostgreSQL already on
the host's 5432). No database starts automatically.

## Point the app at PostgreSQL
```bash
pip install -e .[postgres]   # psycopg driver (optional extra)
export ORBITMIND_DATABASE_URL="postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind"
alembic upgrade head         # applies migrations incl. the FTS GIN index
```

Alembic is the PostgreSQL schema authority. App startup does not bootstrap the
PostgreSQL schema with ORM metadata `create_all()`; run `alembic upgrade head`
before starting a PostgreSQL-backed app or validation run. ORM `create_all()`
remains a SQLite/local/offline test convenience only.

> **Windows:** use `127.0.0.1`, **not** `localhost`. `localhost` resolves to IPv6 `::1`
> first; the Docker port-forward is IPv4-only, so psycopg waits out a ~130s IPv6 timeout
> before falling back. `127.0.0.1` connects immediately.

## Verify full-text retrieval
After ingesting documents, the PostgreSQL `ix_document_chunks_fts` GIN index over
`to_tsvector('english', search_text)` is used for candidate selection; results are
labelled `backend = postgres-fts`. On SQLite the same query is labelled
`deterministic-lexical`.

## Integration tests
PostgreSQL integration tests are marked `postgres` and skip cleanly unless a disposable
PostgreSQL DB is configured. Ordinary unit tests never require Docker or PostgreSQL.
```bash
# Prepare a disposable test DB (host PG on 5432 is never touched):
docker exec <pg-container> psql -U orbitmind -d orbitmind -c "CREATE DATABASE orbitmind_test;"
URL=postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind_test
ORBITMIND_DATABASE_URL=$URL python -m alembic upgrade head
ORBITMIND_TEST_POSTGRES_URL=$URL python -m pytest -m postgres -v
```
In CI the `postgres-integration` job (`.github/workflows/ci.yml`) runs these against a
PostgreSQL 16 service container; the default offline job is unchanged.

Current test inventory after the read-product pause: `python -m pytest -m postgres
--collect-only -q` collects **117** postgres-marked tests. This is a collection
count only; a live PostgreSQL pass still requires `ORBITMIND_TEST_POSTGRES_URL`.

## Validation of record (2026-06-20)
Performed against a real local PostgreSQL via the Compose profile:

| Item | Result |
|------|--------|
| PostgreSQL version | **16.13** (Debian) |
| psycopg version | **3.3.4** |
| Migration to head (fresh DB, from zero) | ✅ `1673553df3f1`, 39 tables |
| FTS `tsvector` + GIN index `ix_document_chunks_fts` | ✅ present + valid |
| Query plan (`asteroid`) | Seq Scan by default (324 chunks — small data); **Bitmap Index Scan on the GIN index** when `enable_seqscan=off` (0.32 ms vs 33 ms) — index valid & usable |
| PostgreSQL integration tests (`-m postgres`) | ✅ 13 passed |
| Gold evaluation (PostgreSQL) | recall@5 = 1.0, MRR = 1.0, nDCG = 1.0, citation_completeness = 1.0, zero_result_rate = 0.0, reproducible = True |
| Backup/restore dev smoke (`pg_dump`/`pg_restore`) | ✅ counts + chunk checksum identical; restored DB serves `postgres-fts` retrieval |
| SQLite default suite | ✅ unchanged (190 passed, 13 postgres skipped) |

> If Docker is unavailable, continue on SQLite — the PostgreSQL paths are code-complete,
> dialect-aware, and migration-ready.
