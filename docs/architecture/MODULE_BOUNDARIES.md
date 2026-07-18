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
| `sources` | Implemented | source registry (offline fixtures) + typed source policy/rights, safe HTTP fetcher, cache/freshness, and the CelesTrak connector (`sources/celestrak/`) behind a generic `OrbitalSource` interface | core, space (elements), persistence (source_repository), httpx |
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
| `mission_windows` | U4.1A offline engine | bounded deterministic Earth-observer geometric windows over pinned orbital elements; no API, persistence, network, optical visibility, or operational claims | observation_geometry, space, governance, core |
| `trajectory_replay` | U4.2B1 offline projection | bounded deterministic geodetic replay samples and dateline-safe track segments over pinned orbital elements; no API, rendering, persistence, or network | observation_geometry, space, governance, core |
| `research` | U4.0B durable structured memory | typed inputs, evidence, gaps, claims, and learning plus an owner-scoped PostgreSQL repository with atomic cycle persistence; no raw evidence vault, API wiring, network adapter, or runtime open-research activation | governance, core |
| `laboratory` | U6 catalog foundation | versioned immutable laboratory manifests, capability declarations (never grants), deterministic in-process registry, built-in Development Laboratory metadata; no execution, plugin loading, persistence, agents, or permission system | core (+ bare `orbitmind` for `__version__`) |
| `authority` | U7.0 pure contracts | strict immutable authority contracts (approval request/decision, scoped expiring capability grants, revocation, evaluation) with deterministic side-effect-free evaluation and stable reason codes; caller-supplied ids/times, no clock, no persistence, no API/UI, no execution surface, delegation prohibited in v1 | core |
| `tool_forge` | **(doc-only, Phase 6)** | generated-tool lifecycle (untrusted) | — |
| `approvals` | **(modeled, governance)** | human review/approval queues | governance |

## Enforcement
- The dependency direction (`api → orchestration → domain → persistence → core`)
  is documented here and reviewed in code review. (An `import-linter` contract is
  a recommended Phase 2 addition.)
- Domain modules MUST NOT import `api`.
- The orbital vertical slice MUST NOT import `quantum` (verified by the absence of
  such imports and by a guard test).
