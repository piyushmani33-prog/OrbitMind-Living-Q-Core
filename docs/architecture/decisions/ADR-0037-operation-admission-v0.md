# ADR-0037 — Operation Admission v0

- **Status:** Accepted
- **Date:** 2026-07-21
- **Phase:** U7.4 (Agent Execution Spine A1.0, slice 1)
- **Related:** ADR-0033 (capability grants & approval authority), ADR-0034 (authority
  persistence), ADR-0035 (authority lifecycle services), ADR-0036 (authority operator API)

## Context

The U7 Authority control plane records capability grants, decisions, revocations, and a pure
deterministic evaluator, but it **executes nothing** — a grant confers no ability by itself.
Before any tool, agent, provider, worktree, command, file mutation, network call, deployment,
or real-world action may enter OrbitMind's controlled execution pipeline, one bounded question
must be answered and recorded:

> "May this proposed operation enter the controlled execution pipeline?"

ADR-0033 explicitly reserved "U7.4 admission" and noted that the authority evaluator is
"directly reusable by U7.4 admission". This ADR introduces that slice.

## Decision

Add **Operation Admission v0**: a deterministic, **non-executing** policy gate that classifies
a bounded proposed operation and persists one immutable, owner-scoped admission record.

### Outcomes (exactly three)
`admitted` · `denied` · `approval_required`. `approval_required` means admission is
**withheld**: no execution may begin, and Operation Admission itself creates no authority
request and grants no approval.

### Architecture
- **Pure domain** `orbitmind/admission/` (`contracts.py`, `policy.py`): frozen, `strict`,
  `extra="forbid"` contracts and a total, side-effect-free `evaluate_admission` function. It
  reads no clock, generates no ids, executes nothing, and **does not import
  `orbitmind.authority`**.
- **Orchestration bridge** `orbitmind/orchestration/admission_lifecycle.py`: the only place
  Authority is consumed. It builds the trusted `AdmissionEvaluationContext`, distills
  owner-scoped Authority evidence into an admission-native `AuthorityFinding` (reusing
  `evaluate_authority` at the single injected `evaluated_at`), invokes the pure policy, and
  persists the record. The clock is injected (no ambient `now()`).
- **Persistence** `orbitmind/persistence/admission_{models,repository}.py`: append-only,
  owner-scoped `operation_admission_records`.
- **No API and no Workbench in v0.** No automatic authority-request creation. No execution
  endpoint.

### Authoritative operation profile
Each supported `operation_kind` has an immutable profile (required capability, side-effect
class, risk class, authority-required, approval-required, forbidden-in-v0) derived from the
kind — never from caller input. A proposal echo that disagrees with the profile is denied
(`operation_profile_mismatch`), so a caller can never reduce risk, side effects, capability
requirements, or approval requirements.

### Deterministic, fail-closed decision order (first-failure-wins)
The pure policy evaluates the following exact precedence and stops at the first failing check
(**first-failure-wins remains authoritative**):

1. **owner mismatch** — proposal owner claim ≠ trusted context ⇒ `owner_mismatch`;
2. **actor mismatch** — proposal actor claim ≠ trusted context ⇒ `actor_mismatch`;
3. **unsupported operation kind** — the `operation_kind` token resolves to no known kind ⇒
   `unsupported_operation_kind`;
4. **operation profile mismatch** — a proposal capability / side-effect / risk echo disagrees
   with the authoritative `OperationProfile` ⇒ `operation_profile_mismatch`;
5. **forbidden operation kind** — a profile-agreeing kind that is forbidden in v0 ⇒
   `forbidden_operation_kind`;
6. **Authority requirement and Authority result** — when the profile requires it, evaluated
   **only** at `context.evaluated_at` (required / not-found / actor / capability / scope /
   validity / revocation);
7. **explicit human approval requirement** (evaluated **after** Authority) ⇒
   `explicit_human_approval_required` (outcome `approval_required`);
8. **admitted by policy** ⇒ `admitted_by_policy` (outcome `admitted`).

**Profile agreement is checked before the forbidden-operation decision** (step 4 precedes
step 5). Therefore:

- a **forbidden** operation carrying **mismatched** profile echoes returns
  `operation_profile_mismatch` **first**;
- a **forbidden** operation carrying the **correct authoritative profile** echoes returns
  `forbidden_operation_kind`;
- **Authority is not consulted for either outcome** (both are decided before step 6).

Ordering profile validation ahead of the forbidden gate prevents caller-controlled capability,
risk, or side-effect echoes from bypassing authoritative profile validation, and the mandatory
human-approval gate at step 7 (after Authority) prevents any valid grant from bypassing required
approval.

### Preserved human-approval rule
push / pull-request / secrets / external-provider / cloud-quantum are **approval-required**
(withheld even with valid authority). merge / deploy / spend / external-communication /
hardware are **forbidden in v0** (denied before Authority). Admission never weakens these.

### Persistence, identity, and replay
Immutable record with **three distinct hashes**: `proposal_fingerprint` (normalized proposal
content + trusted identity, excluding the idempotency key and the decision), `decision_checksum`
(policy version + fingerprint + outcome + ordered reasons + `evaluated_at` + resolved authority
identity), and `record_identity` (domain-separated SHA-256 of the canonical persisted record,
which contains neither `record_identity` nor `canonical_payload` — no self-reference).
`created_at = evaluated_at` (the single injected timestamp). A grant reference is split into a
FK-free `requested_authority_grant_id` and a nullable owner-qualified FK
`resolved_authority_grant_id`, so `authority_not_found` / `revoked` / `expired` / mismatches are
immutably persistable. Replay: same owner + idempotency key + `proposal_fingerprint` returns the
original record; a different fingerprint fails closed with `IdempotencyConflictError`. A record
is historical evidence, **not** a bearer token; later execution admission must independently
re-check current governance and revocation.

### Owner privacy
Grants are resolved owner-scoped; a referenced grant absent from the authoritative owner scope
returns the public-safe `authority_not_found` and never reveals cross-owner existence
(`authority_owner_mismatch` is deliberately absent).

### Malformed-input boundary
A structurally invalid proposal fails at the contract boundary with a sanitized error and
**creates no record**. Transport/contract validation failure is distinct from a persisted
admission denial.

## Alternatives considered
- **Reuse the Authority decision as the admission decision.** Rejected: admission is an
  operation-specific superset check (forbidden kinds, mandatory approval) and must be a
  separate, independently auditable record.
- **Put admission inside `orbitmind.authority`.** Rejected: the authority package is a closed
  3-file allowlist; admission is a separate package, and the authority↔admission bridge lives
  in orchestration.
- **Ship an API/Workbench in v0.** Deferred: the service is fully testable directly; an API
  would enlarge the slice without immediate integration value.

## Consequences
- A new sole Alembic head (`a1f4c7e9b230`) adds one table; head-pinning tests were updated.
- Admission reuses `evaluate_authority` unchanged; no Authority package edit was required.
- A future execution-admission / PIN-approval subsystem integrates by supplying an opaque
  approval reference; admission never handles the PIN and never approves here.

## Review trigger
Revisit when the first execution component (Tool Gateway / Worktree Manager) needs to consume
admission decisions, when additional operation kinds are introduced, or when a v0.1 read/JSON
API is required.
