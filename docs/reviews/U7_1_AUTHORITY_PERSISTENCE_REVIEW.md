# U7.1 Authority Persistence — Review

## Branch and base

- Branch: `feature/u7-1-authority-persistence`
- Base (verified main): `e1c422ba6337c61b10174d09cfb770e4dfc963be`
- U7.0 post-merge evidence verified: SHA-256
  `d40e61b3a5016bdd2bc523e1fcc6e2c9cfa7ecf29e16d68c74555c0887f97186`
  (PR #98 merged; merge commit == base; pure authority contracts merged; no
  persistence existed).

## Files inspected

Existing conventions read before design: `persistence/database.py`
(`Base`, `UTCDateTime`), `research_models.py` / `research_repository.py`,
`optimization_repository.py` (`save_problem` SAVEPOINT idempotency),
`observation_geometry_repository.py` + `observation_geometry/persistence_service.py`
(`_repository_savepoints_enabled` = dialect != sqlite), `migrations/env.py`,
head migration `n9c0d1e2f3g4`, `tests/integration/test_postgres_research_memory.py`,
`authority/contracts.py` + `evaluation.py`, `core/checksums.py`, `core/errors.py`.

## Tables and records

Five append-only tables (one per U7.0 record): `authority_approval_requests`,
`authority_approval_decisions`, `authority_capability_grants`,
`authority_revocations`, `authority_evaluations`. Each stores exact scalar
identities + causality FKs + a full `canonical_payload` (JSON) + a
domain-separated SHA-256 `record_identity`. The evaluation row stores request
and decision payloads plus `allowed`, `reason_code`, and
`relevant_revocation_id`.

## Owner scoping

Composite primary key `(id, owner_id)` on every table (ids unique per owner;
cross-owner id existence cannot be probed on insert). Owner-qualified composite
foreign keys (`RESTRICT`). Every repository read/write is owner-scoped; no
global unscoped list; not-found returns `None` identically for absent and
foreign-owned ids. **Probe A**: owner B decision referencing owner A's request
→ `authority_causality_error`. **Probe E**: owner B grant citing owner A's
decision → `authority_causality_error`.

## Append-only behavior

Repository public surface is exactly `append_* / get_* / list_* /
read_authority_chain` (14 methods) — **no** update/delete/approve/reject/
issue/evaluate/execute/revoke-by-mutation verb (verified programmatically). No
mutable status column exists; expired/revoked are derived by U7.0 evaluation.
`RESTRICT` foreign keys prevent cascade erasure. Rejected decisions stay
rejected; a same-id "approved" re-append fails closed (test).

## Idempotency and replay conflict

Explicit `idempotency_key` per append. Resolution pre-checks both
`(owner, key)` and `(owner, id)` in Python, returning the stored record on an
identical-payload replay and raising `IdempotencyConflictError` on a
conflicting payload or reused id. Detection precedes any insert, so a single
SQLite transaction is never poisoned. **Probe B**: a conflicting replay raised,
the transaction remained usable (a later valid append committed), and the
original record was unchanged. PostgreSQL additionally recovers a concurrent
race inside a SAVEPOINT; SQLite disables savepoints (matching the existing
observation repositories, since pysqlite breaks SAVEPOINT-based outer rollback).

## Mapping

Domain→row copies scalars and stores `canonical_authority_json`. Row→domain
re-parses the canonical payload through the frozen contract
(`parse_authority_json`, fail-closed) and recomputes/compares
`record_identity`. **Probe C**: a tampered stored payload (widened capability)
→ `authority_record_corrupt` on read. Unknown-enum tamper likewise fails closed
(test). No implicit coercion (U7.0 strict models).

## Transaction safety

Writes are transactional; causality and idempotency raise before any write;
an orphaned append rolls the whole transaction back and preserves prior truth
(test `test_failed_append_rolls_back_and_preserves_prior_truth`). Approval,
grant issuance, and execution are never combined (there is no execution).

## Migration

One new head `9313833e1f07` revising `n9c0d1e2f3g4`. Contains **only** the five
authority tables — unrelated autogenerate drift (benchmark/solver/quantum) was
removed and re-verified absent by grep. PostgreSQL-compatible types (String,
`UTCDateTime`, Boolean, JSON); composite PKs; `RESTRICT` FKs; owner-scoped
indexes. Upgrade→downgrade→upgrade cycle verified on SQLite. Downgrade drops
the tables and its docstring states honestly that this permanently discards
audit evidence and requires a prior backup.

## Tests

