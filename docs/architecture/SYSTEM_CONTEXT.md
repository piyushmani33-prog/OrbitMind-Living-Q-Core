# System Context — OrbitMind Living Q-Core

## Purpose
Describe the system boundary, actors, and external interfaces at Phase 0/1.

## Actors
- **Mission Owner** — submits structured orbital missions, reviews results.
- **Reviewer** — inspects provenance, verification, epistemic labels, audit trail.
- **Operator** — checks health/capabilities, runs the local service.
- **(Future) Approver** — grants human approval for risky actions.

## System (in scope now)
A single FastAPI **modular monolith** (`orbitmind`) exposing a versioned HTTP API,
backed by a local SQLite database via SQLAlchemy, writing visual artifacts to a
controlled local directory.

## External dependencies
| Dependency | Phase 0/1 status |
|------------|------------------|
| SGP4 library | Used (bundled algorithm; offline). |
| Sample TLE fixtures | Bundled under `data/samples` (offline, test-only). |
| Qiskit / Aer | Optional, isolated adapter + self-test only; not on mission path. |
| Network / live APIs | **None.** No outbound calls. |
| PostgreSQL / Redis / Temporal | **Not used.** Production targets, deferred. |
| Cloud services | **None.** Cloud-portable design only. |

## Context diagram (textual)
```
            ┌──────────────┐      HTTP/JSON       ┌──────────────────────────┐
 Owner ─────▶  Client/curl  ├─────────────────────▶   OrbitMind monolith      │
 Reviewer ──▶  / Swagger UI │                      │  (FastAPI + workflow)     │
 Operator ──▶              │◀─────────────────────┤                          │
            └──────────────┘     typed result      │  ┌────────────────────┐  │
                                                    │  │ SQLite (SQLAlchemy)│  │
                                                    │  └────────────────────┘  │
                                                    │  ┌────────────────────┐  │
                                                    │  │ artifacts/<id>/...  │  │
                                                    │  └────────────────────┘  │
                                                    │  ┌────────────────────┐  │
                                                    │  │ Qiskit adapter (opt)│  │
                                                    │  └────────────────────┘  │
                                                    └──────────────────────────┘
```

## Trust boundaries
- All HTTP input is untrusted → validated by Pydantic + domain validators.
- The filesystem write surface is restricted to the artifacts directory.
- The quantum adapter is isolated and never triggered by ordinary API requests.
