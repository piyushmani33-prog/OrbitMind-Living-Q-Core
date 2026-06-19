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
- Single-user / single-tenant; no auth yet (interfaces designed for it).
- In-process synchronous workflow (no durable/long-running workflows yet).

## Roadmap

Phase 2 real connectors → Phase 3 memory/retrieval (PostgreSQL/pgvector) →
Phase 4 bounded quantum-vs-classical optimization → Phase 5 advanced visuals →
Phase 6 Tool Forge → Phase 7 Research Autopilot → Phase 8 cloud hardening.
See [`docs/architecture/ROADMAP.md`](docs/architecture/ROADMAP.md).

## Safety boundaries

- Sample TLE data is **not** live satellite data (SR-05).
- Deterministic tools (not an LLM) perform all calculations (SR-01).
- Every output is labeled `verified-fact | deterministic-calculation |
  model-estimate | hypothesis | assumption | unknown | rejected` (ADR-0006).
- Artifacts are written only under the configured artifacts directory; path
  traversal is rejected (SR-13).
- No secrets in code/VCS; no hidden network calls; generated code is never executed
  or auto-deployed. Full list in
  [`docs/requirements/SAFETY_REQUIREMENTS.md`](docs/requirements/SAFETY_REQUIREMENTS.md).
