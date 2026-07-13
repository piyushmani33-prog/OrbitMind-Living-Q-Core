# Windows Packaging Kickoff Decisions

## Status

This is the U5.0B0 documentation-only decision record. It closes the design choices
required before packaging implementation. It does not create PyInstaller files,
dependencies, a launcher, an installer, or production-source changes.

**Decision: APPROVE BOUNDED U5.0B PACKAGING SPIKE**

The approval is limited to a local, non-distributable Windows packaging spike. U5.0B
may build and test an unsigned PyInstaller one-folder bundle in an isolated internal
environment. It is not an external alpha, public release, signed installer, updater,
supported distribution channel, or public deployment approval. External distribution
remains blocked.

This kickoff approval is not an exit claim. U5.0B must still produce and review
clean-machine, scientific/security parity, resource, shutdown, antivirus, rollback,
and data-preservation evidence before the spike can be accepted.

See [LOCAL_RUNTIME_ARCHITECTURE.md](LOCAL_RUNTIME_ARCHITECTURE.md).

## Scope and Non-Goals

U5.0B is the smallest proof that the verified Python/FastAPI Solo Alpha can be
reproducibly bundled for one Windows user without changing scientific authority,
offline behavior, provenance, or browser security. It covers build inputs, a future
thin launcher/bootstrap, lifecycle, user-scoped data paths, and evidence collection.

It does not add Tauri, Electron, a Rust rewrite, a cloud control plane, accounts,
public hosting, camera, microphone, 3D, Visual Universe, agents, Laboratory, Quantum
Studio, quantum mission behavior, a service, tray behavior, an updater, an installer,
or a second scientific authority. No new database schema or durable transient-handoff
state is authorized.

## Repository Facts Used

