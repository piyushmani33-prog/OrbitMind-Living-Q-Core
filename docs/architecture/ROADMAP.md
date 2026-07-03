# Roadmap — OrbitMind Living Q-Core

Phases are gated by owner approval. Each phase keeps the repo runnable and tested.

> Reconciled with the reference documents (2026-06-19): this phasing aligns with the
> Vision document's own 12–18 month plan (Foundations → Mission spine → Scientific
> memory → Satellite intelligence → Quantum Organ → Tool Forge → Visual Intelligence
> → Research Autopilot → Hardening). See `REFERENCE_RECONCILIATION.md`.

## Phase 0 — Foundation ✅ (this build)
Repo, tooling, docs, ADRs, FastAPI app, health/version/capabilities, CI scaffold.

## Phase 1 — Orbital vertical slice ✅ (this build)
Deterministic SGP4 propagation from bundled TLE, validation, verification,
epistemic labeling, persistence (SQLite/SQLAlchemy/Alembic), 2 visual artifacts,
provenance, audit, retrieval endpoints — all offline-tested.

## Phase 2 — Real approved data connectors
**CelesTrak GP connector implemented ✅** behind a generic `OrbitalSource` interface:
source policy + rights metadata, configurable endpoint, network-disabled-by-default
(two switches), HTTPS-only + host allowlist, bounded retries/size/timeouts, GP/OMM
JSON schema validation, normalization to the unchanged SGP4 path, DB-metadata + file
cache, freshness classification, minimum-refresh discipline, source/health/cache/
refresh API, full audit, and offline mocked tests. Source data flows into mission
results with explicit freshness/limitations and **no silent fallback**.

NASA Earthdata / NOAA SWPC / SatNOGS / Space-Track remain **future** connectors,
each to follow the same pattern (`docs/development/ADDING_A_SOURCE_CONNECTOR.md`):
source policy, licensing note, rate/cache/freshness policy, schema versioning,
failure behavior, and **offline test fixtures**.

## Phase 3 — split into 3A and 3B (re-sequenced; ADR-0012)
The owner prioritized natural-space-object intelligence ahead of broad scientific
memory. The original Phase 3 (scientific memory + PostgreSQL) is **not cancelled** —
it becomes Phase 3B.

### Phase 3A — Unified space-object model & JPL small-body intelligence ✅ (this build)
A kind-agnostic `SpaceObject` model (satellites/asteroids/comets/planets/stars/signals
kept scientifically separate; ADR-0013/0016); guarded JPL connectors (SBDB lookup, SBDB
query, CAD) behind the Phase 2 source pattern (network off by default); small-body
normalization, deterministic verification, persistence (additive tables), bounded
visual artifacts (model-estimate; ADR-0017), full provenance/freshness/audit. Asteroids
and comets use heliocentric models — **never SGP4**. SQLite remains the store for this
bounded phase.

### Phase 3B — Scientific memory & PostgreSQL foundation ✅ (this build)
PostgreSQL as production system-of-record (SQLite retained for offline tests; ADR-0018);
deterministic allowlisted ingestion with dedup + versioning; reproducible structure-aware
chunking; concepts/terminology; typed claims + evidence + version-pinned citations
(ADR-0020); a lightweight relational knowledge graph (bounded, cycle-safe); deterministic
retrieval — PostgreSQL full-text candidate selection with an explicit ranking formula,
SQLite labelled lexical fallback (ADR-0021); offline gold retrieval evaluation; memory
APIs. Embeddings/pgvector are **optional and disabled by default** (ADR-0022). **No
generative answer synthesis, no LLM, no network.** The Phase 3A object model is the entity
foundation the knowledge graph indexes. See
[SCIENTIFIC_MEMORY.md](SCIENTIFIC_MEMORY.md).

