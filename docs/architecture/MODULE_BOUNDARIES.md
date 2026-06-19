# Module Boundaries — OrbitMind Living Q-Core

Each module has a single responsibility and a typed public surface. Modules marked
**(stub/doc-only)** are documented for the architecture but NOT implemented in
Phase 0/1 — they will be added in their roadmap phase. No empty modules are
created merely for appearance.

| Module | Phase 0/1 status | Responsibility | May import |
|--------|------------------|----------------|------------|
| `core` | Implemented | config, logging, errors, ids, units, checksums, shared types | — (stdlib + pydantic) |
| `api` | Implemented | HTTP routers, request/response schemas, error handlers, versioning | orchestration, mission, core, observability |
| `observability` | Implemented | health/version/capabilities reporting | core, persistence |
| `mission` | Implemented | mission domain models, request validation, status lifecycle | core |
| `orchestration` | Implemented | Prime Orchestrator + in-process Workflow abstraction | mission, space, verification, visualization, persistence, governance, sources, core |
| `sources` | Implemented (offline) | source registry + bundled fixture loaders + provenance | core |
| `space` | Implemented | SGP4 orbital propagation, coordinate transforms, units | core, sources |
| `verification` | Implemented | deterministic checks → structured findings | core |
| `visualization` | Implemented | altitude + ground-track charts, JSON sidecars, path guard | core |
| `governance` | Implemented | audit events, epistemic status policy, approval records | core, persistence |
| `persistence` | Implemented | SQLAlchemy models + repository interfaces (SQLite) | core |
| `quantum` | Adapter + self-test only | bounded Qiskit/Aer adapter, capability reporting | core (qiskit optional) |
| `science` | **(stub/doc-only)** | general deterministic math/scientific computation | core |
| `optimization` | **(stub/doc-only)** | classical optimization + benchmark definitions | core |
| `identity` | **(doc-only)** | users/roles/tenancy (single-tenant now) | core |
| `retrieval` | **(doc-only, Phase 3)** | lexical/semantic/hybrid retrieval | — |
| `knowledge` | **(doc-only, Phase 3)** | concepts/claims/evidence graph | — |
| `memory` | **(doc-only)** | mission/scientific/procedural memory | — |
| `simulation` | **(doc-only)** | safe scientific/orbital simulation | — |
| `research` | **(doc-only, Phase 7)** | hypotheses/experiments/reviewer gates | — |
| `tool_forge` | **(doc-only, Phase 6)** | generated-tool lifecycle (untrusted) | — |
| `approvals` | **(modeled, governance)** | human review/approval queues | governance |

## Enforcement
- The dependency direction (`api → orchestration → domain → persistence → core`)
  is documented here and reviewed in code review. (An `import-linter` contract is
  a recommended Phase 2 addition.)
- Domain modules MUST NOT import `api`.
- The orbital vertical slice MUST NOT import `quantum` (verified by the absence of
  such imports and by a guard test).
