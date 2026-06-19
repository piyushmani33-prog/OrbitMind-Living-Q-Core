# Mission Lifecycle — OrbitMind Living Q-Core

## States
```
received ──▶ validated ──▶ running ──▶ completed
   │             │            │
   └──▶ failed ◀─┴────────────┘   (any stage may transition to failed)
```

## Stage → spine mapping
| Stage | Spine node | Audit action | Notes |
|-------|-----------|--------------|-------|
| received | Mission Intake | `mission.submitted` | Raw request stored verbatim (SR-03). |
| validated | Mission Validation | `mission.validated` | Pydantic + domain validators; safe 422 on failure. |
| running | Prime Orchestrator → Domain Workflow | `workflow.started` | Deterministic in-process workflow opens a `WorkflowRun`. |
| running | Data / Tools | `propagation.completed` / `propagation.failed` | SGP4 over the window; failures explicit (SR-08). |
| running | Verification & Evidence | `verification.completed` | Deterministic findings produced. |
| running | Structured & Visual Output | `artifact.generated` (×N) | Charts + sidecars under artifacts/<mission_id>/. |
| completed | Memory Update | `mission.completed` | Persisted; retrievable. |
| failed | — | `mission.failed` | Recorded with reason; never silently dropped. |

## Human approval
Phase 1 missions are read-only deterministic compute and require **no** approval.
The `ApprovalRecord` model and the `approvals`/governance boundary exist so that
future risky actions (e.g., promoting a generated tool, contacting an external
service) can be gated (SR-18). The spine's "Human Approval when required" node is
a no-op for Phase 1 missions, by policy, not by omission.

## Evaluation & improvement
"Evaluation" and "Controlled Improvement Proposal" spine nodes are represented in
Phase 1 by the verification findings + audit record that make a mission auditable
and reproducible. Automated evaluation harnesses arrive with later phases
(see EVALUATION_STRATEGY.md).

## Idempotency & reproducibility
Re-running the identical request yields identical `orbital_samples` (same sgp4
version). Each mission has a fresh UUID; artifacts live under that UUID.
