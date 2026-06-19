# System Architecture — OrbitMind Living Q-Core

## Style
Modular monolith with strong internal boundaries (ADR-0001). One deployable
process; modules communicate through typed in-process interfaces. Seams are
designed so high-load modules (quantum, simulation) can later be extracted to
services *only when measured load justifies it* — not now.

## Layered view
```
┌───────────────────────────────────────────────────────────────────────┐
│ api/            FastAPI routers, request/response schemas, error handlers│
├───────────────────────────────────────────────────────────────────────┤
│ orchestration/  Prime Orchestrator + in-process deterministic Workflow   │
├───────────────────────────────────────────────────────────────────────┤
│ mission/  space/  science/  verification/  visualization/  (domain)      │
│ optimization/  quantum/ (bounded adapter)                                │
├───────────────────────────────────────────────────────────────────────┤
│ persistence/    SQLAlchemy models + repository interfaces (SQLite now)   │
│ sources/        source registry + fixture loaders (offline)              │
│ governance/     audit, epistemic policy, approval records                │
├───────────────────────────────────────────────────────────────────────┤
│ core/           config, logging, errors, units, ids, checksums, types    │
│ observability/  health, version, capabilities reporting                  │
└───────────────────────────────────────────────────────────────────────┘
```

## Dependency rule
Dependencies point **downward** only:
`api → orchestration → domain → persistence/sources/governance → core`.
`core` depends on nothing internal. Domain modules MUST NOT import `api`.
The orbital slice MUST NOT import `quantum`.

## Request flow (orbit-propagation mission)
1. `api` receives `POST /api/v1/missions/orbit-propagation`, parses into a typed
   request model, returns safe 422 on validation error.
2. `orchestration.PrimeOrchestrator` opens a `WorkflowRun`, records audit
   "mission submitted/validated/workflow started".
3. `sources` loads the bundled TLE fixture (provenance attached).
4. `space.propagation` runs SGP4 over the window → `OrbitalStateSample[]`.
5. `verification` runs deterministic checks → `VerificationFinding[]`.
6. `governance` assigns epistemic status to outputs; records audit events.
7. `persistence` writes mission, inputs, samples, findings, provenance, artifacts.
8. `visualization` renders altitude-vs-time and ground-track charts + sidecars.
9. `api` returns a typed `MissionResultResponse` carrying provenance.

## Key abstractions
- **Workflow** (`orchestration.workflow.Workflow`) — in-process, deterministic,
  step-logged; interface allows a future Temporal-backed implementation (ADR-0004).
- **Repository** (`persistence.repositories`) — per-aggregate interfaces; SQLite
  implementation today, Postgres later (ADR-0003) with no domain change.
- **QuantumAdapter** (`quantum.adapter`) — bounded capability surface; classical
  baseline required for any future quantum result (ADR-0005).
- **EpistemicStatus** (`governance.epistemic`) — single enum applied to outputs
  (ADR-0006).

## Configuration & DI
Typed settings (`core.config.Settings`, pydantic-settings) are loaded once and
injected via FastAPI dependencies. No module reads environment variables directly
except `core.config`.