| Area | Current fact | Packaging consequence |
| --- | --- | --- |
| Python | pyproject.toml requires Python >=3.12; CI runs Python 3.12; development is Python 3.14.3 | Build/parity evidence uses Python 3.12.x |
| API | orbitmind.api.app:app is the module-level FastAPI application | Start this existing application |
| Server | Uvicorn serves one process, normally on 127.0.0.1:8000 | No public bind, worker process, or automatic port fallback |
| Storage | SQLite is default; PostgreSQL is optional source/development support | First frozen PoC is SQLite-only |
| Migrations | alembic.ini, migrations/env.py, migrations/script.py.mako, and migrations/versions/ are tracked | Check schema compatibility before readiness |
| Asset | src/orbitmind/api/assets/trajectory_replay.js is loaded through importlib.resources; package data declares api/assets/*.js | Preserve package-resource loading and verify frozen bytes |
| HTML | Workbench HTML is rendered by API code; there is no broad static/template authority | Verify rendering; do not add generic static serving |
| Scientific stack | FastAPI, Uvicorn, Pydantic, SQLAlchemy, Alembic, SGP4, Matplotlib, NumPy, Structlog, and HTTPX are runtime dependencies | Freeze and parity-test the actual graph |
| Optional stack | psycopg[binary] is optional PostgreSQL support; Qiskit is separate | Exclude both from the first frozen PoC |
| Lifecycle | The container initializes storage and clears process-local custom-TLE handoff state at shutdown | Preserve readiness and restart-loss semantics |
| Security | CSP, Workbench referrer policy, loopback handoff checks, and security headers exist | Packaging must preserve them |

The repository has no PyInstaller package, spec file, launcher, or Windows packaging CI
job. Those are future U5.0B implementation outputs.

## PyInstaller Version and Build Policy

### Selected pins

The first build pins:

- PyInstaller 6.21.0;
- pyinstaller-hooks-contrib 2026.6.

Official PyInstaller 6.21.0 metadata declares Python 3.8 through 3.15 support and
provides a Windows x86-64 wheel. The official project description says it is tested
on Windows and is not a cross-compiler, so the Windows bundle is built on Windows.
The official hooks package lists 2026.6 as its release at this decision point and
requires Python 3.8 or newer.

Evidence reviewed:

- [PyInstaller 6.21.0 on PyPI](https://pypi.org/project/pyinstaller/);
- [PyInstaller installation guide](https://pyinstaller.org/en/stable/installation.html);
- [PyInstaller operating modes](https://pyinstaller.org/en/stable/operating-mode.html);
- [PyInstaller spec-file guide](https://pyinstaller.org/en/stable/spec-files.html);
- [pyinstaller-hooks-contrib 2026.6 on PyPI](https://pypi.org/project/pyinstaller-hooks-contrib/);
- [official hooks release history](https://github.com/pyinstaller/pyinstaller-hooks-contrib/releases).

The time-sensitive package and release metadata above was retrieved on 2026-07-13 UTC.

This supports selecting the pins. It does not prove that OrbitMind's complete
dependency graph freezes correctly; that is U5.0B evidence.

### Reproducibility

Build on Windows 10/11 x86-64 in a clean Python 3.12.x virtual environment. The exact
future lock file is requirements/u5.0b0-windows-py312.lock.txt. It uses pip
requirements format with every direct and transitive dependency pinned to an exact
version and accompanied by a SHA-256 hash.

The future installation command shape is:

~~~
.venv-build\Scripts\python.exe -m pip install --require-hashes --no-deps -r requirements\u5.0b0-windows-py312.lock.txt
~~~

The lock must include PyInstaller 6.21.0 and pyinstaller-hooks-contrib 2026.6. The
lock file does not exist in U5.0B0; its creation and review are U5.0B implementation
work. The lock-file SHA-256 must be included in build metadata. No dependency may be
resolved dynamically during the frozen build, and editing pyproject.toml is not
authorized in this slice.

Capture the clean Git commit, Windows build number and architecture, Python version,
PyInstaller version, hooks version, dependency inventory, lock hash, exact command,
build log, and a SHA-256 manifest of every output file. Prepare all wheels before the
offline build step and verify those wheels against the lock hashes; after preparation,
the frozen build makes no network request.
U5.0B is developer-local and isolated-environment only. CI packaging is deferred.

Future command shape, after U5.0B creates the reviewed spec file:

~~~
\.venv\Scripts\python.exe -m PyInstaller --clean --noconfirm --log-level=INFO --distpath build\u5.0b0\dist --workpath build\u5.0b0\work packaging\orbitmind.spec
~~~

The spec file defines COLLECT one-folder output. The command and file are not created
in U5.0B0. The disposable output is build\u5.0b0\dist\OrbitMind\.

## Package-Data and Import Inventory

| Input | Classification | Rule |
| --- | --- | --- |
| alembic.ini | Required in first PoC | Include at a package-relative or launcher-resolved path and verify before readiness |
| migrations/env.py | Required in first PoC | Include the tracked migration environment |
| migrations/script.py.mako | Required in first PoC | Include because Alembic references it |
| migrations/versions/*.py | Required in first PoC | Include all revisions needed to reach n9c0d1e2f3g4 |
| src/orbitmind/api/assets/trajectory_replay.js and its package | Required in first PoC | Collect via importlib.resources and compare frozen bytes |
| Workbench HTML/CSS renderer | Required behavior, no separate file | Verify frozen output; do not add generic static serving |
| Other templates/static paths | Excluded unless a current route proves one required | Add only an exact reviewed path |
| src/orbitmind/__init__.py version metadata | Required in first PoC | Include version in status and build manifest |
| SGP4, NumPy, Matplotlib | Required in first PoC | Collect from locked dependencies and prove propagation parity |
| FastAPI, Uvicorn, Starlette, Pydantic, SQLAlchemy, Alembic, Structlog, HTTPX | Required in first PoC | Exercise startup and read-product paths |
| SQLite support | Required in first PoC | Use the selected user database path |
| psycopg[binary] | Optional source/development; excluded from first PoC | Later PostgreSQL packaging requires separate acceptance |
| Qiskit | Excluded | Quantum behavior is outside this spike |
| Dynamic/hidden imports | Unresolved until build analysis | Record warnings; add only justified exact rules |
| Version/build manifest | Required in evidence | Capture, do not infer |
| Certificates | Excluded unless a real local requirement is found | No default external access |
| MIME/type data | Unresolved only if a frozen response proves it needed | Do not collect broad system data |
| Project documentation | Excluded from runtime bundle | Remains in the source/review surface |

The inventory decision is closed because every category has a rule. The unresolved
rows are bounded evidence checks, not permission to guess or collect broad directories.

## PostgreSQL Scope

The frozen PoC supports **SQLite only**. SQLite is the default Solo Alpha path and
avoids bundling a native PostgreSQL driver or a separate server lifecycle.

The source/development product continues to support PostgreSQL and its migration-
governed validation paths. No dependency is removed. The frozen PoC must not claim
PostgreSQL runtime support. A later packaged PostgreSQL slice must cover driver
packaging, connection configuration, service lifecycle, migrations, ownership, and
offline expectations.

## Runtime and Data Paths

The first PoC uses a user-scoped internal bundle location, not an installer:

~~~
%LOCALAPPDATA%\OrbitMind\
  poc\u5.0b0\bundle\       one-folder bundle; read-only at runtime
  runtime\                   runtime marker and bounded status metadata
  config\config.json         versioned user configuration
  data\orbitmind.db          SQLite database
  projects\                  user projects
  artifacts\                 generated reports and approved artifacts
  cache\                     bounded cache data
  logs\                      launcher and backend logs
  backups\                   pre-migration SQLite backups
  temp\                      runtime temporary files
~~~

Runtime working directory is %LOCALAPPDATA%\OrbitMind\runtime\, never the bundle.
Build output is disposable and separate, for example build\u5.0b0\dist\ and
build\u5.0b0\work\ in a clean checkout. Portable extraction is not selected; any
future portable mode needs a separate path/deletion decision. Deleting the bundle
does not delete %LOCALAPPDATA%\OrbitMind\.

## ACL and Privilege Decision

Run as a standard Windows user with no administrator requirement. Use inherited ACLs
from the current user's profile. Do not change ACLs and do not grant Everyone write
access. A missing or unwritable path is a fixed startup failure; the runtime does not
redirect to the bundle or a public temporary directory.

Elevated launch is unsupported: detect it, report that standard-user launch is
required, and exit before opening the Workbench or migrating data. A different
Windows account gets separate user data, mutex scope, database, logs, and transient
state. Shared multi-user data is unsupported.

## Configuration and Settings Adapter

Choose strict versioned JSON at:

~~~
%LOCALAPPDATA%\OrbitMind\config\config.json
~~~

The top-level field config_schema_version is 1. JSON comments are not supported.
Unknown keys, wrong types, invalid syntax, or unsupported versions stop startup;
defaults do not silently replace invalid configuration.

Precedence is exactly:

~~~
built-in defaults
    -> user config JSON
    -> ORBITMIND_* environment variables
    -> bounded allowlisted launcher arguments
~~~

The future adapter resolves an allowlisted mapping and constructs the existing
Settings model directly. Settings remains the only authority and retains bind-host,
port, worker, reload, forwarded-trust, handoff, and database validation. The adapter
must not create a parallel policy engine.

Before an approved config migration, make a timestamped backup beside the config,
for example config.json.bak-20260713T000000Z. If migration fails, preserve the
original and stop. Secrets, raw TLEs, cookies, authorization values, and provider
credentials are excluded; future credentials require separate OS-protected storage.

The existing names remain authoritative: ORBITMIND_API_BIND_HOST,
ORBITMIND_API_WORKERS, ORBITMIND_API_RELOAD_ENABLED,
ORBITMIND_FORWARDED_HEADER_TRUST_ENABLED, and
ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED. Launcher arguments may choose an explicit
approved port but may not bypass Settings.

## Single-Instance Primitive

The first PoC selects a Windows named mutex:

~~~
Global\OrbitMind.U5.0B0.Runtime.v1.<current-user-SID>
~~~

The future implementation must apply a descriptor allowing the current user to
coordinate with its own runtime without broad write access. The SID-qualified global
name is intended to enforce one OrbitMind runtime per Windows user across interactive
sessions. If the scoped object cannot be created, fail closed instead of weakening it.

Acquire it before database access, file logging, backend start, browser opening, or
transient-state construction. Kernel cleanup handles a crash. Existing mutex means a
fixed conflict response; never attach to, kill, or signal the other process. Port
collision is defense in depth, not a replacement. Duplicate runtimes must not race
over SQLite, logs, browser sessions, or transient handoffs.

## Uvicorn and Status Surface

Keep one OrbitMind application process. The future thin launcher starts the existing
orbitmind.api.app:app through uvicorn.Server programmatically.

- Launcher main thread owns status and Windows console-control handling.
- One managed background thread owns one Uvicorn asyncio event loop; no Uvicorn worker.
- Readiness is a bounded canonical-loopback probe. No external probe is allowed.
- Open http://127.0.0.1:<port>/workbench only after readiness.
- Stop requests Uvicorn exit, joins the backend thread, and waits for FastAPI lifespan.
- Ctrl-C and supported console-close events request the same bounded stop.
- Backend crash or timeout becomes a fixed status and exit code without raw exceptions.
- Closing the browser does not stop the backend.

The smallest status surface is a bounded console/status window, not a tray or
dashboard. It displays:

~~~
starting
validating configuration
checking database
starting backend
ready
http://127.0.0.1:<port>/workbench
failed
stopping
stopped
~~~

It also shows version, port, fixed safe error, Open Workbench instruction/action, and
Ctrl-C stop guidance. It never displays raw TLEs, credentials, cookies, arbitrary
exception text, or local secrets.

## SQLite and Migration Decision

Alembic head n9c0d1e2f3g4 remains schema authority. Future startup behavior is:

1. validate paths and acquire the mutex;
2. create a new user SQLite file and run the embedded migration path on first run;
3. inspect the revision of an existing database before Workbench readiness;
4. for an older compatible revision, create and verify a backup under
   %LOCALAPPDATA%\OrbitMind\backups\ and require explicit console confirmation;
5. stop for a newer, unknown, missing-revision, or corrupt database;
6. on migration failure, preserve original and backup and stop.

There is no destructive repair, silent replacement, automatic downgrade, or second
database created to hide a failure. Backup name is
orbitmind-<UTC timestamp>-pre-migration.sqlite3. Exact copy/integrity verification
is a U5.0B implementation and test item.

Select SQLite's default rollback journal rather than WAL for the first PoC because
one guarded process has one writer and this avoids WAL sidecar/backup coordination.
Initial busy timeout target: 5 seconds. SQLite locking must still be measured.
PostgreSQL is excluded from the frozen PoC.

## Port Collision and Exit Codes

Default port is 8000. Explicit ports are 1024 through 65535 and the application and
custom-TLE handoff ports must match. There is no automatic fallback. An occupied port
is reported, the other process is not identified or killed, the browser is not opened,
and the launcher exits with 21 (port_collision). The operator may choose another
explicit approved port and restart.

Proposed launcher-level codes, not current application behavior:

| Code | Name | Meaning |
| ---: | --- | --- |
| 0 | success | Clean user-requested shutdown or normal completion |
| 10 | invalid_configuration | Settings, path, environment, or config failure |
| 20 | single_instance_conflict | SID-scoped mutex already held |
| 21 | port_collision | Explicit port is occupied |
| 30 | database_corruption | SQLite integrity or revision inspection failed |
| 31 | migration_failure | Approved migration failed |
| 40 | readiness_timeout | Backend did not become ready in time |
| 50 | backend_crash | Managed backend ended unexpectedly |
| 60 | unsupported_environment | Unsupported OS, architecture, elevation, or runtime |

Messages use fixed reason codes and recovery guidance. They do not expose passwords,
tokens, TLEs, authorization values, stack traces, or arbitrary file contents.

## Removal and User-Data Preservation

U5.0B has no installer. The future status/help surface must distinguish these actions:

### A. Remove application bundle

Deletes only the one-folder application bundle. It preserves every user-data subtree:

~~~
config\
data\
projects\
artifacts\
cache\
logs\
runtime\
backups\
temp\
~~~

All of these remain under %LOCALAPPDATA%\OrbitMind\. Export important work before
any separate data action.

### B. Clear cache

Deletes only:

~~~
cache\
temp\                 disposable contents only
~~~

It must not delete projects, the database under data\, artifacts, backups, config\,
or logs\ unless separately selected by an explicit action.

### C. Reset settings

Export or back up configuration first, then remove or replace only config\config.json.
Preserve projects, the database, artifacts, and backups. Other user-data subtrees
remain unless a separate explicit action selects them.

### D. Delete all OrbitMind data

Before this action, provide export guidance and require an explicit irreversible
confirmation. State clearly that it removes projects, databases, artifacts,
configuration, logs, runtime state, cache, temp files, and backups. Warn that backups
may be the only recovery copies.

Deleting backups is never implied by ordinary bundle removal, cache clearing, or
settings reset. No ordinary action silently deletes user projects. Portable mode and
a system-wide uninstaller remain separate decisions.

## External Distribution Boundary

U5.0B is local and non-distributable. An unsigned bundle may be tested only in an
isolated internal Windows environment. SmartScreen or antivirus warnings are evidence
to record, not trust or permission to distribute. There is no public download,
supported installer, updater, external alpha, or trust claim.

External distribution remains blocked pending approval of code-signing identity,
signature verification, signed artifacts and metadata, an antivirus/reputation plan,
tamper-resistant release handling, and an installation/removal contract.

## U5.0B Implementation Gate

Every required kickoff item is closed. Closed means the design choice is fixed; it
does not mean implementation or evidence exists. External distribution is recorded
separately as deferred and blocked; it is not authorized by this kickoff decision.

| Required decision | Status | Closed choice |
| --- | --- | --- |
| PyInstaller version | **CLOSED** | PyInstaller 6.21.0 and hooks 2026.6 |
| Build command | **CLOSED** | Clean venv plus the spec-file command above; COLLECT one-folder output |
| Clean build environment | **CLOSED** | Windows 10/11 x86-64, Python 3.12.x, reviewed lock, offline frozen build |
| Dependency-lock mechanism | **CLOSED** | Hashed pip requirements lock at requirements/u5.0b0-windows-py312.lock.txt; --require-hashes, --no-deps, and no dynamic resolution during build |
| Package-data inventory | **CLOSED** | Explicit Alembic, asset, package, dependency, optional, excluded, and evidence rules |
| PostgreSQL scope | **CLOSED** | SQLite-only first frozen PoC; source/development PostgreSQL remains separate |
| Extraction location | **CLOSED** | User-scoped %LOCALAPPDATA%\OrbitMind\poc\u5.0b0\bundle\; no bundle writes |
| ACL behavior | **CLOSED** | Standard user, inherited ACLs, no broad changes, elevated launch rejected |
| Config format | **CLOSED** | Strict versioned JSON at %LOCALAPPDATA%\OrbitMind\config\config.json |
| Settings adapter | **CLOSED** | Allowlisted precedence mapping constructs existing Settings |
| Single-instance primitive | **CLOSED** | SID-qualified Global namespace Windows named mutex |
| Uvicorn execution model | **CLOSED** | One process; main-thread launcher and one managed Uvicorn thread/event loop |
| Status surface | **CLOSED** | Bounded console/status window with lifecycle states and URL |
| SQLite migration/backup | **CLOSED** | Embedded head check, verified pre-migration backup, explicit confirmation, no repair |
| Port collision | **CLOSED** | Default 8000, explicit range, no fallback/attach/kill, code 21 |
| Exit codes | **CLOSED** | Codes 0, 10, 20, 21, 30, 31, 40, 50, and 60 |
| Removal wording | **CLOSED** | Bundle removal separate from explicit cache/settings/all-data deletion |
| External distribution boundary | **DEFERRED** | Internal unsigned spike only; public and supported distribution remain blocked |

U5.0B implementation may begin after this record is approved. It may not be accepted
or merged as a packaging result until its exit evidence is produced and reviewed.
No packaging implementation exists in U5.0B0.

## Explicit Exclusions Preserved

No packaging implementation, production-source/dependency/configuration/migration
change, installer, Tauri, Electron, Rust rewrite, tray, service, updater, public
distribution, cloud control plane, account, authentication, authorization, public
CSRF, reverse proxy, multi-worker runtime, hosted service, camera, microphone, Visual
Universe, agents, Laboratory, Quantum Studio, or quantum mission behavior is authorized.

## Final Decision

**APPROVE BOUNDED U5.0B PACKAGING SPIKE.**

This is approval for the exact local Windows one-folder PoC only. It creates no trust,
distribution, public readiness, scientific authority, or change to the existing
offline product boundary.
