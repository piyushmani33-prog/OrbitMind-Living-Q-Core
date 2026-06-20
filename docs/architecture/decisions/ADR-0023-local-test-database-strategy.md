# ADR-0023 — Local & Test Database Strategy

- **Status:** Accepted (2026-06-20)

## Context
PostgreSQL is the production system-of-record (ADR-0018), but the test suite must stay
**offline, deterministic, and fast**, and contributors must be able to develop without
running a database server.

## Decision
- **SQLite is the default for unit tests and basic local development.** Tests use temp
  dirs/DBs and fixed inputs; no network; no external services.
- **Retrieval is dialect-aware** (ADR-0021): SQLite uses the deterministic lexical
  fallback; PostgreSQL uses native full-text. Tests assert the SQLite behaviour by
  default and assert dialect *labelling* so the difference is explicit.
- **PostgreSQL is opt-in locally** via Docker Compose
  (`docker compose --profile postgres up -d`) with `ORBITMIND_DATABASE_URL` and the
  optional `psycopg` extra. PostgreSQL-specific behaviour (FTS index, `tsvector`
  selection) is **code-complete and migration-ready**, exercised by CI/integration when
  a PostgreSQL service is available, and skipped (not failed) when it is not.
- **If Docker/PostgreSQL is unavailable**, the limitation is documented and development
  continues on SQLite with dialect-aware code and mocked/CI-ready PostgreSQL config.

## Alternatives considered
1. **Require PostgreSQL for all tests.** Slow, network/service dependent, fragile on
   contributor machines and offline CI. Rejected.
2. **Test only on SQLite and ignore PostgreSQL paths.** Leaves the production dialect
   unexercised. Rejected; PostgreSQL paths are written to be runnable and are guarded by
   a dialect check.

## Consequences
- Fast, hermetic default tests; production dialect remains exercisable on demand.
- Two retrieval candidate paths to maintain, clearly separated and labelled.

## Validation (2026-06-20)
The `postgres` marker is implemented (`tests/integration/test_postgres_memory.py`, 13
tests) and skips cleanly unless `ORBITMIND_TEST_POSTGRES_URL` (a disposable DB) is set.
Run locally and green against PostgreSQL 16.13; a CI `postgres-integration` job runs them
against a PostgreSQL 16 service container while the default offline job is unchanged. The
default SQLite suite stays green (190 passed, 13 postgres skipped). A real dialect defect
was found and fixed during validation: SQLite does not enforce foreign keys by default, so
an insert-ordering bug (children before parents) only surfaced on PostgreSQL — fixed by
flushing FK parents before children.

## Review trigger
Revisit if a lightweight, embeddable PostgreSQL-compatible test engine becomes viable,
or if dialect drift causes defects.
