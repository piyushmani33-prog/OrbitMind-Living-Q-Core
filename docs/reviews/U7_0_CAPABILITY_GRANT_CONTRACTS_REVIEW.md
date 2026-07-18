# U7.0 Capability Grant Contracts Review

- **Review date:** 2026-07-18
- **Branch:** `feature/u7-0-authority-contracts`
- **Base / HEAD / main / origin/main:** `8d518b8b98999731170cac9ad7f70016d82f4c45`
- **Review mode:** fresh-context implementation review followed by fresh-context
  delta review. Neither reviewer modified the repository or ran the full suite.

## Files Inspected

- `src/orbitmind/authority/__init__.py`
- `src/orbitmind/authority/contracts.py`
- `src/orbitmind/authority/evaluation.py`
- `tests/test_authority_contracts.py`
- `tests/test_authority_evaluation.py`
- `tests/test_authority_architecture.py`
- `docs/architecture/AUTHORITY_AND_CAPABILITY_GRANTS.md`
- `docs/architecture/U7_AUTHORITY_CONTROL_PLANE_ROADMAP.md`
- `docs/architecture/MODULE_BOUNDARIES.md`
- `docs/architecture/decisions/ADR-0033-capability-grants-and-approval-authority.md`

`orbitmind.authority` is correctly located as a pure domain package. The amended
module-boundary entry is narrow: it permits only `core`, documents pure
contracts/evaluation, and grants no API, persistence, UI, Agent Runtime,
provider, dynamic-loading, tool, quantum, hardware, or execution exception.

## Contracts And Evaluation

The slice implements immutable, strict, schema-versioned approval requests and
decisions, exact subjects and scopes, mandatory bounded validity windows,
operator-typed decision and issuance actors, non-delegable grants, append-only
revocation records, and canonical deterministic serialization.

`evaluate_authority()` is a side-effect-free, explicit-time decision function.
It fails closed for malformed linkage, non-operator actors, temporal causality
violations, delegation, rejection, exact-parity drift, request/grant mismatch,
window boundaries, and revocation. It returns only policy evidence: stable reason
codes, fixed immutable detail text, and no credential, executable handle, token,
secret, command, or capability to perform an operation.

The exact causality rule is:

```
requested_at <= decided_at <= issued_at <= evaluation_time
```

No U7.0 contract authenticates a real-world human. `OperatorReference` records
an attributable operator-designated principal and rejects agent, laboratory,
tool, and adapter actors structurally; authenticated approval/issuance is a
separate U7.2/U7.3 concern.

## Original F3/F4 Evidence

The continuation authorization reported F3/F4 corrections but no original review
artifact, finding text, or identifier was preserved in the Claude evidence root,
sealed patch, reachable repository history, or current worktree. The labels are
therefore **not independently identifiable**.

Their reported substance is present and verified as follows:

- **Reported F3, substance only:** evaluation details were hardened for
  immutability. The final implementation uses a `MappingProxyType` fixed-detail
  mapping and the decision contract validates exact detail-to-reason parity.
- **Reported F4, substance only:** authority architecture guards and regression
  tests were strengthened. The final AST tests enforce a closed import surface,
  prohibit clock/I/O/execution calls, prohibit module-level mutable state, and
  prohibit premature consumers outside the authority package.

This evidence limitation is historical provenance, not a finding against the
current implementation. It must not be represented as proof of the original
reviewer’s exact wording.

## Independent Review And Delta

The first fresh-context review found and the correction addressed:

1. **P1, causal authorization:** a grant could otherwise evaluate before the
   recorded request/decision/issuance sequence completed. Evaluation now requires
   the full ordered chain and tests cover decision-before-request,
   grant-before-decision, and evaluation-before-issuance.
2. **P1, actor boundary:** decision and issuance actors were unconstrained ids.
   They are now `OperatorReference` values, and evaluator defensive checks reject
   tampered non-operator actors as malformed.
3. **P2, forged evaluation detail:** parsed result records could carry arbitrary
   `detail` text. The contract now requires the exact fixed detail for its reason
   code and forbids a grant reference on malformed results.

The independent delta review verified all three corrections and found:

| Severity | Count |
| --- | ---: |
| P0 | 0 |
| P1 | 0 |
| P2 | 0 |
| P3 | 0 |
| Informational | 0 |

## Validation At Review Time

The corrected focused set passed before this record was finalized:

```text
58 passed, 1 warning
tests/test_authority_contracts.py
tests/test_authority_evaluation.py
tests/test_authority_architecture.py
tests/test_architecture_boundaries.py
```

Ruff import normalization and the focused lint check passed. The full source
suite has not started. The required post-review focused/static validation,
Alembic check, pre-suite seal, single durable full-suite run, and patch-parity
check remain governed by the continuation gate.

## Scope Exclusions And Remaining Risk

U7.0 adds no persistence, migration, API, UI, runtime enforcement, approval
issuance workflow, Agent Runtime, consumer, adapter, plugin, network operation,
external AI, cloud, quantum execution, hardware access, dependency, or lockfile
change. No module outside `orbitmind.authority` consumes the package.

The remaining risk is intentionally deferred integration work: authenticating
operators, persisting append-only records, lifecycle issuance, revocation
recording policy, and operational admission each require their own approved
future slice. An allowed U7.0 decision is never execution authority.

## Verdict

**PASS FOR PRE-SUITE VALIDATION.** The reviewed U7.0 contracts-and-architecture
slice is bounded, pure, and ready for the required pre-suite checks and exactly
one complete source-suite run. This verdict is not a commit, merge, deployment,
or runtime-execution authorization.
