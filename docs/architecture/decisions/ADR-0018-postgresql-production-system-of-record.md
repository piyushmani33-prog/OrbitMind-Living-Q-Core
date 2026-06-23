# ADR-0018 — PostgreSQL as the Production System-of-Record

- **Status:** Accepted (2026-06-20)

## Context
Phase 0–3A used SQLite as the persistence backend. SQLite is excellent for offline,
deterministic unit tests but is not the intended production store for durable
scientific memory (documents, claims, evidence, retrieval indexes). Phase 3B
introduces full-text retrieval, which benefits from a real RDBMS engine.

## Decision
- **PostgreSQL is the production system-of-record.** SQLite is retained for fast,
  offline unit tests and basic local development.
- Production behaviour **must not depend on SQLite-only features**. All schema and
  queries go through SQLAlchemy with dialect-aware code; raw SQL is limited and
  guarded by a dialect check (`Database.is_postgres`).
- The repository pattern (`persistence/*_repository.py`) keeps the domain layer free
  of dialect details, so SQLite↔PostgreSQL is a configuration change
  (`ORBITMIND_DATABASE_URL`), not a domain change.
- A local PostgreSQL profile is provided via Docker Compose
  (`docker compose --profile postgres up -d postgres`); the `psycopg` driver is an **optional**
  install extra (`pip install -e .[postgres]`).
- **No destructive migration of user data.** Alembic migrations are additive; the
  Phase 3B migration only creates new tables/indexes and is reversible.

## Alternatives considered
1. **Stay on SQLite in production.** No real full-text engine, weaker concurrency,
   not the intended durable store. Rejected.
2. **MySQL.** Weaker full-text/JSON and no first-class `tsvector`. Rejected.

## Consequences
- Tests stay fast and offline on SQLite; production gains a real engine + FTS.
- A small amount of dialect-aware code (retrieval candidate selection, the FTS index)
  must be maintained and clearly labelled.

## Validation (2026-06-20)
Validated against a real PostgreSQL **16.13** (driver psycopg **3.3.4**) via the Compose
profile: the full migration chain reaches head on a **fresh** PostgreSQL database (39
tables), PostgreSQL-specific DDL (FTS GIN index) succeeds, no migration falls back to
SQLite behaviour, existing satellite/source/small-body tables are intact, and a
`pg_dump`/`pg_restore` development smoke test round-trips counts + checksums. SQLite
remains the default for offline unit tests.

## Review trigger
Revisit if concurrency/scale needs outgrow a single PostgreSQL instance, or if a
managed vector/search service is adopted.
