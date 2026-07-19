# Authority and Capability Grants (U7.0)

The `orbitmind.authority` package is the pure domain foundation of the U7
Authority Control Plane: strict immutable contracts and a deterministic,
side-effect-free evaluation function. It is a **decision layer only** — no
persistence, API, UI, network, filesystem, subprocess, tool, agent,
credential, or execution surface exists in it, and nothing it produces can
perform or authorize a real operation by itself.

Related: [U7_AUTHORITY_CONTROL_PLANE_ROADMAP.md](U7_AUTHORITY_CONTROL_PLANE_ROADMAP.md),
[ADR-0033](decisions/ADR-0033-capability-grants-and-approval-authority.md),
[LABORATORY_FRAMEWORK.md](LABORATORY_FRAMEWORK.md) (declaration vocabulary),
[MODULE_BOUNDARIES.md](MODULE_BOUNDARIES.md).

## 1. Contracts (`authority/contracts.py`)

All models are frozen, `extra="forbid"`, and `strict=True` (no implicit
coercion: a string is never silently an enum, a naïve datetime is never
silently UTC). Schema version: `authority-contracts-v1` on every record.
Identifiers and timestamps are always **supplied by the caller** — this layer
never generates an id and never reads a clock, so equal inputs are equal
records, byte-for-byte, forever.

| Contract | Meaning | Is NOT |
| --- | --- | --- |
| `SubjectReference` | exact principal (`operator/agent/laboratory/tool/adapter` + canonical id) | a wildcard (grammar cannot express one) |
| `AuthorityScope` (+ `ScopeConstraint`) | exact resource_type + resource_id + sorted unique constraints | a pattern, prefix, or glob |
| `ValidityWindow` | mandatory `valid_from < expires_at`, half-open `valid_from <= t < expires_at`, span ≤ `MAX_GRANT_VALIDITY` (366 days) | perpetual, open-ended, or optional |
| `ApprovalRequest` | attributable request for an operator decision | approval, permission, or authority |
| `ApprovalDecision` | attributable `OperatorReference` outcome (`approved/rejected`) echoing the exact request | execution of anything |
| `CapabilityGrant` | scoped expiring non-delegable grant, issued by an `OperatorReference` and linked to request+decision | a credential; possession alone is insufficient — every use is re-evaluated |
| `RevocationRecord` | append-only revocation evidence (`effective_at`) | a mutation of the grant |
| `AuthorityEvaluationRequest` | one exact question + the complete chain + explicit `evaluation_time` | ambient (“current user/now”) context |
| `AuthorityEvaluationDecision` | deterministic result with a stable reason code | a token, credential, or execution handle |

Field grammars are canonical and closed: ids `[a-z0-9][a-z0-9-]{6,62}[a-z0-9]`,
capabilities `[a-z][a-z0-9_]{2,63}` (accommodating the laboratory declaration
vocabulary without importing it), kebab resource types, bounded resource ids
with no `/`, `\`, `..`, or `*`. Free-text `purpose`/`reason` are single-line,
bounded, and reject `://`, path separators, and wildcards, so no external
destination, command, or import path can hide in text. Grant field names are
pinned by test — no secret/token/credential/command/callable field can be
added silently.

`decided_by` and `issued_by` are structurally limited to an
`OperatorReference`; an agent, laboratory, tool, or adapter reference cannot
occupy either field. This pure contract records a canonical operator-designated
principal, not proof of a real-world identity: authentication and the
human-facing approval/issuance workflow are deliberately deferred to U7.2/U7.3.

Canonical serialization: `canonical_authority_json()` — sorted keys, compact
separators, UTF-8, `allow_nan=False` (same convention as the U6.1B laboratory
catalog digest source). Fail-closed ingestion: `parse_authority_json()` wraps
any parse failure in typed `AuthorityContractError`
(`code="authority_contract_error"`).

## 2. Evaluation (`authority/evaluation.py`)

`evaluate_authority(request) -> AuthorityEvaluationDecision` is total, pure,
and clock-free. The documented precedence (exported as
`EVALUATION_PRECEDENCE`, pinned by tests) is:

1. `malformed_authority_chain` — any linkage inconsistency: decision does not
    reference the request; grant does not reference both; owner ids differ
   anywhere; decision or issuance actor is not an `OperatorReference`; request,
   decision, issuance, and evaluation are not ordered
   `requested_at <= decided_at <= issued_at <= evaluation_time`; a revocation
   references another grant/owner; or the decision's echoes drift from the
   request it claims to decide. Malformed chains return `grant_id=None`.
2. `delegation_prohibited` — any delegation request (v1 prohibits all
   delegation; a parent can never transfer authority to a child).
3. `approval_not_approved` — a rejected (or non-approved) decision can never
   generate authority.
4. `approval_grant_mismatch` — the grant must match the approved decision on
   subject, capability, scope, purpose, policy version, and validity, exactly.
5. `subject_mismatch` / `capability_mismatch` / `scope_mismatch` /
   `purpose_mismatch` / `policy_version_mismatch` — the evaluated question
   must match the grant exactly; policy-version drift fails closed.
6. `not_yet_valid` (`t < valid_from`) / `expired` (`t >= expires_at`) — the
   half-open window.
7. `revoked` — `t >= earliest effective_at` among the supplied grant's
   revocations. `recorded_at` remains immutable append-only evidence, while
   `effective_at` is the explicit policy instant; U7.0 makes no persistence or
   retroactive-recording workflow decision.
