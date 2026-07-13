# Operations Runbook — OrbitMind Solo Alpha (local)

OrbitMind Solo Alpha runs locally on one Windows machine with SQLite and no external
services by default. This runbook is the authoritative operator path for the
server-rendered Workbench and the optional local custom-TLE transient replay handoff.
Cloud/DR hardening, authentication, authorization, complete public CSRF protection,
reverse-proxy support, multi-worker support, and public deployment remain deferred.

The product is deterministic predicted geometry, not live tracking. It is local Solo
Alpha software, not a public hosted service.

## Workbench Entry Point

Use the canonical loopback origin exactly:

```text
http://127.0.0.1:8000/workbench
```

Do not replace `127.0.0.1` with `localhost`, `::1`, `0.0.0.0`, another IPv4
spelling, or a proxy URL. The custom-TLE handoff accepts only the configured
canonical loopback host and port.

## Approved Default Mode

The default mode is the simplest approved operator path. The custom-TLE transient
replay handoff is disabled by default. Catalog mission-window and replay paths work;
custom-TLE mission-window calculation works; a custom result honestly says that its
transient replay handoff is unavailable. No catalog or ISS fallback is used.

### Windows Command Prompt

Run these commands in a project-local Command Prompt. `set` affects this window only:

```bat
cd /d E:\quantum-project
.venv\Scripts\python.exe -m alembic upgrade head
set ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED=false
set ORBITMIND_NETWORK_ENABLED=false
set ORBITMIND_CELESTRAK_ENABLED=false
.venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000
```

### PowerShell

These assignments affect the current PowerShell window only:

```powershell
$env:ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED="false"
$env:ORBITMIND_NETWORK_ENABLED="false"
$env:ORBITMIND_CELESTRAK_ENABLED="false"
& .venv\Scripts\python.exe -m alembic upgrade head
& .venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/workbench`. Stop the server with `Ctrl-C` in the
server window. No provider credential is required and no external network call is
part of this mode.

## Advanced Local Mode: Custom-TLE Transient Handoff

This mode is for informed Solo Alpha operators testing request-local custom-TLE replay.
It remains disabled by default and is supported only when every condition below is true:

- `ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED=true` explicitly enables the feature;
- `ORBITMIND_CUSTOM_TLE_HANDOFF_PORT` equals the Uvicorn application port;
- `ORBITMIND_API_BIND_HOST` is exactly `127.0.0.1`;
- `ORBITMIND_API_WORKERS` is exactly `1`;
- `ORBITMIND_API_RELOAD_ENABLED=false`;
- `ORBITMIND_FORWARDED_HEADER_TRUST_ENABLED=false`;
- the Uvicorn command binds to `127.0.0.1` and does not use `--reload` or `--workers`;
- the browser uses the direct canonical loopback URL; and
- the process is used locally as one application process, without a reverse proxy.

The handoff stores validated custom-TLE replay state only in bounded process memory. It
is temporary, single-use, cleared on shutdown/restart, and does not durably persist raw
TLE text in the database, artifacts, cache, browser storage, cookies, URLs, or logs.
It is not authentication, authorization, or a complete public CSRF solution.

### Enabled Windows Command Prompt

```bat
cd /d E:\quantum-project
set ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED=true
set ORBITMIND_CUSTOM_TLE_HANDOFF_PORT=8000
set ORBITMIND_API_BIND_HOST=127.0.0.1
set ORBITMIND_API_WORKERS=1
set ORBITMIND_API_RELOAD_ENABLED=false
set ORBITMIND_FORWARDED_HEADER_TRUST_ENABLED=false
set ORBITMIND_NETWORK_ENABLED=false
set ORBITMIND_CELESTRAK_ENABLED=false
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000
```

### Enabled PowerShell

```powershell
$env:ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED="true"
$env:ORBITMIND_CUSTOM_TLE_HANDOFF_PORT="8000"
$env:ORBITMIND_API_BIND_HOST="127.0.0.1"
$env:ORBITMIND_API_WORKERS="1"
$env:ORBITMIND_API_RELOAD_ENABLED="false"
$env:ORBITMIND_FORWARDED_HEADER_TRUST_ENABLED="false"
$env:ORBITMIND_NETWORK_ENABLED="false"
$env:ORBITMIND_CELESTRAK_ENABLED="false"
& .venv\Scripts\python.exe -m alembic upgrade head
& .venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000
```

Open only `http://127.0.0.1:8000/workbench`. Do not add Uvicorn `--reload` or
`--workers` flags. The command uses one default Uvicorn worker, while the application
settings independently enforce the one-process handoff boundary.

Invalid enabled-mode settings fail startup rather than enabling partial behavior.
Unsupported enabled-mode configurations include `localhost`, `::1`, `0.0.0.0`,
alternate IPv4 spellings, multiple workers, reload, reverse proxies, trusted forwarded
headers, public access, and any non-loopback host.

## Workbench Flow and Safety Boundary

1. Open the Workbench URL above.
2. Choose exactly one bounded offline catalog source or custom offline TLE source.
3. Enter the observer coordinates, explicit UTC start, duration, and elevation threshold.
4. Choose **Calculate Mission Windows** or **Replay Predicted Trajectory**.
5. With enabled custom handoff, a successful custom-TLE mission result may offer a
   temporary **Replay this request** action. It reuses the exact validated source,
   observer, and interval once; it is not live tracking.
