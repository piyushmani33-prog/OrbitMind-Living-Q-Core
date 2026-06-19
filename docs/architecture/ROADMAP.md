# Roadmap — OrbitMind Living Q-Core

Phases are gated by owner approval. Each phase keeps the repo runnable and tested.

## Phase 0 — Foundation ✅ (this build)
Repo, tooling, docs, ADRs, FastAPI app, health/version/capabilities, CI scaffold.

## Phase 1 — Orbital vertical slice ✅ (this build)
Deterministic SGP4 propagation from bundled TLE, validation, verification,
epistemic labeling, persistence (SQLite/SQLAlchemy/Alembic), 2 visual artifacts,
provenance, audit, retrieval endpoints — all offline-tested.

## Phase 2 — Real approved data connectors
CelesTrak / NASA Earthdata / NOAA SWPC / SatNOGS. Each connector requires: source
policy, licensing note, rate limits, cache policy, freshness policy, schema
versioning, failure behavior, and **offline test fixtures**. Live calls behind a
connector interface; tests stay offline via fakes.

## Phase 3 — Scientific memory & retrieval
PostgreSQL as system of record; full-text retrieval; optional pgvector; documents,
chunks, concepts, claims, evidence; citation/provenance evaluation.

## Phase 4 — Optimization & bounded quantum comparison
Classical baseline first; a QUBO/graph problem; Qiskit Aer experiment;
reproducible seeds/shots; wall-clock + objective comparison; **no unsupported
quantum-advantage claim**.

## Phase 5 — Advanced visual intelligence
Interactive charts, maps (Leaflet), CesiumJS orbit view, D3 provenance graph,
dashboards & reports.

## Phase 6 — Tool Forge
Manifests, dependency policy, static analysis, test generation, sandbox execution,
quarantine, human approval, rollback. **No generated code executed before this
phase, and never auto-promoted.**

## Phase 7 — Research Autopilot
Research question → evidence search → model selection → simulation → hypothesis →
benchmark → reviewer gate → scientific-memory update.

## Phase 8 — Cloud hardening
PostgreSQL, object storage, managed identity, secrets manager, OpenTelemetry,
metrics/alerts, backups, disaster recovery, tenant isolation, cost controls.
**Cloud deployment always requires separate owner approval.**
