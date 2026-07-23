# U8 Controlled Tool Gateway Roadmap

`governance.epistemic`: assumption

## Delivered U8.1A boundary

U8.1A delivers strict frozen contracts, three immutable code-owned descriptors, the exact
13-row deterministic eligibility policy, a lifecycle bridge to owner-scoped verified Admission
evidence, and append-only Gateway Decision persistence. It has no API and no execution surface.

The corrected production semantics make the lifecycle own a fresh transaction. A successful
decision commits and survives session close and database restart; any exception rolls back.
Replay is resolved before current evaluation, an identical request returns the original record as
`replayed`, and a changed fingerprint conflicts without writing. Found Admission evidence binds
its fail-closed-verified `record_identity` into the stored record and decision checksum; misses and
cross-owner references bind no identity.

## Deferred slices

| Future gate | Candidate scope | Explicitly absent from U8.1A |
|---|---|---|
| Acceptance/API planning | Authenticated typed proposal and evidence-read surface | No router, container wiring, or Workbench affordance |
| Adapter architecture | Typed adapter seam, limits, timeout, cancellation, policy enforcement | No adapter module or construction |
| Execution control | Fresh governance, approval consumption, run-once, sandbox enforcement | No invocation, subprocess, shell, network, worktree, provider, or agent action |
| Receipt/result integrity | Threat model, key management, redaction, result quarantine | No receipt or tool result |
| Extended catalog | Reviewed registration and version lifecycle | No user, downloaded, dynamic, provider, or agent-authored tools |

## Next planning gate

After U8.1A passes fresh independent review and exact-head PostgreSQL validation, a human may
authorize planning for the acceptance/API slice. That gate must preserve the non-equivalences in
ADR-0039 and must not infer permission to implement execution. Phase advancement is never
automatic.

U8.1A evaluates and persists governance evidence only. It does not execute any tool.