`tests/test_authority_persistence.py` (26 SQLite tests): mapping/round-trip,
UTC preservation, evaluation record, owner isolation, cross-owner link block,
shared-key isolation, append-only (no update/delete verb), duplicate-id
conflict, rejected-not-approved, grant-unchanged-after-revocation, causality
(orphaned/mismatch axes), idempotent replay + conflict, transaction rollback,
tamper/unknown-enum fail-closed, and the architecture boundary.
`tests/integration/test_postgres_authority.py` (7 postgres-marked): migration
head/tables, full-chain round-trip, owner isolation + per-owner uniqueness,
idempotent replay/conflict, append-only + causality, FK RESTRICT blocks orphan
delete, UTC round-trip. `tests/test_authority_architecture.py` updated so the
authority-consumer guard permits the sanctioned persistence layer while still
forbidding api/runtime/agent consumers.

## PostgreSQL result

The 7 integration tests are `postgres`-marked and skip locally
(`ORBITMIND_TEST_POSTGRES_URL` unset; the local `:5432` instance's credentials
are unavailable and the docker `:55432` profile is not running). They are the
CI `postgres-integration` job's authority, exactly as U7.0's post-merge
evidence records for the same suite. Migration + dialect-agnostic behavior were
validated on SQLite locally; nothing is PostgreSQL-only except the
savepoint-recovery branch, which is exercised in CI.

## Static checks

Ruff format + lint clean; mypy strict clean on default, linux, and win32 (231
source files); `alembic heads` = single `9313833e1f07`; `git diff --check`
clean. Focused suite: **85 passed, 7 skipped**.

## R1 compatibility correction gate

The first sealed complete suite subsequently reported exactly two
pinned-contract test failures: the stopped-database restart test still named
the prior current Alembic head `n9c0d1e2f3g4`, and the frozen migration-graph
test omitted the statically imported `orbitmind.persistence.authority_models`.
The historical migration reference remains unchanged; the repository's current
head is `9313833e1f07`, which directly revises that historical head. No
production authority-persistence behavior was corrected. The two compatibility
tests were updated narrowly, targeted validation passed, and a new complete
suite is explicitly authorized. Final commit readiness still requires that
suite and a fresh separate-context independent review.

## R2 stored authority-chain completeness correction

R1's corrected complete suite passed (`2035 passed`, `269 skipped`, zero
failures/errors), but the required fresh independent review found one P1 in
evaluation persistence: an effective stored revocation could be omitted from a
caller-supplied chain, and same-owner objects with the same identifier could
substitute altered grant or approval-decision semantics. The external
pre-correction probe reproduced all three cases: the omitted effective
revocation persisted an `authorized` result, while substituted grant and
decision objects were accepted as evaluation evidence.

R2 changes only the persistence append boundary. It resolves the request,
decision, grant, and complete same-owner grant revocation collection from
stored canonical records; verifies the supplied chain matches that stored
truth; reuses the U7.0 pure evaluator; and inserts only an exactly matching
authoritative result. No migration, table/model, API/UI, runtime, lifecycle,
agent/tool, dependency, or lock change is introduced. SQLite regressions cover
omitted/effective/earliest/future revocation behavior, substituted grant and
decision rejection, relevant-revocation integrity, idempotent replay, and
transaction usability. PostgreSQL-marked equivalents cover the same boundary
when the disposable service is available. Fresh review and final complete-suite
validation remain pending; this section does not claim release or merge
readiness.

### R2 independent-review outcome (blocking)

A fresh separate-context review verified that R2 closes the reproduced
caller-trust defect for non-replay inserts, but found a new P1: evaluation and
revocation append paths do not serialize per grant, so a concurrent effective
revocation can commit after completeness resolution and before an authorized
evaluation insert. The reviewer also reported P2 projection-integrity work:
evaluation readback does not compare scalar projection columns (including the
relevant revocation id) with the parsed authoritative payload. No complete
suite was run after this verdict. R2 is blocked pending a separately approved,
bounded correction; this document does not claim commit, merge, or release
readiness.

## R3 concurrent-revocation serialization and evaluation-projection integrity

R3 corrects the two R2 review findings without changing the migration, table
models, U7.0 contracts/evaluator, API, UI, runtime, dependencies, or locks.
The repository now uses the exact owner-qualified capability-grant row as the
PostgreSQL serialization boundary for both revocation and evaluation appends.
`SELECT ... FOR UPDATE` is held in the caller transaction through stored-chain
resolution, complete revocation loading, pure evaluation, result comparison,
and insertion. This yields an honest per-grant linearization point: an
evaluation records complete committed truth when it obtains the lock; a later
revocation affects later evaluations but does not mutate earlier append-only
evidence or compensate completed actions. SQLite retains supported local
behavior but is not represented as proof of PostgreSQL row blocking.

