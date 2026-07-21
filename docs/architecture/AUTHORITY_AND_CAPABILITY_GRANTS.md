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

U7.0 itself contains no persistence, migrations, API, UI, services,
idempotency keys, receipts, admission, adapters, agents, or tools. Reviewed
consumers arrive in later slices: U7.1 persistence, U7.2 lifecycle services,
and the strictly transport-only U7.3 operator API. The authority-consumer guard
allows only those reviewed layers; runtime, camera, laboratory, sources, and
other consumers remain prohibited.

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

## 6. Lifecycle application services (U7.2)

`orbitmind.orchestration.authority_lifecycle` is the owner-scoped application
boundary above the frozen U7.0 contracts and the U7.1 append-only repository.
It accepts strict immutable commands, opens exactly one transaction for each
explicit mutation, and returns only persisted authority evidence. It has no
API route, authentication middleware, runtime enforcement, provider, tool,
agent, subprocess, filesystem-discovery, or operation-execution surface.

The command sequence is deliberately explicit and non-automatic:

1. `CreateApprovalRequestCommand` stores a request, which is never authority.
2. `RecordApprovalDecisionCommand` stores one attributable terminal decision.
   The v1 policy is exactly one terminal decision per request; an identical
   replay returns that record and a different second decision fails closed.
   PostgreSQL serializes that check by locking the exact owner-scoped approval
   request row for the service transaction.
3. `IssueCapabilityGrantCommand` requires an existing approved decision and
   reconstructs subject, capability, scope, purpose, policy, and validity from
   stored authority truth. It does not accept those widening-sensitive values
   from the caller.
4. `RevokeCapabilityGrantCommand` appends revocation evidence and never mutates
   the grant. The earliest effective stored revocation governs later explicit
   evaluations.
5. `EvaluateAuthorityCommand` may evaluate only an existing owner-scoped grant
   that exactly links its stored request and approved decision. The pure U7.0
   evaluator determines the result; U7.1 persists allowed and denied
   grant-backed evaluation evidence atomically.

### Rejection and pre-grant semantics

An `ApprovalDecision(outcome="rejected")` is itself durable, attributable,
append-only denial evidence. It cannot produce a `CapabilityGrant`, and the
lifecycle service fails closed with `authority_decision_rejected` before any
evaluation is constructed or persisted. There is no nullable, synthetic,
placeholder, or fabricated grant chain.

Likewise, an approved decision without an explicitly issued grant is not
execution authority. Evaluation fails closed with `authority_grant_not_found`
and creates no `AuthorityEvaluation` row. Only an existing persisted grant may
be evaluated. A future generalized command-refusal receipt belongs to a later
operation-admission/receipt phase, not authority persistence.

This preserves the U7.1 invariant that `AuthorityEvaluationRequest` is
strictly grant-backed and that evaluation persistence requires an approved,
exact stored chain. The original U7.2 draft requested a denied evaluation for
rejected decisions; that conflict was resolved by treating the rejected
`ApprovalDecision` as the durable denial evidence, with no migration and no
causality weakening.

### Read and replay model

`AuthorityChainReadModel` returns stored request, decision, grant, revocation,
and evaluation tuples in deterministic repository order. It stores no mutable
status: pending, rejected, approved-ungranted, and granted are truthful
projections of the records. Owner-qualified not-found behavior is
non-disclosing, corrupt evidence fails closed, and every command receives
explicit identifiers, actors, policy versions, and UTC-normalized event times.
No service reads a clock or generates an identity.

## 7. Operator API and Approval Workbench (U7.3)

U7.3 exposes the existing lifecycle services through two local-only evidence
surfaces:

- `/api/authority/*` is a bounded JSON transport surface for owner-scoped
  requests, decisions, grants, revocations, evaluations, and deterministic
  evidence reads.
