# ADR-0003 — Storage Strategy

- **Status:** Accepted (2026-06-19)

## Context
The platform needs a durable system of record. Production target is PostgreSQL,
but Phase 0/1 is a local, offline, single-user slice where provisioning Postgres
would add operational weight with no current benefit.

## Decision
- Use **SQLAlchemy 2.0** ORM for all persistence behind **repository interfaces**.
- Use **SQLite** locally and in automated tests (file DB for dev, temp DB for
  tests).
- Use **Alembic** for migrations from the start.
- Document **PostgreSQL** as the production system of record; switching is a
  configuration change (`ORBITMIND_DATABASE_URL`) plus a Postgres-specific
  migration revision — no domain-logic rewrite.

## Alternatives considered
1. **Provision PostgreSQL now (Docker).** Closer to prod but unnecessary ops for an
   offline slice; violates "do not install/provision unless genuinely required".
   Rejected for Phase 0/1.
2. **Raw SQL / no ORM.** Less abstraction but couples domain logic to SQLite and
   complicates the Postgres move. Rejected.
3. **Document store / JSON files.** Loses transactional integrity and querying.
   Rejected.

## Consequences
- Domain code is storage-agnostic via repositories; SQLite↔Postgres swap is low
  risk.
- Must avoid SQLite-only SQL features in domain code; JSON columns use SQLAlchemy's
  portable `JSON` type. Postgres-specific optimizations (JSONB, GIN) are deferred.

## Review trigger
Revisit when multi-user/concurrent writes, full-text/pgvector retrieval, or cloud
deployment (Phase 3/8) require PostgreSQL.
