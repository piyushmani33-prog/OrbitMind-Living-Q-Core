# Solo Alpha Smoke Flow

## Purpose
This is a local solo smoke/sanity flow for one operator to check the current
OrbitMind API behavior. It validates deterministic API behavior that already
exists in this repository.

This checklist is not certification, not approval, not readiness scoring, and
not production authority. It does not validate live provider data, frontend/UI,
rendering, exports, or quantum behavior.

## Preconditions
- Start from a clean git working tree.
- Use the existing `.venv`.
- Expected Alembic head: `m8b9c0d1e2f3`.
- Do not paste secrets, database URLs with real credentials, tokens, or private
  paths into logs or reports.
- The default smoke is local-only and offline.
- Provider/live network behavior is out of scope.
- The PostgreSQL lane requires Docker/PostgreSQL availability.

## Required SQLite Lane
Run this lane for every Solo Alpha local smoke. No Docker is required.

From Command Prompt:

```bat
cd /d E:\quantum-project
git status --short
.venv\Scripts\python.exe -m alembic heads
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000
```

In a second terminal, check the operational endpoints:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
Invoke-RestMethod http://127.0.0.1:8000/version
Invoke-RestMethod http://127.0.0.1:8000/api/v1/system/capabilities
```

Pass criteria:
- `GET /health` returns HTTP 200.
- `database` is `connected`.
- `execution_mode` is `local`.
- `GET /version` returns a version and component versions.
- `GET /api/v1/system/capabilities` returns declared capabilities.

## Deterministic ISS Mission Submission
Submit the canonical deterministic ISS fixture:

```powershell
$mission = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/missions/orbit-propagation `
  -ContentType "application/json" `
  -Body '{
    "satellite_id": "ISS",
    "start_time": "2019-12-09T17:00:00Z",
    "end_time": "2019-12-09T18:00:00Z",
    "step_seconds": 120
  }'

$mission
$missionId = $mission.mission_id
```

This uses bundled sample TLE / test-only data. It is not live tracking, not
provider data, not command readiness, and not approval or certification.

Expected factual output:
- HTTP 201.
- `status = completed`.
- `epistemic_status = deterministic-calculation`.
- `sample_count = 31`.
- `source.test_only = true`.
- `artifacts` include `altitude_vs_time` and `ground_track`.

## Mission Read Checks
Use the `mission_id` from the mission submission.

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/missions/$missionId"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/missions"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/missions/$missionId/artifacts"
```

Pass criteria:
- Retrieve-by-id returns the same `mission_id`.
- Mission list includes the submitted mission.
- Artifact list includes `altitude_vs_time` and `ground_track`.

## Mission Read-Product Checks
These routes are read-only projections over existing persisted mission records.
They do not imply generated graphics, rendering, chart drawing, graph drawing, or
map drawing.

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/visual-manifests/mission/$missionId"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/static-reports/mission/$missionId"
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/map-orbit-contexts/mission/$missionId"
```

Pass criteria:
- Mission visual manifest returns `schema_version = visual-manifest-v1` and the
  same mission scope.
- Mission static report returns `schema_version = static-report-v1` and the same
  mission scope.
- Mission map/orbit context returns `schema_version = map-orbit-context-v1`,
  `context_type = mission-map-orbit-context`, and coordinate payloads excluded by
  design in v1.
- Responses avoid raw paths, raw sidecar JSON, raw coordinates, raw TLEs, and
  provider/live-data claims.

## Product Summary Catalog Check
```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/product-summaries/read-products"
```

Pass criteria:
- Returns `schema_version = product-summary-v1`.
- Returns `summary_type = read-product-catalog`.
- Lists implemented, deferred, and unsupported read-product entries.
- Does not trigger domain data reads.
- Does not imply readiness scoring.
- Does not authorize deferred surfaces.

## Safe Failure Checks
Use only safe, already tested failure paths.

PowerShell may raise an exception for expected 4xx responses. Inspect the body
with `try`/`catch` and `$_.ErrorDetails.Message`, or use PowerShell 7
`Invoke-WebRequest -SkipHttpErrorCheck`.

Unsupported satellite with otherwise valid times:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/missions/orbit-propagation `
  -ContentType "application/json" `
  -Body '{
    "satellite_id": "DOES_NOT_EXIST",
    "start_time": "2019-12-09T17:00:00Z",
    "end_time": "2019-12-09T18:00:00Z",
    "step_seconds": 120
  }'
```