6. A missing, expired, consumed, owner-mismatched, or restart-lost handoff fails closed
   with HTTP 410 and no source fallback.

All results are deterministic predictions from the supplied offline orbital source.
The Workbench does not provide optical visibility, current-state truth, command readiness,
collision analysis, or safety certification.

## Storage and Schema Behavior

For SQLite/local development, startup may create missing ORM tables as a
convenience. For PostgreSQL, Alembic is the schema authority: run
`alembic upgrade head` before app startup. PostgreSQL startup does not bootstrap
schema via ORM `create_all()`, though it still records the source catalog once
the migrated schema is present.

## Health checks
- `GET /health` — status, version, Python, DB connectivity, execution mode, quantum.
- `GET /version` — component versions.
- `GET /api/v1/system/capabilities` — declared capabilities + availability.

For a bounded one-person local smoke checklist, see
[`docs/operations/SOLO_ALPHA_SMOKE_FLOW.md`](SOLO_ALPHA_SMOKE_FLOW.md).
For the factual closure record of the completed SQLite and PostgreSQL Solo
Alpha smoke runs, see
[`docs/operations/SOLO_ALPHA_RESULTS_CLOSURE.md`](SOLO_ALPHA_RESULTS_CLOSURE.md).
For the first trusted operator boundary, see
[`docs/operations/FIRST_TRUSTED_OPERATOR_BOUNDARY.md`](FIRST_TRUSTED_OPERATOR_BOUNDARY.md).

For the read-only offline observation study API flow that links persisted
geometry-derived eligibility to provenance-anchored planning records, see
[`docs/development/OBSERVATION_STUDY_API_FLOW.md`](../development/OBSERVATION_STUDY_API_FLOW.md).

A non-200 or `"database":"unavailable"` indicates the SQLite file/path is missing
or unwritable — check `ORBITMIND_DATABASE_URL` and the `data/` directory.

## Troubleshooting

| Symptom | Interpretation and correction |
| --- | --- |
| Startup rejects the worker count | When enabled, set `ORBITMIND_API_WORKERS=1` and do not pass Uvicorn `--workers`. |
| Startup rejects reload | Set `ORBITMIND_API_RELOAD_ENABLED=false` and remove Uvicorn `--reload`. Reload invalidates process-local handoffs. |
| Startup rejects the bind host | Set `ORBITMIND_API_BIND_HOST=127.0.0.1` and bind Uvicorn with `--host 127.0.0.1`. |
| Browser opened `localhost` | Close it and open `http://127.0.0.1:8000/workbench`; `localhost` is not an enabled-handoff alias. |
| Wrong port or handoff port | Keep `ORBITMIND_CUSTOM_TLE_HANDOFF_PORT` and the Uvicorn port identical, normally `8000`. |
| Proxy/forwarded trust is enabled | Set `ORBITMIND_FORWARDED_HEADER_TRUST_ENABLED=false`; reverse-proxy mode is unsupported. |
| Custom replay handoff is unavailable | The feature is probably disabled. Custom-TLE calculation still works without replay; enable advanced mode only within this runbook’s boundary. |
| Handoff returns HTTP 410 | The identifier is missing, expired, already consumed, owner-mismatched, or lost on restart. Submit a new custom-TLE request; no fallback is performed. |
| `/health` reports database unavailable | Check `ORBITMIND_DATABASE_URL`, the local `data` directory, and that PostgreSQL migrations were run before a PostgreSQL-backed startup. |

## Data locations
- Database: `./data/orbitmind.db` (gitignored).
- Artifacts: `./artifacts/<mission_id>/` (gitignored).

## Backup / restore (local)
- Backup: copy `data/orbitmind.db` and the `artifacts/` tree.
- Restore: stop the app, replace the files, restart.
- Missions are reproducible from inputs (deterministic), so artifacts can also be
  regenerated by re-submitting the recorded request.

## Rollback
- Code/docs: `git revert` / checkout a previous commit (no broken intermediate
  states are committed).
- Schema: `alembic downgrade -1` (migrations are reversible).

## Logs
Structured key/value logs to stdout (`ORBITMIND_LOG_JSON=true` for JSON). Mission
logs carry `mission_id`. The per-mission `audit_events` table is the durable record
of lifecycle transitions.

## Incident notes
- No secrets or network egress exist in this phase, limiting blast radius.
- If a mission fails, it is persisted with status `failed` plus `mission.failed` /
  `propagation.failed` audit events — inspect via `GET /api/v1/missions/{id}`.

## Related Documentation

- [Offline Mission Workbench](../product/OFFLINE_MISSION_WORKBENCH.md)
- [Animated Trajectory Replay](../product/ANIMATED_TRAJECTORY_REPLAY.md)
- [Custom-TLE transient handoff architecture](../architecture/CUSTOM_TLE_TRANSIENT_HANDOFF_ARCHITECTURE.md)
- [Browser security baseline](../security/BROWSER_SECURITY_BASELINE.md)
- [Solo Alpha smoke flow](SOLO_ALPHA_SMOKE_FLOW.md)
