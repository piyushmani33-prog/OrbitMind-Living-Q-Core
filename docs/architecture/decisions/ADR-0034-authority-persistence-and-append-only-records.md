# ADR-0034 — Authority Persistence and Append-Only Records (U7.1)

- **Status:** Accepted (2026-07-18)

## Context

U7.0 ([ADR-0033](ADR-0033-capability-grants-and-approval-authority.md))
delivered `orbitmind.authority` as pure, strict, deterministic contracts +
evaluation, with caller-supplied ids and times and no persistence. Everything
after U7.0 (lifecycle services, operator surface, admission) needs durable,
attributable, append-only storage of authority evidence. U7.1 adds that
storage and nothing else — no lifecycle service, API, UI, or runtime
enforcement.

## Problem

Persist approval requests, approval decisions, capability grants, revocations,
and authority-evaluation records as immutable, owner-scoped, append-only
evidence, without changing U7.0 domain semantics, and with idempotent,
transactional, fail-closed behavior on both PostgreSQL (production system of
record) and SQLite (default local/test database, ADR-0023).

## Decision

Add `orbitmind.persistence.authority_models` (five SQLAlchemy rows) and
`orbitmind.persistence.authority_repository`
(`SqlAlchemyAuthorityRepository`), following existing repository conventions
(the research/optimization/observation modules). One Alembic migration
(`9313833e1f07`, revises `n9c0d1e2f3g4`) creates the five tables.

Key decisions:

1. **Store the contract, not a re-modelled schema.** Each row keeps the exact
   scalar identities needed for owner-scoped reads, causality foreign keys, and
   uniqueness, plus a `canonical_payload` JSON column holding the full
   `canonical_authority_json(...)` of the U7.0 contract. Row-to-domain
   re-parses that payload through the frozen contract via `parse_authority_json`
   (fail-closed), so unknown enums / wrong types / tampered data raise
   `AuthorityRecordCorruptError` and no coercion can widen a stored record.
2. **Canonical record identity.** A domain-separated SHA-256 over the canonical
   payload (`record_identity`, per-record-type separator) is stored and
   recomputed on read — identity, not signature, reusing `core.checksums`. It
   excludes storage metadata; it is deterministic across PostgreSQL and SQLite.
3. **Owner scoping via composite primary key `(id, owner_id)`.** Ids are unique
   *per owner*, so one owner cannot collide with — or, on insert, probe the
   existence of — another owner's identifier (a sole-`id` key would leak
   cross-owner id existence via a primary-key violation). Composite
   owner-qualified foreign keys (`RESTRICT`) make cross-owner links impossible.
   Every repository read/write is owner-scoped; not-found never discloses
   another owner's record.
