# Product Requirements — OrbitMind Living Q-Core

Status: Living document · Phase 0/1 scope · Derived from the owner build specification
(the reference vision documents are absent — see RISK R-001).

## 1. Product summary

OrbitMind Living Q-Core is a cloud-first (cloud-portable, locally-run for now),
evidence-grounded **scientific intelligence platform**. It accepts structured
scientific *missions*, executes deterministic computation, preserves provenance,
reports uncertainty, and produces verifiable text, data, and visual artifacts.

The **first bounded production mission** is *Satellite and Earth-orbit scientific
intelligence*: deterministic orbital propagation, verification, evidence-aware
output, persistence, and visualization — with optional bounded quantum
optimization deferred to a later phase.

## 2. What OrbitMind IS (Phase 1 implemented scope)

| ID | Requirement |
|----|-------------|
| PR-01 | Accept a structured orbital mission request via a typed API. |
| PR-02 | Validate inputs (time range, step interval, coordinates, satellite id, output types). |
| PR-03 | Use bundled, deterministic sample TLE data (no network). |
| PR-04 | Propagate a satellite trajectory over a requested UTC time window using SGP4. |
| PR-05 | Compute position (ECI/TEME), velocity, latitude, longitude, altitude with explicit units. |
| PR-06 | Run deterministic verification checks and emit structured findings. |
| PR-07 | Tag every major output with an explicit epistemic status. |
| PR-08 | Persist mission, inputs, samples, findings, provenance, artifacts, and audit events. |
| PR-09 | Generate ≥2 visual artifacts (altitude-vs-time, ground-track) with JSON sidecars. |
| PR-10 | Return a typed API response that carries provenance. |
| PR-11 | Expose stored missions through retrieval endpoints. |
| PR-12 | Pass all automated tests fully offline and reproducibly. |

## 3. What OrbitMind IS NOT (hard product boundaries)

- It does **not** claim to know everything or to be perfectly correct.
- It does **not** autonomously deploy arbitrary or generated code.
- It does **not** bypass source licenses or data-use terms.
- It does **not** perform unrestricted experimentation.
- It does **not** present a generated hypothesis as verified fact.
- It does **not** claim live satellite status from bundled sample data.
- It is **not** a chemistry wet-lab, biological experimentation, financial
  execution, real-world hardware control, or autonomous-publication system.

## 4. Permanent system spine (architectural invariant)

```
User Mission
  → Mission Intake & Validation
  → Prime Orchestrator
  → Domain Workflow
  → Data / Memory / Scientific Tools / Simulation / Quantum Adapter
  → Verification & Evidence Review
  → Structured & Visual Output
  → Memory Update
  → Evaluation
  → Human Approval (when required)
  → Controlled Improvement Proposal
```

Every current and future feature MUST connect to this spine.

## 5. Primary user stories (Phase 1)

- *As a mission owner*, I submit an orbit-propagation mission and receive a typed
  result with positions, altitude, verification findings, and chart artifacts.
- *As a reviewer*, I retrieve a stored mission and inspect its provenance, audit
  trail, and epistemic labels to judge trustworthiness.
- *As an operator*, I check `/health` to confirm app status, DB connectivity,
  execution mode, and quantum availability before running missions.

## 6. Out of scope now / future phases

Real data connectors (Phase 2), scientific memory & retrieval / PostgreSQL +
pgvector (Phase 3), classical+quantum optimization comparison (Phase 4), advanced
visual intelligence (Phase 5), Tool Forge (Phase 6), Research Autopilot (Phase 7),
cloud hardening & multi-tenancy (Phase 8). See `../architecture/ROADMAP.md`.
