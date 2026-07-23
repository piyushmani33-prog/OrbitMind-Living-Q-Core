# ADR-0039 — Controlled Tool Gateway Foundation v0

- Status: accepted for U8.1A implementation review
- Date: 2026-07-22
- `governance.epistemic`: assumption

## Context

OrbitMind needs a governed boundary between immutable Operation Admission evidence and a future
tool adapter. U8.1A answers only whether one proposal, one verified admission record, and one
code-owned tool version are eligible to reach that future boundary. It does not invoke a tool.

These eleven concepts remain distinct:

| # | Concept | U8.1A meaning |
|---|---|---|
| 1 | Tool definition | Immutable code-owned `ToolDescriptor`. |
| 2 | Tool version | A distinct descriptor identity; versions never mutate in place. |
| 3 | Tool capability | What a descriptor declares; a declaration grants nothing. |
| 4 | Tool registration | Presence in the built-in catalog. |
| 5 | Tool availability | Current `available` or `disabled` descriptor state, separate from registration. |
| 6 | Invocation proposal | Strict immutable reference to one admission and one tool version. |
| 7 | Gateway decision | Deterministic `eligible`, `denied`, or `approval_required` evidence. |
| 8 | Human approval | A withheld state; it performs no execution. |
| 9 | Execution | Deferred and absent. |
| 10 | Execution receipt | Deferred and absent. |
| 11 | Tool result | Deferred and absent. |

Registered is not enabled; enabled is not authorized; authorized is not admitted; admitted is not
an invocation; a proposal is not execution; approval performs no execution; a result is not a
decision. A prior admission record is evidence, never reusable execution permission.

## Decision

Adopt the deterministic catalog plus persisted Gateway Decision v0. Descriptors are code-owned,
immutable, versioned, and checksum-bound. Proposals carry no command, path, URL, environment,
secret, input payload, adapter selection, receipt, or result. The gateway owns no API surface.

The exact first-failure-wins policy is:

| # | Check | Reason | Outcome |
|---|---|---|---|
| 1 | proposal owner differs from trusted owner | `owner_mismatch` | denied |
| 2 | proposal actor differs from trusted actor | `actor_mismatch` | denied |
| 3 | tool id is not registered | `unknown_tool` | denied |
| 4 | registered tool id has no requested version | `unsupported_tool_version` | denied |
| 5 | descriptor class is outside the v0 allowlist | `forbidden_tool_class` | denied |
| 6 | input schema reference differs from the descriptor | `input_schema_mismatch` | denied |
| 7 | descriptor is not available | `tool_unavailable` | denied |
| 8 | owner-scoped admission is absent | `admission_not_found` | denied |
| 9 | admission outcome is not admitted | `admission_not_admitted` | denied |
| 10 | admission actor differs from trusted actor | `admission_actor_mismatch` | denied |
| 11 | admission operation differs from the tool-class mapping | `admission_operation_mismatch` | denied |
| 12 | descriptor requires explicit human approval | `explicit_human_approval_required` | approval required |
| 13 | every check passed | `eligible_by_policy` | eligible |

### Transaction and persistence semantics

`evaluate_tool_invocation` requires a fresh caller-provided session and owns one
`with session.begin():` transaction. Fingerprinting, replay/conflict resolution, replay return,
verified Admission read, catalog resolution, policy evaluation, record construction, and append
are inside it. Successful exit commits; every exception rolls back. Repositories never commit.
The PostgreSQL insertion-race savepoint remains nested inside this transaction.

The owner-scoped table is append-only. Historical replay occurs before current Admission, catalog,
or policy evaluation. A matching fingerprint returns the original immutable record as `replayed`;
a new append is `created`; a changed fingerprint conflicts without writing. The record stores the
verified Admission `record_identity` whenever an owner-scoped Admission was found, even when its
outcome was not admitted. Missing and cross-owner references store `None`. Corrupt Admission or
Gateway evidence fails closed without repair. The decision checksum binds the identity.

### Future adapter seam, explicitly deferred

A later `ToolAdapter` boundary must use typed input and output; timeout and cancellation; resource
limits; enforcement of network, filesystem, process, and external-communication policies;
deterministic adapter identity bound to `(tool_id, tool_version, descriptor_checksum)`; integrity-
protected receipts with an approved threat model and key management; output redaction/quarantine;
and stable failure classification. No adapter module, implementation, construction, invocation,
receipt, result, subprocess, shell, network call, provider contact, worktree mutation, deployment,
spending, hardware, or cloud-quantum path exists in U8.1A.

Fresh governance is mandatory at any future real invocation. Historical Admission and Gateway
records remain evidence only and must not authorize execution by themselves.

## Threat-model summary

Closed contracts prevent command, path, URL, environment, credential, and arbitrary-input
injection. Token grammars reject traversal, URL, wildcard, and control syntax. A closed import and
call allowlist prevents network, process, shell, filesystem, and dynamic-import surfaces. Code-owned
descriptors plus domain-separated checksums address version and descriptor substitution. Owner-
qualified reads hide cross-owner existence. Replay fingerprints prevent idempotency-key reuse with
changed content. Approval is withheld structurally because no execution surface exists.

## Error taxonomy

Malformed contracts raise `ToolGatewayContractError` (`tool_gateway_contract_error`). A non-fresh
session raises `GatewayServiceTransactionError` (`tool_gateway_transaction_error`). Corrupt stored
Gateway evidence raises `GatewayDecisionCorruptError` (`gateway_decision_corrupt`). Corrupt
Admission evidence propagates `AdmissionRecordCorruptError`; idempotency conflicts propagate the
existing conflict error. Unknown, unsupported, unavailable, and governance mismatches are fixed,
public-safe persisted reason codes rather than exceptions. No error exposes cross-owner existence,
payloads, SQL, paths, credentials, or adapter names.

## Consequences and alternatives

Catalog-only was rejected because it creates no governed spine boundary. Real invocation was
rejected because sandbox, run-once, receipt, timeout/cancellation, and adapter controls do not yet
exist. Persistence is accepted because decisions are immutable governance evidence requiring
durable replay and integrity verification.

## Review trigger

Review this ADR before adding an API, adapter, actual input, execution, approval mechanism,
receipt/result, dynamic tool registration, new policy value, descriptor mutability, or any change
to replay, identity binding, transaction ownership, or fresh-governance-at-invocation semantics.