Expected behavior:
- HTTP 422.
- Exact response keys: `code`, `message`.
- `code = validation_error`.
- `message` indicates an unsupported satellite identifier.
- No `Traceback`, SQL, database URL, filesystem path, secret, password, token,
  or internal stack detail.

Unknown mission id:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/missions/11111111-2222-3333-4444-555555555555"
```

Expected behavior: sanitized HTTP 404 with `code = not_found`.

Sanitized response criteria:
- No `Traceback`.
- No SQL.
- No database URL.
- No filesystem path.
- No secret.
- No password.
- No token.
- No internal stack detail.

## Stop Conditions
Stop the smoke flow and investigate if any of these occur:
- Tracked files are dirty before smoke.
- Tracked files are dirty after smoke, unless the only changes are expected
  ignored local DB/log/artifact files.
- Alembic head is not `m8b9c0d1e2f3`.
- Alembic upgrade fails.
- `GET /health` fails.
- Health reports the database is not connected.
- Any unexpected HTTP 500 appears.
- Any error body is not sanitized.
- `sample_count != 31`.
- `epistemic_status != deterministic-calculation`.
- `source.test_only` is missing or false for the ISS fixture.
- `altitude_vs_time` or `ground_track` artifacts are missing.
- An artifact or read-product response leaks a filesystem path or raw internal
  details.
- A response claims live tracking or provider data.
- A response claims command readiness.
- A response claims approval or certification.
- A response claims quantum authority.
- The PostgreSQL lane uses startup `create_all()` semantics as schema
  provisioning.
- The PostgreSQL lane is skipped when release-quality PostgreSQL validation is
  required.

## PostgreSQL Lane
This lane is optional locally, but required for release-quality validation when
Docker/PostgreSQL is available.

Use `127.0.0.1:55432`, not `localhost`. Alembic is the PostgreSQL schema
authority. Run Alembic before app startup. App startup must not be treated as
schema provisioning, and a local skip is not a live PostgreSQL pass.

```bat
docker compose --profile postgres up -d postgres
set ORBITMIND_DATABASE_URL=postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind
.venv\Scripts\python.exe -m alembic upgrade head
```

For test validation:

```bat
set ORBITMIND_TEST_POSTGRES_URL=postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind
.venv\Scripts\python.exe -m pytest -m postgres -v
```

If `ORBITMIND_TEST_POSTGRES_URL` is unset, PostgreSQL tests may skip locally.
Do not report that as a live PostgreSQL pass. Release-quality validation
requires an actual live PostgreSQL run.

## Validation Commands
Use these before and after checklist edits, or as a quick operator reference:

```bat
git status --short
.venv\Scripts\python.exe -m alembic heads
.venv\Scripts\python.exe -m pytest -m postgres --collect-only -q
```

The current postgres-marked collection count is 118. Verify with
`.venv\Scripts\python.exe -m pytest -m postgres --collect-only -q`; do not treat
the number as permanent when future tests are added.

## Explicit Out Of Scope
- Dashboard UI.
- Frontend.
- Rendering.
- Charts.
- Graph drawing.
- Map drawing.
- Surface B.
- Observation-study visual manifest implementation.
- Provider/live-data.
- Live tracking.
- Export/PDF.
- Quantum Studio.
- Quantum implementation.
- New API routes.
- New schemas.
- Migrations.
- Persistence changes.
- Product feature work.
- Automated smoke script.
- Grouped smoke test implementation.
