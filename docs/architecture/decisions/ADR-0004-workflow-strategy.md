# ADR-0004 — Workflow Strategy

- **Status:** Accepted (2026-06-19)

## Context
Missions are multi-step (intake → propagate → verify → persist → visualize) and
will eventually include long-running, durable, approval-gated workflows. Temporal
is the intended durable engine, but operating it in Phase 0/1 is unjustified.

## Decision
- Implement an **in-process, deterministic `Workflow` abstraction** in
  `orchestration`. The Prime Orchestrator runs ordered steps, records a step log
  on `WorkflowRun`, and emits audit events.
- Define the abstraction (a small interface: named steps, status, step log) so a
  **Temporal-backed implementation can be substituted later** without changing
  callers.
- Do **not** install or operate Temporal or Celery in Phase 0/1.

## Alternatives considered
1. **Temporal now.** Durable + retriable but heavyweight (server, workers, ops) for
   a synchronous offline slice. Rejected for Phase 0/1.
2. **Celery now.** Designed for short async jobs, not durable approval-gated
   workflows; adds a broker (Redis). Rejected.
3. **Inline procedural code, no abstraction.** Simplest but no seam for durability;
   would force a rewrite later. Rejected.

## Consequences
- Phase 1 missions run synchronously within the request (fast, deterministic).
- Long-running/durable behavior (retries, timers, human-approval waits) is not yet
  available; it arrives with the Temporal-backed implementation behind the same
  interface.

## Review trigger
Revisit when a mission must survive process restarts, wait on human approval for
minutes/hours, or fan out long-running parallel steps.