4. **Append-only by construction.** The repository exposes only
   `append_*`/`get_*`/`list_*`/`read_authority_chain`. There is no update,
   delete, approve, reject, issue, evaluate, or execute method. No mutable
   status column exists — *expired*/*revoked* are derived by U7.0 evaluation,
   never stored. `RESTRICT` foreign keys prevent cascade erasure of evidence.
5. **Causality at the mapping boundary + FK defense in depth.** Appends
   validate the full chain in Python (decision echoes request; grant references
   an existing **approved** decision and matches it; revocation references an
   existing grant; evaluation references the exact chain and its stored result
   equals `evaluate_authority(request)`), raising `AuthorityCausalityError`
   before any write; owner-qualified foreign keys enforce the same invariants
   at the database.
6. **Idempotency by deterministic pre-check.** Each append takes an explicit
   `idempotency_key`; resolution checks both `(owner, key)` and `(owner, id)`
   in Python, returning the stored record on an identical-payload replay and
   raising `IdempotencyConflictError` on a conflicting payload. Because
   duplicates are detected before any insert, a single SQLite transaction is
   never poisoned. On PostgreSQL, a concurrent-insert race is additionally
   recovered inside a `SAVEPOINT`; SQLite disables savepoints (matching the
   existing observation repositories, since pysqlite does not participate in
   SAVEPOINT-based outer rollback).
7. **Explicit UTC time only.** All timestamps originate from the domain
   contracts (already UTC-normalized) and round-trip through the shared
   `UTCDateTime` type; naïve input is rejected upstream. No server-default
   replaces an authority event time; `recorded_at` and `effective_at` stay
   distinct.
8. **Per-grant append serialization.** PostgreSQL revocation and evaluation
   appends take the same `SELECT ... FOR UPDATE` lock on the exact
   `(owner_id, grant_id)` capability-grant row in the caller's transaction.
   The lock spans persisted-chain resolution, revocation loading, deterministic
   evaluation, comparison, and insertion. It defines the evidence
   linearization point: a later revocation affects subsequent evaluations but
   does not rewrite earlier append-only evidence or compensate completed
   actions. SQLite remains supported for local persistence tests without
   claiming PostgreSQL row-lock behavior.
9. **Evaluation projections are verified, never trusted.** The canonical
   request and decision payloads, their combined record identity, and every
   duplicated semantic evaluation scalar are verified on read. A mismatch,
   including a nullable relevant-revocation identity or normalized UTC time,
   raises `AuthorityRecordCorruptError`; reads neither repair nor skip a
   corrupt row. The idempotency key is storage metadata rather than a canonical
   semantic projection.

## Alternatives considered

- **Shred every nested field into columns** — rejected: nested subject/scope/
  validity would need many tables or JSON anyway; the canonical-payload +
  re-parse approach guarantees exact round-trip and fail-closed reads with far
  less surface, and matches the receipt/research precedent.
- **Sole-`id` primary key (globally unique ids)** — rejected: it leaks
  cross-owner id existence on insert and weakens owner isolation; composite
  `(id, owner_id)` is the security-correct choice.
- **Database triggers for immutability** — rejected: the repository omits
  update/delete methods and the ORM never issues them; triggers are not used
  consistently elsewhere and add dialect-specific surface. Constraints +
  method-absence + tests are sufficient.
- **Reuse `governance.approvals.ApprovalRecord`** — rejected (as in ADR-0033):
  its mutable status and generated ids/times contradict append-only,
  deterministic storage. It remains untouched; U7 authority is the forward
  model.

## Downgrade implications

`alembic downgrade` drops the five tables and therefore permanently discards
the authority evidence they hold. Downgrade is intended for development/test
rollback of an unreleased schema only; it is **not** a safe way to dispose of
audit evidence in an environment holding real records. Operators must back up
first (`docs/operations/DATABASE_MIGRATION_BACKUP.md`). The migration
documents this in its module docstring.

## Security implications

No secret/credential/command/import-path/filesystem column exists; owner
isolation is structural (composite PK + owner-qualified FKs + owner-scoped
reads); evidence is append-only and non-cascadeable; tampered/unknown stored
data fails closed on read. Possession of a persisted grant id confers nothing —
authority is always re-evaluated by U7.0. No API, UI, or runtime enforcement is
introduced.

## Compatibility implications

PostgreSQL-first, SQLite-supported; no SQLite-only types (JSON, String,
`UTCDateTime`, Boolean). Alembic remains the schema authority; ORM
`create_all()` is a local/test convenience only. One new head `9313833e1f07`.

## Future (U7.2 lifecycle services) and exclusions

U7.2 will add application services (create request, record decision, issue
grant from an approved decision, revoke, evaluate, list, read chain) on top of
this storage, projecting status from records rather than mutating it. U7.1
explicitly excludes services, API, UI, runtime enforcement, admission,
adapters, agents, tools, execution, dependency/lock changes, and CI changes.

## Review trigger

Revisit when U7.2 lifecycle services land (they must not introduce mutable
status or bypass owner scoping), or if a retention/export requirement ever
needs a non-destructive archival path distinct from downgrade.