- `/authority/workbench/*` is a server-rendered Approval Workbench with
  explicit POST/Redirect/GET forms. It projects stored evidence only; it does
  not admit an operation, invoke a tool, run an agent, execute a command, or
  emit an execution receipt.

### Trusted-local limitation

This slice is deliberately **not production authentication or multi-user
authorization**. The only owner value comes from the established trusted-local
dependency, and the matching fixed operator actor is supplied by the same
trusted-local context. JSON bodies, forms, query strings, and route parameters
cannot select or override either identity. The context is an explicit future
authentication insertion point, not proof of a human identity or a privilege
escalation mechanism.

Every Authority route also rejects a direct peer other than `127.0.0.1` before
it reads or mutates evidence. This is a transport containment guard, not a
replacement for production authentication: remote binding, proxy forwarding,
or multi-user access remain outside U7.3 and require a separate threat model.

The API router is a transport adapter only: it parses bounded input, constructs
strict U7.2 commands, maps typed lifecycle errors to HTTP, and renders bounded
responses. It does not construct `SqlAlchemyAuthorityRepository`, open a
repository transaction, evaluate policy, or decide authority. Lifecycle
services remain the sole boundary that constructs the repository and owns
transactions. In particular, grant issuance reconstructs its truth from the
stored decision chain through the lifecycle service, never from a router-side
repository read.

### Shared page CSRF authority

`orbitmind.core.page_csrf.PageCsrfRegistry` is the one in-memory process owner
for protected local pages. `AppContainer` creates one process-binding key and
one registry with static `CAMERA` and `AUTHORITY_WORKBENCH` policies. The Camera
compatibility adapter delegates to that registry, preserving the existing
Camera page contract without introducing a second secret or registry. Authority
has no independent registry, secret, port setting, authentication mechanism,
or durable session store.

The registry stores only scoped page-session and token digests, compares token
digests in constant time, bounds active sessions, expires records, and rotates
a token only after a successful authority check. Authority and Camera scopes
cannot exchange tokens. Tokens are never placed in URLs or logs. Authority
forms use a separate `HttpOnly`, `SameSite=Strict`, path-scoped cookie namespace
under `/authority/workbench`.

For every modifying Authority form, the registry requires exact `http`
same-origin protocol inputs: `Host` and `Origin` must both match
`127.0.0.1:<runtime-selected-port>`, `Sec-Fetch-Site` must be `same-origin`,
and forwarded headers are rejected. The selected port is the established runtime
`Settings.custom_tle_handoff_port`; U7.3 adds no fixed Authority port. A missing,
invalid, expired, cross-session, cross-scope, forwarded, or cross-origin token
fails closed before lifecycle mutation. Each Workbench mutation additionally
requires an explicit form confirmation. The protocol preflight occurs before
the bounded form body is consumed, so a cross-origin or forwarded request is
rejected before form decoding.

### Bounded evidence reads and scope cap

All operator lists are bounded. List projections, including exact-grant
revocation and evaluation lists, read one bounded probe row so their `truncated`
marker is truthful at the requested limit. The Workbench independently probes
its request, grant, revocation, and evaluation summaries, and labels a request
summary only as recorded until the detail page reads the complete evidence
chain. Exact-grant projection reads are owner- and grant-filtered in the
database; the grant projection uses an exact aggregate revocation count and a
one-row latest-evaluation read rather than mistaking a capped page for complete
evidence. Grant issuance reads only the stored request and decision required to
construct its command, so later bounded evidence does not block an otherwise
valid idempotent grant replay. Revocation and evaluation replays likewise use
exact owner- and grant-scoped record reads rather than a capped evidence page.
Complete request chains fail closed when their bounded evidence shape is
exceeded. The U7.3 remediation is intentionally constrained to nine changed
production Python paths: shared core CSRF, Camera compatibility, container
wiring, API schemas, presentation/router transport, lifecycle/repository
bounded reads, and API error mapping. It makes no migration, dependency, lock,
runtime-enforcement, or operation-admission change.
