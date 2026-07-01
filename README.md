# OrbitMind Living Q-Core

Evidence-grounded scientific intelligence platform. **Phase 0/1** delivers a
deterministic *satellite / Earth-orbit* vertical slice: submit a structured orbital
mission, propagate a satellite with SGP4 from bundled sample data, verify the
output, persist everything with provenance, and return a typed response plus two
visual artifacts — **fully offline and reproducible**.

> ⚠️ **The bundled TLE data is stale sample data, not live tracking data.** Results
> are a *deterministic calculation*, never a claim about a satellite's current
> position. See [Safety boundaries](#safety-boundaries).

## What OrbitMind is (today)

- A FastAPI **modular monolith** (`src/orbitmind`) with strong internal boundaries.
- An orbital mission pipeline across a permanent spine:
  `Intake → Validation → Orchestrator → Workflow → Propagation → Verification →
  Provenance → Visual Output → Persistence → Audit`.
- Deterministic SGP4 propagation + WGS-84 geodesy, explicit SI/aerospace units,
  timezone-aware UTC throughout.
- Epistemic labeling of every major output and claim-level provenance.
- SQLite system of record (SQLAlchemy + Alembic); PostgreSQL is the production target.

## What OrbitMind is NOT

- Not omniscient, not "always correct", not a source of live satellite status.
- It does not autonomously deploy code, bypass data licenses, run unrestricted
  experiments, or present generated text as verified fact.
- No microservices, no agent swarm, no quantum-on-the-mission-path (quantum is a
  bounded, optional, simulator-only adapter — see ADR-0005).

## Architecture summary

```
api → orchestration → (mission, space, verification, visualization, governance)
                    → persistence (SQLAlchemy/SQLite) → core (config/logging/ids/units)
quantum/  = isolated bounded adapter (NOT on the mission path)
```

See [`docs/architecture/SYSTEM_ARCHITECTURE.md`](docs/architecture/SYSTEM_ARCHITECTURE.md)
and the ADRs under [`docs/architecture/decisions/`](docs/architecture/decisions).

## Installation

Requires Python **3.12+** (production baseline 3.12; this repo was developed and
tested on 3.14.4 — see [ADR-0002](docs/architecture/decisions/ADR-0002-python-version-policy.md)).

```bash
# from the project root, using the existing .venv
.venv\Scripts\python -m pip install -e ".[dev]"   # runtime + dev tools
# optional quantum extra (already present locally):
.venv\Scripts\python -m pip install -e ".[quantum]"
```

### Environment

```bash
cp .env.example .env        # no secrets belong in .env.example
```

All configuration is read only by `orbitmind.core.config.Settings`
(prefix `ORBITMIND_`). Never commit a real `.env`.

## Local execution

```bash
# create the SQLite schema (dev convenience) — or use Alembic (below)
.venv\Scripts\alembic upgrade head

# run the API
.venv\Scripts\python -m uvicorn orbitmind.api.app:app --reload --port 8000
# open http://127.0.0.1:8000/docs  (interactive API)
```

Operational endpoints: `GET /health`, `GET /version`,
`GET /api/v1/system/capabilities`.

## API usage example

Submit an orbit-propagation mission (see
[`docs/development/API_EXAMPLE.md`](docs/development/API_EXAMPLE.md) for the full
request/response):

```bash
curl -s http://127.0.0.1:8000/api/v1/missions/orbit-propagation \
  -H "content-type: application/json" \
  -d '{
        "satellite_id": "ISS",
        "start_time": "2019-12-09T17:00:00Z",
        "end_time": "2019-12-09T18:00:00Z",
        "step_seconds": 120
      }'
```

Returns a typed `MissionDetailResponse` with `status`, `epistemic_status`,
`samples`, `findings`, `provenance`, `artifacts`, `audit`, and a `disclaimer`.
Retrieve later with `GET /api/v1/missions/{mission_id}` and
`GET /api/v1/missions/{mission_id}/artifacts`.

For the completed offline geometry-derived eligibility to provenance-anchored
planning study flow, see
[`docs/development/OBSERVATION_STUDY_API_FLOW.md`](docs/development/OBSERVATION_STUDY_API_FLOW.md).

## Data sources (Phase 2)

Missions default to bundled **sample** data and run fully offline. An optional
**CelesTrak** connector can fetch real General Perturbations (GP/OMM) elements.

### Default offline behavior
Network access is **disabled by default**. The existing sample workflow is
unchanged and needs no network.

### Enabling CelesTrak (local development)
Both switches must be set (a live request needs both):

```bash
ORBITMIND_NETWORK_ENABLED=true
ORBITMIND_CELESTRAK_ENABLED=true
# configurable (verify the endpoint against official CelesTrak docs first):
ORBITMIND_CELESTRAK_BASE_URL=https://celestrak.org/NORAD/elements/gp.php
ORBITMIND_CELESTRAK_CACHE_TTL_SECONDS=7200
# CelesTrak checks for new GP data only every 2h; the policy floors this at 7200s.
ORBITMIND_CELESTRAK_MIN_REFRESH_SECONDS=7200
```

### Sample vs CelesTrak
- `"source": "sample"` (default) — bundled, stale, test-only TLE (offline).
- `"source": "celestrak"` — real GP data; `satellite_id` is a NORAD number (e.g.
  `"25544"`). Requires the switches above.
- **No silent fallback:** if CelesTrak is unavailable the mission fails safely.
  Opt in with `"allow_sample_fallback": true` to fall back to the sample — the
  result is then explicitly labelled `source=sample`, `freshness=test-fixture`.

### Freshness meanings
`test-fixture · current · fresh · aging · stale · expired · unavailable · invalid`.
Stale/expired data is **never** reported as live. Every external mission result
carries a `source_data` block (source, record id, data epoch, fetch time, cache
status, freshness, policy version, checksum, limitations).

### Cache behavior
Raw payloads are cached under `cache/<source_id>/` (gitignored); metadata lives in
the DB. Reads are cache-first within the TTL; refreshes respect a minimum interval
and an in-process lock (no Redis, no background polling). See
[CACHE_AND_FRESHNESS.md](docs/operations/CACHE_AND_FRESHNESS.md) and
[SOURCE_OPERATIONS.md](docs/operations/SOURCE_OPERATIONS.md).

### Source endpoints (local-dev-only; no auth yet)
`GET /api/v1/sources`, `/{id}`, `/{id}/policy`, `/{id}/health`, `/{id}/cache`,
and `POST /{id}/refresh?satellite_id=<norad>`.

### Data limitations & rights
CelesTrak licensing/commercial-use terms are **not confirmed** in this repo and are
labelled *requires review*; attribution to CelesTrak is recorded. See
[DATA_RIGHTS_AND_SOURCE_POLICY.md](docs/architecture/DATA_RIGHTS_AND_SOURCE_POLICY.md).

## Small-body intelligence (Phase 3A)

OrbitMind models **space objects of many kinds without treating them all as
satellites** (ADR-0013/0016): satellites/debris use TLE/GP + SGP4, while **asteroids and
comets use heliocentric small-body models — never SGP4**. Phase 3A adds asteroid/comet
intelligence from official **NASA/JPL** APIs (SBDB lookup, SBDB query, CAD), behind the
same guarded-connector pattern (network off by default).

### Endpoints
`GET /api/v1/space-objects[/{id}]`, `POST /api/v1/small-bodies/lookup|query|close-approaches`,
`GET /api/v1/small-bodies/{id}[/close-approaches]`.

### Enabling JPL (local development)
```bash
ORBITMIND_NETWORK_ENABLED=true
ORBITMIND_JPL_SBDB_ENABLED=true   # lookup + constrained query
ORBITMIND_JPL_CAD_ENABLED=true    # close-approach data
```

### Example
```bash
curl -s http://127.0.0.1:8000/api/v1/small-bodies/lookup \
  -H "content-type: application/json" -d '{"identifier": "433"}'
```

### What it is / isn't
Identifies catalogued asteroids/comets and their **source-reported** orbits, physical
estimates, classifications, and close approaches. It does **not** observe directly,
propagate high-fidelity ephemerides (Horizons deferred), or compute impact probability.
A **close approach is NOT an impact**; NEO/PHA hazard flags are **source-reported, not
computed**. JPL data rights are labelled *requires review*. See
[SMALL_BODY_INTELLIGENCE.md](docs/architecture/SMALL_BODY_INTELLIGENCE.md),
[UNIFIED_SPACE_OBJECT_MODEL.md](docs/architecture/UNIFIED_SPACE_OBJECT_MODEL.md), and
[JPL_SOURCE_OPERATIONS.md](docs/operations/JPL_SOURCE_OPERATIONS.md).

## Scientific memory (Phase 3B)

Durable, queryable memory for scientific documents, concepts, claims, evidence,
citations, lightweight graph relations, and **deterministic retrieval**. **Memory is
not truth and retrieval is not verification**: outputs are ranked, version-pinned
**evidence passages — never a generated answer** (answer synthesis is deferred).

- **PostgreSQL** is the production system-of-record; **SQLite** remains the default for
  fast offline tests (ADR-0018/0023). Only `ORBITMIND_DATABASE_URL` changes between them.
- Allowlisted, secret-rejecting, deterministic ingestion (no execution, no network);
  content-checksum dedup + immutable versioning; reproducible structure-aware chunking.
- Retrieval: PostgreSQL full-text (GIN `tsvector`) candidate selection with an explicit,
  identical ranking formula on both dialects; SQLite uses a labelled deterministic
  lexical fallback (ADR-0021). Embeddings/`pgvector` are **optional and disabled by
  default** (ADR-0022).
- **Validated on real PostgreSQL 16.13 / psycopg 3.3.4 (2026-06-20):** fresh-DB migration
  to head, FTS GIN index verified, 13 live `postgres` integration tests, gold eval
  recall@5 = 1.0, `pg_dump`/`pg_restore` smoke test, and a CI service-container job. To
  exercise it locally: `docker compose --profile postgres up -d postgres` (host port **55432**;
  use `127.0.0.1` on Windows, not `localhost`).

### Endpoints
`POST /api/v1/memory/ingestion-runs`, `GET /api/v1/memory/ingestion-runs/{id}`,
`GET /api/v1/memory/documents[/{id}][/chunks]`, `POST /api/v1/memory/search`,
`POST|GET /api/v1/memory/concepts[/{id}]`, `POST|GET /api/v1/memory/claims[/{id}]`,
`POST /api/v1/memory/evidence`, `GET /api/v1/memory/graph/{entity_id}/neighbors`,
`POST /api/v1/memory/evaluations`.

See [SCIENTIFIC_MEMORY.md](docs/architecture/SCIENTIFIC_MEMORY.md),
[CLAIMS_AND_EVIDENCE.md](docs/architecture/CLAIMS_AND_EVIDENCE.md),
[DETERMINISTIC_RETRIEVAL.md](docs/architecture/DETERMINISTIC_RETRIEVAL.md),
[POSTGRESQL_ARCHITECTURE.md](docs/architecture/POSTGRESQL_ARCHITECTURE.md), and
[POSTGRESQL_LOCAL_OPERATIONS.md](docs/operations/POSTGRESQL_LOCAL_OPERATIONS.md).

## Bounded quantum optimization (Phase 4A)

One **bounded, scientifically honest** experiment: satellite observation scheduling solved
by deterministic classical baselines (exact + greedy) and a **simulator-only** QAOA, on the
**same normalized instance**. The quantum layer is an **experimental adapter, NOT** the
cognition engine; **general quantum advantage is never claimed** and an experimental result
never controls a production mission.

- **Mandatory classical baselines**; every schedule is independently re-verified by a shared
  deterministic evaluator (a solver's own claim is never trusted).
- **Manual QUBO** (no `qiskit-optimization`); `QUBO energy == −penalized_objective` is
  **exhaustively verified** on tiny instances.
- **Aer simulator only** — no real hardware, no IBM account, no API key, no network; fixed
  seeds, bounded shots/iterations/timeout, full circuit metadata. Quantum is disabled with a
  clear `unsupported` response when Aer is absent.
- Policy-driven conclusions (`quantum-competitive` / `quantum-worse` / `quantum-infeasible` /
  `equivalent-objective` / `insufficient-evidence` / `experiment-failed` / `classical-*-best`);
  `quantum-competitive` means only that a bounded threshold was met — **not advantage**.

### Endpoints
`POST|GET /api/v1/optimization/problems[/{id}]`,
`POST /api/v1/optimization/problems/{id}/solve/{classical|quantum}`,
`POST /api/v1/optimization/problems/{id}/benchmark`,
`GET /api/v1/optimization/runs[/{id}][/artifacts]`.

See [QUANTUM_OPTIMIZATION_BOUNDARY.md](docs/architecture/QUANTUM_OPTIMIZATION_BOUNDARY.md),
[SATELLITE_OBSERVATION_SCHEDULING.md](docs/architecture/SATELLITE_OBSERVATION_SCHEDULING.md),
[QUBO_ENCODING.md](docs/architecture/QUBO_ENCODING.md),
[QUANTUM_BENCHMARK_POLICY.md](docs/architecture/QUANTUM_BENCHMARK_POLICY.md), and
[OPTIMIZATION_BENCHMARKS.md](docs/operations/OPTIMIZATION_BENCHMARKS.md).

## Testing

```bash
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy src
.venv\Scripts\python -m pytest --cov=orbitmind --cov-report=term-missing
```

All tests run **offline** (no network, no external DB, temp dirs/DBs, fixed seeds).

## Project structure

```
src/orbitmind/        modular monolith (api, core, mission, orchestration,
                      persistence, sources, space, verification, visualization,
                      governance, observability, quantum)
tests/                unit + integration (offline)
docs/                 requirements, architecture, ADRs, development, reference
data/samples/         bundled, checksummed, test-only TLE fixtures
migrations/           Alembic migrations
experiments/quantum/  isolated Bell-state smoke experiment (not production)
artifacts/            generated mission artifacts (gitignored)
```

## Generated artifacts

Each mission writes to `artifacts/<mission_id>/`:
`altitude_vs_time.png`, `ground_track.png`, and a `.json` sidecar per image
(type, timestamp, source references, computation + software versions, verification
status, checksum). Binary images are never stored in the database.

## Known limitations

- TLEs are bundled **sample** data (not live); SGP4 accuracy degrades far from the
  element-set epoch.
- TEME→geodetic uses GMST rotation only (no polar motion/nutation); good for
  demonstration ground tracks, not sub-km frame precision.
- Single-user / single-tenant; no auth yet (interfaces designed for it). The source
  endpoints (incl. refresh) are local-development-only.
- In-process synchronous workflow (no durable/long-running workflows yet).
- CelesTrak endpoint/format/cadence are verified against official docs (R-012a
  closed; `docs/architecture/CELESTRAK_VERIFICATION.md`); its **legal/commercial-use
  rights remain unconfirmed** (R-012b open) and are labelled "requires review".
  Alpha-5 (alphanumeric) catalogue ids are not yet supported (numeric only, R-016).

## Roadmap

Phase 2 real connectors → Phase 3A small-body intelligence → Phase 3B scientific
memory + deterministic retrieval (PostgreSQL) → **Phase 4A bounded classical-vs-quantum
(Aer) scheduling benchmark** → Phase 4B+ optimization → Phase 5 advanced visuals →
Phase 6 Tool Forge → Phase 7 Research Autopilot → Phase 8 cloud hardening.
See [`docs/architecture/ROADMAP.md`](docs/architecture/ROADMAP.md).

## Safety boundaries

- Sample TLE data is **not** live satellite data (SR-05).
- Deterministic tools (not an LLM) perform all calculations (SR-01).
- Every output is labeled `verified-fact | deterministic-calculation |
  model-estimate | hypothesis | assumption | unknown | rejected` (ADR-0006).
- Artifacts are written only under the configured artifacts directory; path
  traversal is rejected (SR-13).
- Network is disabled by default; a live CelesTrak request needs two explicit
  switches, is HTTPS-only + host-allowlisted, and never happens during startup,
  `/health`, or tests (ADR-0009).
- No secrets in code/VCS; no hidden network calls; generated code is never executed
  or auto-deployed. Full list in
  [`docs/requirements/SAFETY_REQUIREMENTS.md`](docs/requirements/SAFETY_REQUIREMENTS.md).