8. `authorized` — everything above passed.

First failure wins; every code is reachable (tested); `authorized` is true
exactly when the reason code is `authorized`. Decision `detail` strings are
fixed constants enforced by the immutable result contract itself, so parsed or
constructed decisions cannot carry caller-controlled text; malformed results
cannot reference a grant. All timestamp comparisons happen on UTC-normalized
instants, so the same moment expressed in any timezone yields the identical
decision.

## 3. What U7.0 deliberately does not contain

Persistence, migrations, APIs, UI, services, idempotency keys, receipts,
admission, adapters, agents, tools, or any consumer: no other module imports
`orbitmind.authority` yet (enforced by test). Those arrive as U7.1–U7.5 per
the roadmap, each behind its own gates.

## 4. Relationship to existing models

- **Laboratory capability declarations** stay metadata
  (`CAPABILITY_IS_NOT_PERMISSION`); authority contracts are the only path from
  a declared capability toward (future) permission, and even then a grant is
  re-evaluated on every use.
- **`governance.approvals.ApprovalRecord`** is the pre-U7 SR-18 placeholder
  (mutable status, self-generated ids/times). U7.0 leaves it untouched; the
  U7.1 persistence ADR will record its disposition. New authority code must
  not build on it.
- **Audit relationships:** every contract carries the explicit ids
  (request → decision → grant → revocations → evaluations) from which U7.1
  builds append-only persisted chains; nothing here mutates, deletes, or
  summarizes evidence.

## 5. Durable persistence (U7.1)

`orbitmind.persistence.authority_models` + `authority_repository` add
PostgreSQL-first (SQLite-supported) durable storage for the five authority
records as **immutable, append-only, owner-scoped evidence**. Persistence adds
no domain semantics: it stores and reads the U7.0 contracts unchanged.
Related: [ADR-0034](decisions/ADR-0034-authority-persistence-and-append-only-records.md).

- **Tables** (one per record): `authority_approval_requests`,
  `authority_approval_decisions`, `authority_capability_grants`,
  `authority_revocations`, `authority_evaluations`. Alembic head
  `9313833e1f07` (revises `n9c0d1e2f3g4`); the migration creates only these
  tables.
- **Owner scoping.** Composite primary key `(id, owner_id)` on every table, so
  identifiers are unique *per owner* — one owner can never collide with, or
  probe the existence of, another owner's ids. Owner-qualified composite
  foreign keys (`RESTRICT`) make cross-owner links impossible; every read and
  write is owner-scoped, and a not-found result is indistinguishable from
  another owner's record (both `None`).
- **Append-only / immutable.** The repository exposes only `append_*` /
  `get_*` / `list_*` / `read_authority_chain`; there is no update, delete,
  approve, reject, issue, evaluate, or execute method. No mutable status is
  stored — *expired* and *revoked* are derived by U7.0 evaluation from explicit
  timestamps and revocation evidence, never persisted as truth. `RESTRICT`
  foreign keys mean no cascade can erase evidence.
- **Canonical identity.** Each row stores the full canonical domain JSON plus a
  domain-separated SHA-256 `record_identity` (identity, not signature). Reads
  re-parse the payload through the frozen contract and recompute the identity,
  so tampered or unknown-enum rows fail closed (`AuthorityRecordCorruptError`).
  No column stores a secret, credential, token, command, import path, or
  filesystem path.
- **Causality** (validated at the mapping boundary, with FKs as defense in
  depth): a decision must echo an existing same-owner request; a grant must
  reference an existing same-owner **approved** decision and match it exactly;
  a revocation must reference an existing same-owner grant; an evaluation must
  reference the exact same-owner chain and its stored result must equal
  `evaluate_authority(request)`. Orphaned or mismatched records raise
  `AuthorityCausalityError` and the transaction rolls back.
- **Idempotency.** Each append takes an explicit `idempotency_key`; a replay
  with the same `(owner_id, key)` and identical canonical payload returns the
  stored record, and a conflicting payload (or a reused record id with
  different content) fails closed with `IdempotencyConflictError`. Different
  owners may reuse the same external key. Detection is by deterministic
  pre-check (never by relying on a database constraint to fire), so a single
  SQLite transaction is never poisoned; PostgreSQL additionally recovers from a
  concurrent-insert race via a savepoint.
- **Transactions.** Writes are transactional; a failed or orphaned append
  leaves no partial record and preserves prior truth.
- **Per-grant serialization.** PostgreSQL serializes revocation and evaluation
  appends by taking the same owner-qualified capability-grant row lock for the
  caller's active transaction. That lock is the persistence linearization
  point: an evaluation uses the complete committed revocation set when it
  acquires the lock, and a later revocation never rewrites earlier append-only
  evaluation evidence or compensates an already completed action. SQLite keeps
  the same repository behavior for local/offline use but does not prove the
  PostgreSQL row-blocking guarantee.
- **Evaluation projections.** The canonical request and decision payloads are
  semantic truth. Every duplicated evaluation scalar (owner, identifiers,
  schema version, time, capability, policy version, result, reason, and
  relevant revocation identity) is recomputed or compared on every read.
  Projection mismatches fail closed; the idempotency key is storage metadata,
  not a semantic payload projection.

Persistence is storage only: it implements no lifecycle service, API, UI, or
runtime enforcement (those are U7.2+). The pure `orbitmind.authority` package
still imports nothing from persistence (enforced by test).
