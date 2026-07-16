# U5.0B1 Windows Packaging Spike

## Status

**IMPLEMENTATION PREPARED - FROZEN BUILD NOT YET AUTHORIZED**

Branch: `phase/u5-0b1-windows-packaging-spike`  
Base: `e22c831bfc6ca0b838e7b092975bdf1c8c80fbda`

This is an internal, non-distributable Windows packaging spike. It is not an
installer, external alpha, updater, service, public runtime, or trust claim.

## Implemented Scope

- A narrow `orbitmind.runtime.launcher` composition root starts the existing
  FastAPI application in one process and one managed Uvicorn thread.
- Source-mode `python -m uvicorn orbitmind.api.app:app` behavior is unchanged.
- Packaged mode uses exact `127.0.0.1`, default port `8000`, no automatic port
  fallback, one worker, no reload, and no forwarded-header trust.
- Writable data is rooted under `%LOCALAPPDATA%\OrbitMind\`; tests inject a
  temporary root and never write to the real profile.
- Packaged mode is SQLite-only. PostgreSQL source/development support remains.
- The launcher uses a SID-qualified named mutex, strict JSON configuration,
  bounded arguments, pre-owned loopback socket, readiness probes, system browser,
  bounded console status, and deterministic exit codes.

## Build Identity

- Lock: `requirements/u5.0b0-windows-py312.lock.txt`
- Lock SHA-256: `785d303155e2ee03915b17d5d5f9a24f009d087465af2b1d9355de2ac0c4102c`
- Target: Windows 10/11 x86-64, CPython 3.12.10
- PyInstaller: 6.21.0, one-folder mode
- pyinstaller-hooks-contrib: 2026.6
- External build environment: approved Python 3.12 environment populated from
  the verified 48-wheel offline closure; no repository-local environment is used.

## Runtime Data and Configuration

The runtime creates only these user-scoped subdirectories:

`config`, `data`, `projects`, `artifacts`, `cache`, `logs`, `runtime`, `backups`,
and `temp`.

`config\config.json` is UTF-8 JSON with `config_schema_version: 1`. Unknown keys,
wrong types, malformed JSON, and unsupported versions fail closed. Precedence is
built-in defaults, user JSON, `ORBITMIND_*` environment values, then the bounded
`--port` and `--no-browser` arguments. Existing `Settings` validation remains the
authority. The config contains no secret or raw TLE field.

## Database Preflight

Workbench readiness is blocked until the approved SQLite database passes a
five-second busy-timeout check, default rollback-journal check, full integrity
check, and Alembic revision inspection. First run migrates a new database to
`n9c0d1e2f3g4`. An older known revision requires console approval and a verified
UTC-named SQLite backup under `backups`. Unknown, missing, newer, or corrupt state
fails closed. There is no destructive repair, silent replacement, downgrade, or
fallback database. Migration failure preserves the database and backup.

## Readiness and Shutdown

The browser opens only after database preflight, a usable `/health` response, and
successful Workbench HTML. `--no-browser` leaves the backend running and prints the
canonical URL. Ctrl-C and supported console-close events set a stop event; the main
thread requests Uvicorn shutdown, waits for FastAPI lifespan cleanup, disposes the
database engine, clears transient handoff state, closes the owned socket, and
releases the mutex. Closing the browser does not stop OrbitMind.

Status states are `starting`, `validating configuration`, `checking database`,
`starting backend`, `ready`, `failed`, `stopping`, and `stopped`. Fixed exit codes
are 0, 10, 20, 21, 30, 31, 40, 50, and 60 as frozen in the kickoff decision.
Console failures expose bounded reason codes, not raw exceptions or request data.

## Packaging Sources

`packaging/orbitmind.spec` is a reviewable one-folder specification with explicit
Alembic, migration, trajectory replay, Matplotlib, SQLite, and Uvicorn inputs. It
excludes psycopg, Qiskit/Aer, tests, user data, artifacts, caches, and secrets.

`scripts/build_windows_poc.ps1` is designed to verify the lock and wheelhouse,
create an external disposable environment, install with `--no-index`,
`--require-hashes`, and `--no-deps`, retain build identity/log evidence, run the
spec only when separately approved, and hash every output.

`scripts/verify_windows_poc.ps1` is designed to use injected LocalAppData, verify
the frozen manifest, exact loopback binding, Workbench and replay assets, a bounded
catalog smoke flow, duplicate launch, port collision, clean shutdown, restart data
survival, and observed process connections. It does not enable handoff or contact
an external origin.

Neither script nor the spec was executed in U5.0B1F.

## Verification Status

- Focused runtime, packaging-source, and Windows loopback integration tests:
  **34 passed**, with 3 third-party deprecation warnings.
- Full serial source suite: **1,494 passed, 262 skipped, 3 warnings in 37:42**.
  The skips are the repository's optional PostgreSQL/quantum environment gates;
  pytest exited successfully. The warnings are existing FastAPI/Starlette and
  Uvicorn/websockets deprecations.
- Ruff check: passed. Ruff format check: 367 files formatted. Strict mypy:
  211 source files passed with the repository's Python 3.12 target.
- Architecture-boundary tests: 3 passed. Active no-network unit gate: 1 passed.
- Alembic: one head, `n9c0d1e2f3g4`.
- CPython 3.12.10 AMD64 source probe: seven runtime modules imported, strict
  configuration resolved, a temporary SQLite database migrated to head, temporary
  files were removable in-process, and the standard-user Windows gate passed.
  The locked environment intentionally contains no mypy/pytest development tools;
  PyInstaller was not invoked.
- Both PowerShell source files passed parser-only syntax validation.
- Frozen build: **NOT RUN**
- Clean-machine execution: **NOT VERIFIED**
- Deterministic frozen scientific parity: **NOT VERIFIED**
- Frozen startup, memory, disk, and shutdown measurements: **NOT VERIFIED**
- Frozen antivirus/SmartScreen result: **NOT VERIFIED**
- External distribution: **BLOCKED**

## Next Gate

The next action requires explicit approval to execute the reviewed offline build
script and PyInstaller spec. That gate must preserve the approved lock and
wheelhouse, produce a one-folder bundle and hashes, and stop before any claim of
clean-machine or external readiness. Public distribution remains separately
blocked by signing, release-integrity, reputation, installation/removal, and
acceptance requirements.