**PostgreSQL closure (validated 2026-06-20):** exercised against real PostgreSQL 16.13
(psycopg 3.3.4) — fresh-DB migration to head, FTS GIN index verified (query plan inspected),
13 live `postgres` integration tests green, gold evaluation recall@5 = 1.0, `pg_dump`/
`pg_restore` smoke test, and a CI `postgres-integration` service-container job. A real
FK-ordering defect masked by SQLite was found and fixed. SQLite remains the default for
offline tests. Phase 3B is **formally complete**. See
[POSTGRESQL_LOCAL_OPERATIONS.md](../operations/POSTGRESQL_LOCAL_OPERATIONS.md).

### Later Phase-3 family work (planned, deferred)
JPL Horizons live ephemerides; planetary/lunar ephemerides; debris collision risk;
space-weather ingestion (NOAA SWPC); astronomy catalogues (stars/galaxies); radio-signal
and spectral analysis; Sentry/Scout impact-risk; Minor Planet Center / ESA NEOCC.

## Phase 4 — Optimization & bounded quantum comparison

### Phase 4A — Satellite observation scheduling benchmark ✅ (this build)
Bounded satellite observation scheduling: mandatory deterministic classical baselines
(exact exhaustive ground truth + greedy heuristic) and a **simulator-only** QAOA on the
**same normalized instance**. Manual QUBO with `QUBO energy == −penalized_objective`
**exhaustively verified**; Aer-only with fixed seeds/bounded shots/iterations/timeout and
full circuit metadata; every schedule independently re-verified; policy-driven comparison
conclusions; bounded scientific-memory entity links; visual artifacts + sidecars.
**No quantum-advantage claim; quantum never controls a production mission** (ADR-0024–0029).
See [QUANTUM_OPTIMIZATION_BOUNDARY.md](QUANTUM_OPTIMIZATION_BOUNDARY.md).

### Phase 4B–4F — Offline observation study chain (complete)
Bounded observation planning, deterministic offline observation geometry with persistence
and APIs, geometry-derived eligibility, provenance-anchored planning compatibility,
read-only study-chain APIs, observation study documentation with executable contract
examples, query-only chain integrity summaries, read-only integrity-summary APIs, and
optional integrity-summary documentation are complete. These provide read-only
traceability over pinned/offline model-derived records and read-time record consistency
only, without live tracking, operational access, taskability, command readiness, approval,
signed receipt claims, or quantum authority. See
[OBSERVATION_STUDY_API_FLOW.md](../development/OBSERVATION_STUDY_API_FLOW.md).

### Further optimization (planned / deferred)
Larger instances / additional solvers, still classical-baseline-first and bounded.

## Phase 5 — Advanced visual intelligence
Phase 5.1–5.9 closes the initial visual manifest family: the
visual-intelligence boundary, visual manifest specification, visual manifest API
contract, mission-only read-only visual manifest API, optimization-benchmark
read-only visual manifest API, guard coverage, and closure documentation are
complete. See [VISUAL_INTELLIGENCE_BOUNDARY.md](VISUAL_INTELLIGENCE_BOUNDARY.md).
The [static report specification](STATIC_REPORT_SPECIFICATION.md) is a
gate for future report work; mission static report v1 is implemented, while
other report domains, rendering, export, frontend, and provider/live-data work
remain deferred.
The [provenance/study graph semantics](PROVENANCE_STUDY_GRAPH_SEMANTICS.md)
specification is a docs-only gate; graph rendering, D3, and frontend remain
deferred.
The [map/orbit view specification](MAP_ORBIT_VIEW_SPECIFICATION.md) is a
docs-only gate; map/orbit rendering, Leaflet, CesiumJS, and frontend remain
deferred.
The [dashboard view specification](DASHBOARD_VIEW_SPECIFICATION.md) is a
docs-only gate; dashboard UI, charts, widgets, rendering, and frontend remain
deferred.
The [Phase 5 visual-planning closure audit](PHASE_5_VISUAL_PLANNING_CLOSURE_AUDIT.md)
closes the planning layer only; it authorizes no implementation surfaces.

Additional visual manifest domains (observation study, integrity, memory),
interactive charts, maps (Leaflet), CesiumJS orbit view, D3 provenance graph,
dashboards, reports, rendering/export, live data/provider behavior, frontend,
and Quantum Studio remain deferred.

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
