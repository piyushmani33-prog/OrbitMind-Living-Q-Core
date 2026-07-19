# ADR-0035 — Authority Lifecycle Application Services (U7.2)

- **Status:** Accepted (2026-07-19)

## Context

U7.0 established pure, strict authority contracts and a deterministic evaluator.
U7.1 added owner-scoped append-only PostgreSQL-first persistence for requests,
decisions, grants, revocations, and grant-backed evaluation evidence. Neither
phase coordinated lifecycle commands. U7.2 adds that application coordination
without adding an operator API, runtime enforcement, operation admission, or
execution capability.

The original U7.2 draft also asked for a persisted denied
`AuthorityEvaluation` for a rejected approval decision. That conflicts with
U7.1's intentional causality model: a rejected decision cannot issue a grant,
while every evaluation record requires a non-null grant linked to an approved
decision. The recorded scope analysis preserved this conflict rather than
weakening the chain.

## Decision

Add `orbitmind.orchestration.authority_lifecycle` as the application-service
module. The orchestration layer is already the architecture-approved boundary
between domain contracts and persistence. The pure `orbitmind.authority`
package remains closed and does not import this module or persistence.

The module provides frozen, `extra="forbid"`, strict commands for:

1. request creation;
2. terminal decision recording;
3. explicit capability-grant issuance;
4. append-only grant revocation;
5. existing-grant authority evaluation; and
6. deterministic owner-scoped lists and complete request-chain reads.

Each command receives all identifiers, actors, policy versions, idempotency
keys, and UTC-normalized event times explicitly. The service owns one outer
transaction over a fresh caller-provided SQLAlchemy session; it rejects an
already-active session so it never commits unrelated caller work. U7.1 remains
the sole persistence/canonicalization/causality/serialization boundary.

The service uses a narrow U7.1 request-row `FOR UPDATE` read to serialize the
terminal-decision check on the exact `(owner_id, request_id)` row. PostgreSQL
therefore permits only the first terminal decision transaction to append; a
concurrent conflicting command waits, observes the stored decision, and fails
closed. SQLite preserves the same sequential service behavior without claiming
PostgreSQL row-lock semantics.

### Terminal-decision and rejection policy

U7.2 v1 permits exactly one terminal `ApprovalDecision` per approval request.
An exact replay returns the stored decision; any semantically different second
decision fails closed. A rejected decision is durable, attributable,
append-only denial evidence. It creates no grant and no evaluation. Grant
issuance and evaluation fail closed with `authority_decision_rejected` before
evaluation persistence.

An approved decision without an explicit grant is likewise non-authoritative:
evaluation fails with `authority_grant_not_found`, persists no evaluation, and
leaves later explicit issuance available. Only valid persisted grant chains are
passed to the pure evaluator. Its allowed and denied results are both appended
as U7.1 authority-evaluation evidence.

The read model returns stored evidence only. It has no mutable lifecycle-status
column and reads no hidden clock; pending, rejected, approved-ungranted, and
granted states are derived from the returned tuples.

## Alternatives considered

- **Grantless rejection evaluation or nullable `grant_id`** — rejected: it
  changes the frozen evaluation contract and its table semantics.
- **Synthetic or placeholder grant** — rejected: it fabricates authority
  evidence and violates approved-decision grant causality.
- **Second rejection-evaluation table** — rejected: it duplicates decision
  evidence and requires a new persistence model/migration without a current
  authority need.
- **Mutable lifecycle status** — rejected: it would duplicate rather than
  project append-only truth.
- **API/container/runtime wiring** — deferred: U7.2 is an application-service
  boundary only; an operator surface and operation admission require later
  separate authorization.

## Security implications

No automatic approval or grant issuance exists. Grant construction loads all
widening-sensitive fields from stored request and decision truth. Cross-owner
records are non-disclosing not-found results. Replays use U7.1's deterministic
canonical idempotency semantics. No command accepts a credential, tool handle,
callable, command line, import path, or network destination, and the module
does not perform I/O outside its transaction-bound persistence calls.

## Compatibility implications

No U7.0 contract, U7.1 repository invariant, table, migration, dependency, or
dependency-lockfile changes. U7.2 adds the reviewed request-row lock read only
to serialize terminal decisions; it leaves U7.1's per-grant
revocation/evaluation serialization intact. The Alembic head remains
`9313833e1f07`, SQLite retains local support, and existing persistence evidence
remains canonical.

## Review trigger

Revisit for the future U7.3 operator API, operation-admission/refusal receipts,
or any requirement for a distinct non-grant command outcome. Those additions
must not overload grant-backed evaluation evidence.
