# U7 Authority Control Plane — Program Roadmap

Program owner: Claude (implementation, testing, review orchestration).
Human authority: **Piyush Mani** — sole approver for merge, deployment,
publication, network access, external AI, dependency installation, cloud,
quantum submission, camera/microphone, physical hardware, and any real tool
execution beyond an explicitly approved slice.

## Objective

A complete, auditable authority control plane so that future agents, tools,
Laboratories, adapters, and connected workflows cannot perform sensitive
operations merely because they declare a capability or can reach a tool. U7
ends with OrbitMind ready for the U8 Tool Gateway; U7 itself never becomes a
general operation executor.

## Non-negotiable distinctions (all slices)

Declaration ≠ permission ≠ grant; request ≠ approval; approval ≠ execution;
grant possession alone ≠ authority; registration ≠ activation ≠ authorization;
evaluation ≠ execution; an allowed evaluation is not a credential; a receipt
is not scientific correctness; digest is identity, not trust; lineage is not
delegated authority; tool availability grants nothing; a previous approval
never silently authorizes a different action; rejection/expiry/revocation/
mismatch/uncertainty fail closed.

## Slice plan

| Slice | Scope | Explicitly out of scope | Gate |
| --- | --- | --- | --- |
| **U7.0** Authority contracts + deterministic evaluation | Pure domain package `orbitmind.authority`: strict immutable contracts (subject, scope, approval request/decision, grant, revocation, evaluation request/decision), stable reason codes, canonical serialization, side-effect-free `evaluate_authority` | persistence, migration, API, UI, network, filesystem, subprocess, agents, adapters, dynamic loading | READY FOR U7.0 CAPABILITY GRANT CONTRACTS COMMIT AND PR APPROVAL |
| **U7.1** Authority persistence *(implemented)* | PostgreSQL-first (SQLite-supported) append-only records for requests/decisions/grants/revocations/evaluations; composite `(id, owner_id)` owner scoping; canonical-payload + SHA-256 record identity with fail-closed reads; explicit idempotency keys; causality validated at the mapping boundary with `RESTRICT` FKs as defense in depth; Alembic head `9313833e1f07`; no update/delete/lifecycle surface, no cascade erasing evidence. See [ADR-0034](decisions/ADR-0034-authority-persistence-and-append-only-records.md). | API, UI, lifecycle services, runtime enforcement | READY FOR U7.1 AUTHORITY PERSISTENCE COMMIT AND PR APPROVAL |
| **U7.2** Lifecycle + application services | create request / decide / issue grant from approved decision only / revoke / evaluate / list / read full chain; status projected from records, never mutable truth; explicit actor + explicit UTC evaluation time; idempotent replay | tool or agent execution, external providers | READY FOR U7.2 AUTHORITY LIFECYCLE SERVICES COMMIT AND PR APPROVAL |
| **U7.3** Operator API + approval Workbench | authenticated owner-scoped read + mutation endpoints (CSRF where applicable, idempotency keys, bounded payloads, stable errors) and a truthful approval surface (pending/approved/rejected/active/future/expired/revoked, exact subject/capability/scope/purpose/window/policy, explicit "approval does not execute" warnings); desktop/mobile/reduced-motion/keyboard/no-external-resource verification | any execution surface, autonomous approval, fake activity | READY FOR U7.3 AUTHORITY OPERATOR SURFACE COMMIT AND PR APPROVAL |
| **U7.4** Operation Admission v0 *(implemented)* | pure Authority-free admission policy; orchestration-only Authority bridge; deterministic proposal fingerprint and decision checksum; append-only owner-scoped Admission decision evidence; fail-closed replay/conflict and integrity reads | API, UI, execution, run-once, execution receipts, adapters, tools, repository mutation, shell, providers, agents, AI, cloud, quantum, camera, hardware | READY FOR U7.4 OPERATION ADMISSION V0 COMMIT AND PR APPROVAL |
| **U7.5A** Authority-Admission acceptance | trusted-local Admission JSON API; authoritative created/replayed disposition; owner-scoped Admission and Authority-Admission evidence reads; normal operator journey plus controlled actor/clock/revocation/restart/tamper probes; existing Authority Workbench browser acceptance; SQLite and PostgreSQL validation | operation execution, run-once, execution receipts, command/tool results, Controlled Tool Gateway, worktree operations, providers, agents, deployment, spending, external communication, hardware, cloud quantum | READY FOR U7.5A FRESH INDEPENDENT REVIEW |

## Per-slice delivery requirements

Branch from verified main → sealed changed-file manifest → focused tests →
Ruff (format + lint) → strict mypy (default, Linux, Windows) → Alembic-head
verification → exactly one complete source-suite run when production code
changes (no automatic rerun; a failure is preserved and a bounded correction
gate is requested) → independent fresh-context review over sealed evidence
(P0/P1/blocking-P2 block commit and merge) → external evidence package →
explicit staging (never `git add .`) → one commit (no amend/rebase/force) →
one PR → CI observed read-only → **stop before merge** → Piyush Mani approves
→ post-merge byte-parity verification → `git pull --ff-only` before the next
slice. Never start a slice from an unmerged branch; never combine slices.

## Cross-slice security requirements (summary)

Fail closed; immutable strict contracts; no wildcard or perpetual authority;
no naïve timestamps; no ambient clock in deterministic logic; no automatic
approval/issuance/renewal/delegation; no ambient authority or global mutable
grant registry; no secret-, command-, or import-path-bearing records; no
credentialized evaluation results; no deletion of audit evidence; no
cross-owner authority; no mixed approval+execution transaction; no dynamic
loading; no external network/AI/hardware without separate human approval.

## Relationship to existing code

- `orbitmind.laboratory.capabilities` remains the *declaration* vocabulary
  (metadata; never permission). Authority contracts reference capabilities as
  canonical tokens and deliberately do not import the laboratory package.
- `orbitmind.governance.approvals.ApprovalRecord` is the pre-U7 SR-18
  placeholder (mutable status, generated ids/times). It remains untouched in
  U7.0; U7 authority contracts are the authoritative model for capability
  authority going forward, and later slices will record its disposition
  (supersede or adapt) in the U7.1 ADR.
- A future separately approved Controlled Tool Gateway may consume Authority and
  Admission decision evidence; neither record is an execution token or receipt,
  and nothing in U7.5A executes anything.

## Program-level risks

1. Scope creep toward execution (mitigated by per-slice forbidden lists).
2. Status-field drift vs append-only truth (U7.2 projects status from records).
3. Clock ambiguity (explicit evaluation time everywhere; ambient-clock AST
   guard in tests).
4. Approval fatigue in U7.3 UX (prompts show exact action, scope, window).
5. Owner-scoping regressions (dedicated isolation tests from U7.1 onward).