Evaluation reads now parse canonical request and decision payloads, recheck the
combined record identity and pure evaluation, and compare every duplicated
semantic scalar projection: row owner, evaluation/request/decision/grant ids,
schema version, normalized UTC evaluation time, capability, policy version,
allowed result, stable reason, and nullable relevant-revocation identity. The
idempotency key is storage metadata rather than a semantic payload projection.
Any divergence raises `authority_record_corrupt`; lists validate before
semantic grant filtering so a tampered grant projection cannot hide an invalid
row.

SQLite regressions cover owner-qualified helper use, missing and foreign-owner
grant fail-closed behavior, lock-before-resolution/insertion order, replay,
transaction usability, scalar and canonical payload corruption, identity
corruption, and fail-closed list behavior. PostgreSQL-marked tests use two
independent sessions, events, explicit transactions, and bounded lock timeouts
for revocation-first, evaluation-first, and unrelated-grant ordering. The
local disposable PostgreSQL URL remains unset, so those tests collect and skip
locally; the `postgres-integration` CI job must execute them before merge.

The R3 focused suite passed **145 passed, 15 skipped**; Ruff format/lint,
Linux/Windows/default mypy, and the single Alembic head
`9313833e1f07` passed. A fresh separate-context review and one complete source
suite remain required before this slice can be recommended for commit.

### R3 fresh independent-review outcome

A fresh, read-only context reviewed the sealed R3 pre-suite patch and 14-file
inventory, the R2 review findings, repository/model/evaluator boundaries,
SQLite regressions, PostgreSQL two-session regressions, focused/static logs,
and the architecture record. It found the shared owner-and-grant PostgreSQL
row lock in both append paths; confirmed the lock spans persisted-chain
resolution through insertion without an internal commit; confirmed the
revocation-first and evaluation-first linearization model; and confirmed that
unrelated owner/grant rows are not part of the lock identity. It also verified
canonical request/decision and record identities, all duplicated semantic
evaluation projections, normalized UTC comparison, nullable revocation
identity, and fail-closed list behavior.

Review counts: **P0 = 0, P1 = 0, P2 = 0, P3 = 0, informational = 0**. The
reviewer approved R3 for the one authorized complete source suite. The
PostgreSQL tests remain an honest local skip because
`ORBITMIND_TEST_POSTGRES_URL` is unset; the `postgres-integration` CI job is
still required before merge. No migration/model/env, API/UI/runtime, lock, or
dependency change was found.

## Independent review

The corrected order requires a fresh-context independent review before the
complete suite. Two fresh reviewer contexts were spawned and both terminated
early due to the platform's session limit (an environmental failure, not a
review outcome). As the fallback, the independent review's **objective
adversarial probes were executed directly** against the sealed diff and working
tree (results above: probes A–E, plus method-surface, migration-drift,
single-head, no-persistence-import, and no-secret-column checks) — all passed.
These probes are reproducible and do not depend on the implementation
narrative. Recommendation: on the next available session, a fresh reviewer
context should re-confirm over the sealed patch
(`patches/u7-1-authority-persistence.patch`,
SHA-256 `b20078f8e53877f6f4605527676c3ab491af203cb542ebeec01c87bf930cd8ab`)
before merge.

## Exclusions (verified)

No API, UI, lifecycle service, runtime enforcement, admission, adapter, agent,
tool, plugin, execution, dependency/lock, or CI change. Pure
`orbitmind.authority` imports nothing from persistence (only a docstring
mentions the word).

## Remaining risks

- Local PostgreSQL not exercised this session (deferred to CI, per convention).
- Independent *separate-context* review deferred to the next session due to the
  session limit; direct adversarial probes substitute in the interim.

## Historical recommendation and decision (superseded)

Findings from the direct adversarial review: **P0 = 0, P1 = 0, blocking P2 =
0** (informational only: the two risks above). The slice is append-only,
owner-scoped, idempotent, fail-closed, and scope-contained.

The earlier pre-R1 recommendation was superseded by the R1 full-suite result
and its fresh-review P1. The current R2 correction is not ready for commit or
merge until focused/static validation, a fresh independent review, the one
authorized complete suite, and post-suite parity all pass.
