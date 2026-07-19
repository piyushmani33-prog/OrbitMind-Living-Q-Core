# U7.2 Authority Lifecycle Application Services — Review

## Branch and foundation

- Branch: `feature/u7-2-authority-lifecycle-services`
- Base / current HEAD: `685c3bbdd16466b86d22ae0479b77a2530f6f352`
- U7.1 post-merge evidence: SHA-256
  `1dec1a5037eab71eb6c0e84e412d5ecfc67a8bc919a4f967cd1c7ee23a5abe3e`
- U7.2 scope-blocker evidence: SHA-256
  `9847a504440687d4ee1ca648c95e2009c8e234fec649f0c594bf11918354dc62`

U7.1 remains the append-only authority persistence authority. U7.2 adds an
orchestration-layer application boundary only; it does not add an API, UI,
runtime enforcement, admission, tool, provider, agent, adapter, plugin,
network, dependency, lock, or migration change.

## Architecture and production path

`src/orbitmind/orchestration/authority_lifecycle.py` follows the existing
application-service pattern used by observation geometry and planning: callers
provide a fresh SQLAlchemy `Session`; each explicit command opens one outer
`session.begin()` transaction; repositories never commit independently. An
active caller transaction is rejected, so a service cannot accidentally commit
unrelated work.

The module depends only on U7.0 authority contracts/evaluation, U7.1 authority
persistence, `Session`, and core safe error/time helpers. The pure
`orbitmind.authority` package remains closed: it imports neither orchestration
nor persistence. The authority-consumer guard permits only persistence and this
reviewed orchestration layer; API, runtime, camera, quantum, laboratory, and
sources remain forbidden.

## Commands and lifecycle behavior

All commands are Pydantic strict, frozen, and `extra="forbid"`. They require
owner, identifiers, policy version, idempotency key, actors, and event times
explicitly. Commands normalize only supplied timezone-aware timestamps to UTC;
they never read a clock or generate an identity.

- **Request:** creates a non-authoritative `ApprovalRequest` and replays
  deterministically through U7.1 idempotency.
- **Decision:** reconstructs echoes from the stored request, requires matching
  policy and non-preceding time, and implements one terminal decision per
  request. Only an exact replay is allowed after the first record.
- **Grant:** requires an approved stored decision, exact request/decision
  linkage, matching policy and validity, and reconstructs all
  broadening-sensitive fields from stored truth. Grant issuance is separate
  from decision recording.
- **Revocation:** appends immutable evidence for an existing owner-scoped grant;
  the grant itself remains unchanged.
- **Evaluation:** loads an exact stored request/decision/grant chain and the
  complete persisted revocation set, runs the pure evaluator, then appends the
  resulting allowed or denied grant-backed evidence through U7.1.

## Rejected and ungranted semantics

The original U7.2 wording requested an evaluation row for a rejected decision,
but U7.1 correctly requires a non-null grant tied to an approved decision. The
scope analysis retained that evidence and U7.2-A1 resolves it without a schema
change:

- A rejected `ApprovalDecision` is immutable attributable denial evidence.
- A rejected decision creates neither a grant nor an `AuthorityEvaluation`.
- Grant issuance and evaluation fail closed as `authority_decision_rejected`.
- An approved decision without a persisted grant is still non-authoritative;
  evaluation fails as `authority_grant_not_found` and records no evaluation.
- After explicit issuance, allowed and ordinary denied outcomes remain
  grant-backed persisted evaluation evidence.

No nullable, placeholder, fabricated, or synthetic grant/evaluation chain is
introduced. The complete request-chain read model truthfully represents
pending, rejected, approved-ungranted, and granted evidence through immutable
tuples, never a mutable status column.

## Tests and validation

Focused SQLite service, transaction, architecture, U7.0, and U7.1 tests cover
strict contracts, replay and conflict behavior, owner isolation, terminal
decision behavior, rejected and ungranted preconditions, grant broadening,
grant-backed authorized/denied evaluation, revocation ordering, rollback, and
fresh-session transaction ownership. PostgreSQL-marked tests cover the service
path against the existing migrated tables; they skip honestly without a
configured disposable database and remain required in exact-head CI.

Pre-suite validation passed: the focused authority command collected 141 tests
and completed **136 passed, 5 skipped** (the five PostgreSQL-marked U7.2
service tests; `ORBITMIND_TEST_POSTGRES_URL` is unset). The combined existing
and U7.2 PostgreSQL command collected 20 tests and skipped all 20 for the same
honest local-environment reason. Ruff format/lint passed repository-wide.
Linux, Windows, and default strict mypy each passed across 232 source files.
`alembic heads` remains the single `9313833e1f07` head.

Three separate read-only reviewer contexts examined the evolving pre-suite
patch. The first found a P1 terminal-decision race and P2 command-boundary
validation gap; both were corrected. The second required stronger proof that a
concurrent PostgreSQL decision command was actually waiting on the request-row
lock. The final review confirmed that the regression now observes the second
`SELECT ... FOR UPDATE` dispatch and a real `pg_stat_activity` `Lock` wait
before the first transaction releases. Final counts are **P0 = 0, P1 = 0,
blocking P2 = 0, P3 = 0** after a documentation wording correction.

The sealed patch/inventory, complete-suite result, and post-suite parity are
recorded in external U7.2 evidence. This document does not claim a commit,
merge, or release.

## Risks and exclusions

U7.2 deliberately provides no operator-facing authentication or approval
workflow, no current-authority cache, and no execution admission. A persisted
grant remains insufficient by itself: a future operation-admission boundary
must request explicit-time evaluation. A generalized command-refusal receipt is
also deferred; a rejected approval decision already supplies the only durable
denial evidence needed for this authority lifecycle.

## Recommendation and decision

Approved for the one sealed complete source-suite run. No commit, push, PR,
merge, or release is performed by this review document.
