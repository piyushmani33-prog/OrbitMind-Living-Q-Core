# ADR-0033 — Capability Grants and Approval Authority (U7.0 Contracts)

- **Status:** Accepted (2026-07-18)

## Context

U6/U6.1 delivered capability *declarations* that are structurally incapable of
expressing permission. Everything agentic that OrbitMind plans (U8 Tool
Gateway, U9 agent runtime, external adapters, connected windows) requires the
opposite object: an attributable, scoped, expiring, revocable **grant**, plus
a deterministic way to answer "is this exact action authorized at this exact
instant?" without executing anything. No such primitive exists;
`governance.approvals.ApprovalRecord` is a mutable-status SR-18 placeholder
with self-generated ids/times and no scope, expiry, linkage, or evaluation
semantics.

## Decision

Introduce `orbitmind.authority` as a **pure contracts + evaluation domain**
(U7.0), with persistence, services, APIs, admission, and the operator surface
following as separately gated slices (U7.1–U7.5).

Key design decisions:

1. **Caller-supplied identity and time.** No id generation, no clock reads in
   the package (AST-enforced). Determinism and replay-safety are structural,
   and U7.1 persistence gets explicit deterministic identifiers for free.
2. **Strict, coercion-free models.** Pydantic `strict=True`, frozen,
   `extra="forbid"`; naïve datetimes rejected and aware ones normalized to
   UTC via the existing `core.timeutils.ensure_utc`.
3. **Closed grammars instead of validation blacklists.** Ids, capability
   tokens, resource references, and policy versions are canonical patterns
   that cannot express wildcards, paths, URLs, or import references; free
   text additionally rejects `://`, `/`, `\`, `..`, `*`, and control
   characters. "No wildcard authority" is unrepresentable, not just checked.
4. **Capability as token, not laboratory import.** Authority is universal
   (missions, laboratories, future tools all reference capabilities by
   canonical token). The `laboratory` package is deliberately NOT imported —
   the declaration vocabulary and the authority plane stay decoupled; the
   token grammar accommodates the existing `LabCapability` values.
5. **Full-chain echo + exact-parity evaluation.** Decisions echo the request;
   grants echo the decision; evaluation re-verifies every echo and every link
   (ids, owners, revocation targets), requires operator-typed decision and
   issuance actors, and requires
   `requested_at <= decided_at <= issued_at <= evaluation_time`. It fails
   closed with `malformed_authority_chain` on any drift. A tampered, miswired,
   or not-yet-issued chain can never evaluate as authorized. The operator type
   records an attributable principal only; authentication is a later lifecycle
   concern, not a U7.0 dependency.
6. **Fixed evaluation precedence** (exported constant, pinned by tests):
   malformed → delegation_prohibited → approval_not_approved →
   approval_grant_mismatch → subject/capability/scope/purpose/policy
   mismatches → not_yet_valid → expired → revoked → authorized. Half-open
   validity `valid_from <= t < expires_at`; revocation applies from the
   earliest `effective_at <= t`.
7. **Delegation prohibited by vocabulary.** `DelegationPolicy` contains only
   `PROHIBITED` in v1; grants pin it with a `Literal`. Lineage can never
   transfer authority silently; a future delegation feature requires a new
   reviewed schema, not a flag flip.
8. **No perpetual grants, structurally.** `expires_at` is mandatory and the
   window span is capped at `MAX_GRANT_VALIDITY = 366 days` — a deliberate
   structural ceiling beneath any future policy layer.
9. **Decisions are not credentials.** `AuthorityEvaluationDecision` carries a
   stable reason code and only the exact fixed detail text for that code;
   parsed values cannot forge arbitrary messages. An authorized decision
   requires the `authorized` reason code and a grant reference; a malformed
   decision requires no grant reference. No decision carries executable or
   secret-bearing data, and it confers nothing by itself. U7.4's admission
   boundary and U8's gateway are the only intended consumers.

## Alternatives considered

- **Extend `governance.approvals`** — rejected: its mutable status field,
  default-generated ids/times, and lack of scope/expiry contradict the
  append-only, deterministic requirements; retrofitting would break its
  existing narrow SR-18 usage. Disposition of the legacy model is deferred to
  the U7.1 persistence ADR.
- **Embed an authorization engine (Cedar/OPA)** — rejected for v1: OrbitMind
  needs exact-match, offline, dependency-free evaluation over its own
  append-only records; an engine adds a dependency and an expression language
  (wildcards, conditions) that v1 explicitly forbids. Revisit only if
  multi-user policy complexity ever demands it.
- **Signed grant tokens (macaroon-style)** — rejected for v1: tokens become
  possession-based credentials, exactly what the distinctions prohibit;
  OrbitMind evaluates records, not bearer artifacts. Signing may later apply
  to *evidence export*, not to authority itself.
- **Clock-reading evaluation (`now()` default)** — rejected: hidden time
  dependency breaks determinism, replay, and testability; explicit
  `evaluation_time` is mandatory everywhere.

## Consequences

- U7.1 persistence can store every contract as-is (canonical JSON payloads +
  explicit ids) and project status instead of mutating it.
- The evaluation function is directly reusable by U7.4 admission and the U8
  gateway with zero behavioral drift.
- Because delegation, wildcards, and perpetuity are unrepresentable, future
  relaxations are conscious schema changes with their own ADRs.
- The 366-day ceiling means long-lived standing authority is impossible;
  operators renew deliberately.

## Review trigger

Revisit when U7.1 persistence lands (legacy `ApprovalRecord` disposition),
when delegation is ever proposed, or if multi-user policy requirements exceed
exact-match evaluation.
