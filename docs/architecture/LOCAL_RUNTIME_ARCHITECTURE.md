# OrbitMind Local Runtime Architecture

## Status

This is the U5.0A documentation-only architecture decision. No launcher,
packaging, installer, service, update system, or runtime behavior is implemented
by this document.

**Decision status: APPROVE WITH REQUIRED DECISION CLOSURE.** U5.0B is approved only
as a bounded, non-distributable Windows packaging and architecture spike. Its purpose
is to close remaining packaging design decisions, produce a reproducible PyInstaller
one-folder build, measure startup/resource/antivirus behavior, prove scientific and
security parity, and produce evidence for a later packaging acceptance decision.
U5.0B may begin after its kickoff design decisions are approved; its measured results
are produced and reviewed during the spike, not required before the spike starts.
U5.0A may merge after this wording correction. This document does not make OrbitMind
production-ready, publicly deployable, or a cloud service.

U5.0B is not an external alpha, public release, signed installer, updater, supported
distribution channel, or approval for Tauri, Electron, services, hardware, cloud,
agents, or public hosting.

## Scope

The target is a user-scoped Windows runtime for the verified Solo Alpha product. It
should let an operator install or extract OrbitMind, start it without manually
opening a terminal, open the existing Mission Workbench, use local CPU/RAM and later
approved local GPU or device capabilities, keep project data locally, inspect runtime
status, and stop cleanly.

The runtime remains offline-first and preserves the existing FastAPI application,
scientific services, provenance, artifacts, database boundaries, browser security,
epistemic labels, and human approval gates.

This slice does not implement packaging or add Tauri, Electron, Rust, PyInstaller,
installers, launchers, services, update systems, accounts, camera or microphone
access, 3D, crawling, agents, Laboratory, or Quantum Studio.

## Current-State Map

The actual current runtime is a local Python service, not an installed desktop
application:

| Concern | Current implementation | Boundary or limitation |
| --- | --- | --- |
| Python/runtime | `pyproject.toml` requires Python `>=3.12`; CI uses Python 3.12; local development uses `.venv` | No embedded runtime or installer exists |
| Application | FastAPI `app` from `orbitmind.api.app:app` | Module-level ASGI app; no launcher status process |
| Server | Uvicorn, normally one process on `127.0.0.1:8000` | The handoff requires one worker and no reload |
| Browser | System browser opens server-rendered `/workbench` HTML | Browser is not owned or sandboxed by OrbitMind |
| Scientific authority | Existing mission-window and trajectory-replay services | Browser JavaScript only presents server-produced values |
| Storage | SQLite default `sqlite:///./data/orbitmind.db`; PostgreSQL is optional and migration-governed | The default path is relative to the current project/runtime directory |
| Artifacts | Configured `artifacts_dir`, currently project-relative by default | Artifact files remain under the guarded root |
| Source cache | Configured `cache_dir`, currently project-relative by default | Network/provider switches are disabled by default |
| Process-local state | Custom-TLE transient handoff store is created by `AppContainer` only when explicitly enabled | It is cleared by lifespan shutdown and is not persisted |
| Startup | FastAPI lifespan constructs the container, configures logging, initializes storage, then serves requests | SQLite may create missing ORM tables; PostgreSQL uses Alembic as schema authority |
| Shutdown | Lifespan calls `AppContainer.shutdown()` | Transient handoff state is cleared; no installed-runtime crash recovery exists |
| Logging | Structured logs to stdout; JSON is optional | No user-scoped log rotation or support bundle exists |
| Security | CSP and browser-security headers are applied to HTML; Workbench uses `Referrer-Policy: same-origin` | No installer trust, single-instance lock, or packaged-update trust exists |
| Packaging | Setuptools source package; replay JavaScript is package data | CI does not build a Windows executable |

The one-command sample is a separate offline CLI path. `python -m orbitmind.sample`
uses the existing mission workflow without an API server and writes its sample
database and artifacts for inspection. That behavior is implemented and tested, but
it is not itself a desktop runtime launcher.

The Python version boundary is explicit: project metadata requires Python `>=3.12`,
Ruff and mypy target Python 3.12, and CI already tests Python 3.12. The current local
`.venv` development environment is Python 3.14.3; it does not replace the production
baseline. U5.0B must re-confirm deterministic and scientific parity on the frozen
Python 3.12 bundle. Metadata and CI alone do not prove that the packaged bundle is
correct.

Implemented and tested today: the FastAPI service, Workbench, offline catalog and
custom-TLE calculation, optional custom-TLE transient handoff, trajectory replay,
SQLite/PostgreSQL persistence paths, artifacts, read-product APIs, security headers,
and the offline sample. Implemented but outside the primary browser operator path:
mission detail, static reports, visual manifests, map/orbit context, provenance
graph, observation geometry/planning, and governed read surfaces. Deliberately
future: installed packaging, runtime status UI, updates, hardware capture, cloud
control, agents, and Quantum Studio.

## Product Objective and Non-Goals

The installed runtime must eventually provide:

- per-user installation or extraction without writing into program files;
- a single obvious Start action and a clear local-only status;
- the exact Workbench URL and an Open Workbench action;
- a clean Stop action and Ctrl-C compatibility;
- local project, database, artifact, and log ownership;
- offline operation without provider credentials or external network access;
- read-only runtime and resource status;
- preserved provenance, source age, limitations, and human approval boundaries.

The first runtime must not require an account, cloud server, internet access, public
binding, reverse proxy, multiple workers, external model provider, camera,
microphone, or administrator rights. A future camera or microphone feature requires
separate product, privacy, permission, and scientific-authority review.

## Options Considered

| Option | Repository fit and complexity | Windows packaging, lifecycle, security, and data | Browser, hardware, future agents, portability, and maintenance | Small-team assessment |
| --- | --- | --- | --- | --- |
| A. Current Python service + system browser | Exact fit; no code adaptation | No installer, signing, update, or clean double-click lifecycle; existing loopback/CSP and SQLite behavior remain | Existing browser compatibility; local hardware would require new APIs; cross-platform is already possible; lowest maintenance | Best baseline and reference, not a normal-user runtime |
| B. Python service + minimal native launcher | High fit if the launcher only starts, probes, opens, and stops the existing app; moderate Windows integration | Small launcher can own readiness, single-instance, shutdown, logs, and signed distribution; data remains local; lifecycle is explicit | Browser stays unchanged; hardware remains outside the launcher; future workers can be added behind review; native launcher needs platform maintenance | Good shape, but a native toolchain is unnecessary for the first packaging proof |
| C. Python service + tray application | Backend fit is good; tray lifecycle and notifications add UI/state complexity | Better background status and Stop action, but tray lifetime, autostart, signing, and AV reputation increase scope; local DB remains straightforward | Browser remains compatible; device permission UI may be added later; cross-platform tray behavior multiplies maintenance | Defer until a status window proves insufficient |
| D. Python service packaged with PyInstaller | Good fit for the existing package; one-folder build can embed Python and package data; build hooks must be verified | Supports user-level extraction, double-click start, signed executable, controlled shutdown, and offline use; one-folder is larger but easier to diagnose and less fragile than one-file; AV reputation still requires signing and testing | System browser remains unchanged; future device access can be added to backend; Windows-first, with separate builds later; build reproducibility is required | Selected first packaging target; no production dependency is added in U5.0A |
| E. Tauri shell + Python sidecar | Adds Rust, a webview shell, sidecar supervision, IPC, and two lifecycle domains without repository evidence | Can provide a polished signed shell, but packaging, update, permissions, and sidecar crash handling are materially larger; local DB is still backend-owned | WebView/browser behavior changes; hardware APIs may be easier but introduce a second authority surface; cross-platform builds and maintenance increase | Not justified for the first proof |
| F. Electron shell + Python service | Fast UI prototyping but adds a large runtime, Node toolchain, IPC, and a second application surface | Large memory/disk cost, signing/update/AV burden, and two-process lifecycle; offline is possible but not small | Chromium shell can access hardware, but expands attack surface and cross-platform maintenance; agents would gain no safe authority by default | Reject for this slice |
| G. PWA plus local daemon | Browser UI could remain familiar, but daemon discovery, permissions, service lifecycle, and origin security are new | Background service and localhost discovery complicate port ownership, startup, update, and user consent; data remains daemon-owned | Browser limitations remain; hardware is constrained; cross-platform daemon support and support cost are high | Reject for the first proof |
| H. Native Windows application | Could offer the best Windows UX but would duplicate the existing Workbench and runtime surface | Native installer, signing, updates, and lifecycle are a rewrite; scientific backend would still need embedding or IPC | Hardware integration is possible, but browser parity and future cross-platform path are poor; maintenance is high | Reject; preserve the verified backend |
| I. Rust runtime rewrite | No fit with current Python scientific and persistence code; highest implementation risk | Could produce a compact signed binary, but requires reimplementing or bridging FastAPI, SGP4, persistence, provenance, and browser surfaces | Hardware and agents would still need policy; cross-platform rewrite cost is extreme; scientific equivalence is hard to prove | Reject; not a packaging task |
| J. Server-hosted application | Contradicts local/offline-first and the Solo Alpha boundary | Requires deployment, auth, TLS, multi-user isolation, operations, and network security; local data sovereignty changes | Browser compatibility is easy but hardware/privacy/cloud boundaries change; operations cost is high | Explicitly out of scope |

The table's packaging, signing, update, and antivirus statements are architecture
assessments, not measurements from this repository. U5.0B must measure the selected
target on Windows before claiming suitability.

## Selected First PoC

The first packaging proof should use:

- the existing Python/FastAPI backend and scientific services unchanged;
- a **PyInstaller one-folder Windows x86-64 bundle** built from the project Python
  3.12 production baseline;
- one executable entry point that performs launcher/bootstrap duties and runs the
  backend in the same OS process;
- the existing Uvicorn/ASGI app lifecycle, with a thin future runner around it;
- the existing system browser, opened only after local readiness succeeds;
- a default `127.0.0.1` bind and default port `8000`;
- no automatic port selection in the first proof;
- user-scoped writable directories outside the installed bundle;
- a visible bounded launcher status surface, initially a console/status window rather
  than a tray or dashboard;
- no cloud dependency, provider call, account, service installation, or admin rights.

The first bundle is one-folder rather than one-file. This avoids hiding large
scientific dependencies in a self-extracting temporary directory, makes package-data
failures diagnosable, improves update/rollback control, and gives antivirus tooling a
stable file set. One-folder does not mean the bundle is trusted automatically; it must
be reproducibly built, scanned, signed when a release identity exists, and tested on a
clean Windows environment.

The first POC is an extracted bundle rather than a full MSI or MSIX installer. A
user-level installer is a later packaging decision after the bundle works. No
installer should silently delete user data.

### Build-recipe inputs to verify

U5.0B must inventory and test the package inputs rather than assume that a source
checkout and a frozen executable have the same contents:

- Alembic configuration and migration files;
- `importlib.resources`-loaded assets;
- the `trajectory-replay.js` asset;
- templates and static files, where present in the packaged surface;
- SGP4 dependencies;
- SQLAlchemy and database drivers;
- optional PostgreSQL dependencies where the PostgreSQL lane is supported;
- dynamic and hidden imports;
- version metadata;
- certificates only if a genuinely required local operation is confirmed; and
- package-data paths after freezing.

No package input is approved merely because it is present in the source tree. Missing
or unexpected inputs must fail the POC evidence review without weakening the browser,
scientific, or offline boundaries.

## Process Topology

### U5.0B target topology

| Role | Owner | Start/readiness | Shutdown/crash behavior | State and permissions |
| --- | --- | --- | --- | --- |
| Launcher/bootstrap role | OrbitMind executable, same OS process as backend in the first POC | Validate config, prepare user directories, start ASGI server, poll local `/health`, then open the Workbench | Ctrl-C or Stop requests orderly server shutdown; startup failure leaves no partial runtime; no automatic kill of an unrelated process | Owns status text, port choice, browser-open request, and runtime diagnostics; user-level only |
| OrbitMind backend role | Existing FastAPI/Uvicorn application in the same first-Poc process | FastAPI lifespan constructs `AppContainer`, initializes storage, then `/health` is ready | Lifespan calls `AppContainer.shutdown()`; transient handoffs are cleared; crash is reported on next start; no destructive repair | Owns scientific services, database sessions, provenance, artifacts, cache policy, and HTML/API responses |
| System browser | User/OS | Opened only after canonical local readiness; browser may also be opened manually | Browser is not killed on backend stop; a stopped backend leaves a clear unavailable page/status | Browser receives only local HTML/assets and the existing server-generated replay payload |
| Optional worker processes later | A separately reviewed runtime supervisor | Not part of U5.0B | Must have explicit state, limits, and approval; cannot be introduced by packaging convenience | Not allowed to share custom-TLE transient state without a new architecture decision |

The launcher and backend are separate conceptual roles but one application process in
the first POC. A separate supervisor process, tray process, background service, or
multi-worker Uvicorn deployment is not silently introduced.

A single-instance guard is required in the first POC, and its exact Windows primitive
must be selected before implementation. Port-collision failure is defense in depth,
not a replacement for that guard. Duplicate runtimes must not race over SQLite,
logs, browser sessions, or process-local custom-TLE handoff state.

The start order is: acquire a per-user single-instance guard, validate settings,
prepare directories, validate or migrate the database according to the selected
storage mode, start the backend, poll readiness, then open the canonical Workbench.
The stop order is: stop accepting new work, request Uvicorn shutdown, allow the
FastAPI lifespan to clear transient state, close database resources, flush bounded
logs, mark a clean stop, and exit.

The smallest acceptable U5.0B status surface is a bounded console/status window that
shows `starting`, `validating`, `checking database`, `ready`, the exact Workbench URL,
`failed`, `stopping`, and `stopped`. A native status window, tray icon, or dashboard
remains deferred.

## Port and Origin Contract

The first POC freezes:

- canonical host: `127.0.0.1` only;
- default application and handoff port: `8000`;
- allowed explicit port range: `1024` through `65535`, matching current settings;
- `ORBITMIND_CUSTOM_TLE_HANDOFF_PORT` must equal the application port when the
  handoff is enabled;
- exactly one application worker and reload disabled when the handoff is enabled;
- forwarded/proxy-header trust disabled;
- no `localhost`, `::1`, `0.0.0.0`, alternate IPv4 spelling, reverse proxy, or public
  bind for the enabled handoff.

The first POC does **not** automatically choose another port. If the configured port
is occupied, the launcher reports the collision, identifies the requested local URL,
and stops without killing or attaching to the existing process. A user may explicitly
choose another approved port and the launcher must communicate the resulting exact
`http://127.0.0.1:<port>/workbench` URL, but it must set the application and handoff
ports together.

Automatic port selection would alter the U4.3D/U4.3F canonical-origin, Origin,
Fetch-Metadata, cookie, and browser-QA contract. It is therefore deferred until a
separate origin/session review proves that dynamic ports do not weaken the handoff.
The launcher always opens `127.0.0.1`, never an alias.

## Local Data Layout

The current checkout uses project-relative `data/`, `artifacts/`, and `cache/`
locations. A packaged runtime must not write into its installed program directory.
The proposed Windows user-scoped layout is:

```text
%LOCALAPPDATA%\OrbitMind\
  config\                  versioned non-secret runtime configuration
  data\orbitmind.db        default SQLite system of record
  projects\                 user-owned project material, when a project model exists
  artifacts\                generated artifacts and reports
  cache\                    controlled source/cache material, if explicitly enabled
  logs\                     bounded local runtime logs
  runtime\                  bounded start/stop markers and status metadata
  models\                   reserved for explicitly approved local models
  knowledge\                reserved for approved local knowledge capsules
  updates\                  signed package metadata and staged update material
```

`projects/` may later be redirected to `%USERPROFILE%\Documents\OrbitMind`, but
that choice requires an explicit user-data and backup decision. The first POC should
keep it under `%LOCALAPPDATA%\OrbitMind\projects` and expose the location clearly.
Portable mode is not part of the first POC.

PostgreSQL is not bundled. An advanced operator may provide a PostgreSQL URL through
the existing settings boundary and follow the current Alembic/migration operations,
but credentials must not be stored in ordinary logs or project metadata. The default
runtime remains SQLite and offline.

Uninstall removes program files only by default. It must preserve `projects`, `data`,
artifacts, logs, cache, and knowledge data unless the user explicitly selects a
separate data-removal operation with a clear warning. Reset is a distinct operation,
requires confirmation, and must offer export/backup guidance first.

## Configuration and Secrets

The existing typed `Settings` model remains the configuration authority. The first
packaging POC should preserve the current `ORBITMIND_` environment names and safe
defaults, including:

- `ORBITMIND_DATABASE_URL=sqlite:///...` for default local storage;
- `ORBITMIND_ARTIFACTS_DIR` and the future user-scoped cache/data paths;
- `ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED=false` by default;
- `ORBITMIND_API_BIND_HOST=127.0.0.1`, `ORBITMIND_API_WORKERS=1`,
  `ORBITMIND_API_RELOAD_ENABLED=false`, and
  `ORBITMIND_FORWARDED_HEADER_TRUST_ENABLED=false`;
- both global and source-specific network switches false;
- `ORBITMIND_OPEN_RESEARCH_ENABLED=false` and no runtime wiring that activates it.

The proposed precedence for a packaged runtime is:

1. built-in safe defaults;
2. a versioned, non-secret per-user configuration file under `config/`;
3. environment variables supplied by the current user process;
4. explicit launcher arguments for non-secret, bounded startup values.

Higher-precedence values must be parsed by the same typed settings validation and
must not bypass the loopback, worker, reload, or forwarded-header checks. A future
config file format must be versioned, reject security-critical unknown fields, and
support forward migration without destructive repair. The exact file format and the
adapter that feeds it into `Settings` are required U5.0B decisions; this slice does
not add one.

The default mode needs no secret. Future provider or account credentials, if ever
approved, must use a Windows-protected credential facility such as DPAPI/Credential
Manager rather than plaintext config, environment dumps, logs, artifacts, or support
bundles. No secret manager is selected or implemented here.

Support export must be an allowlisted diagnostic bundle: versions, bounded status,
non-sensitive configuration names, migrations, and redacted errors only. It must
exclude raw TLE, project content, cookies, tokens, credentials, arbitrary headers,
filesystem secrets, and full request bodies.

## Startup and Readiness

The runtime exposes these operator-visible states:

1. `starting` - executable launched and single-instance guard acquired;
2. `validating configuration` - typed settings and packaging/runtime paths checked;
3. `checking database` - SQLite path or explicitly configured PostgreSQL checked and
   the approved schema path prepared;
4. `backend ready` - ASGI server is listening on the canonical loopback origin;
5. `Workbench available` - the readiness response confirms the browser surface is
   reachable;
6. `failed` - startup stopped with a fixed actionable reason code;
7. `stopping` - orderly shutdown is in progress;
8. `stopped` - process exited and clean-stop state was recorded.

The first POC should reuse `GET /health` as the readiness probe, with an internal
launcher signal around it rather than adding a new API contract in U5.0A. The
launcher should require a successful local response and available database status,
with a 30-second bounded startup timeout. It opens the browser only after readiness;
it never opens an external URL.

Failure behavior is explicit:

- duplicate launch or port collision: report the port and stop; do not kill or attach;
- stale process: do not assume it is OrbitMind; require an explicit operator action;
- missing/corrupt SQLite database: stop with backup/restore guidance; no destructive
  repair or silent replacement;
- migration failure: stop before Workbench availability and preserve the database;
- invalid enabled custom-TLE configuration: fail startup as current settings already
  require;
- missing packaged asset: fixed sanitized failure, not a path-bearing traceback;
- browser launch failure: keep the backend available and show the exact local URL;
- provider/network disabled: remain offline rather than retrying or falling back.

Database behavior is an implementation gate: there is no destructive repair and no
silent database replacement; an approved migration takes a backup when required;
migration failure prevents Workbench readiness; a corrupted database stops startup
with recovery guidance; and SQLite locking must be assessed under the single-instance
model. The exact packaged backup/migration mechanism must be decided before
implementation and tested during U5.0B.

## Shutdown and Crash Recovery

Clean shutdown must preserve current behavior: Ctrl-C remains valid, the ASGI lifespan
executes `AppContainer.shutdown()`, process-local custom-TLE state is cleared, and no
project data is deleted. Database sessions and file handles must close through their
existing context/lifecycle boundaries. Generated artifacts are flushed before exit
where possible; partial work is not reported as a completed scientific result.

The launcher should maintain a bounded `runtime/last_run` marker containing only a
schema version, start/stop times, clean-stop flag, version, port, and fixed reason
code. On the next start, an unclean marker produces a diagnostic message and a link
to recovery guidance. It must not contain raw TLE, cookies, tokens, secrets, request
bodies, arbitrary paths, or stack traces. No automatic database rollback, file
deletion, cache purge, or project repair is allowed.

An interrupted mission remains subject to the existing persistence transaction and
audit semantics. The runtime must not resume scientific work automatically. A
process restart loses transient custom-TLE handoffs by design; SQLite projects and
completed durable records remain available after restart.

## Update Boundary

Updates are future architecture only. A compliant updater must provide:

- signed package and metadata verification before installation;
- explicit user approval and no silent update or self-modification;
- application, schema, migration, and configuration compatibility checks;
- side-by-side staging and rollback before replacing the active bundle;
- offline update packages with a verifiable manifest;
- preservation of user data and an explicit migration backup/restore path;
- rejection of unsigned, tampered, incompatible, or partial packages.

No update server, account, telemetry, auto-update, or production self-modification is
introduced by U5.0A.

### External-distribution gate

A local, non-distributed U5.0B spike may be built and tested unsigned in an isolated
Windows environment. An unsigned local POC is not trusted, distributable, or a user
release. External distribution remains blocked until all of the following are approved:

- code-signing identity;
- signature verification;
- antivirus and reputation plan;
- tamper-resistant release process;
- signed update/package metadata strategy; and
- user-facing installation and removal contract.

## Resource Capability Reporting

The future runtime may expose a read-only bounded capability report containing:

- operating system and architecture;
- CPU model class and logical/physical core counts where available;
- total and available RAM;
- free disk space for the selected data root;
- GPU presence and a conservative driver/API identifier, without claiming workload
  support;
- Python/runtime or packaged engine version;
- later model support and battery/thermal state only after separate review.

The first runtime must not increase sample limits, start GPU work, load models, enable
agents, or select a quantum path based only on detected hardware. Current scientific
calculation remains deterministic and CPU-authoritative; any later GPU acceleration
requires equivalence tests, explicit limits, provenance, and human review.

## Local and Server Responsibility Boundary

Local by default:

- project data, SQLite, artifacts, caches, logs, and knowledge capsules;
- scientific calculations and server-rendered browser surfaces;
- secrets held by approved OS-protected storage, if a future feature needs them;
- custom-TLE transient handoffs and their bounded session state;
- future agent worktrees and generated-code quarantine, if separately approved;
- raw camera or microphone data, if later approved, with no default synchronization.

A later optional server may provide only separately approved services such as signed
update metadata, an opt-in account/device registry, opt-in encrypted backup,
structured-knowledge synchronization, connected research jobs, collaboration, or
quantum-provider coordination. The central control plane is deferred. No raw camera
or microphone stream may synchronize by default, and no server is required by the
first runtime.

## Security Model

The runtime preserves the current browser and scientific security boundary:

| Threat | First-runtime control | Residual limitation |
| --- | --- | --- |
| Malicious local webpage, DNS rebinding, non-loopback bind | Exact `127.0.0.1` bind, exact Host/Origin/Fetch-Metadata checks for handoff, no proxy trust | A compromised local machine can bypass application controls |
| Port hijacking or stale process | Fixed/explicit bounded port, single-instance guard, readiness identity, fail on collision | No automatic authority to kill an unknown process |
| Browser session/token theft | Existing HttpOnly SameSite session and single-use opaque handoff; no raw TLE in browser data | Local malware or browser compromise remains out of scope |
| Modified installer or unsigned update | Reproducible build, package hash, code signing and signed update gate before release | Signing identity and release service are not yet selected |
| Antivirus false positive | One-folder build, stable file set, scan and signed-release evidence | Reputation is not guaranteed by architecture |
| Log/project leakage | User-scoped paths, bounded redacted logs, no secrets/raw TLE in diagnostics | User filesystem permissions and local malware still matter |
| Multiple runtime instances | Single-instance guard and no attach/fallback behavior | Cross-user locking and elevated contexts need Windows testing |
| External launcher changing workers | Launcher owns bounded Uvicorn settings and startup validation; handoff remains default-off | An operator can still bypass the launcher with a source checkout |
| Forwarded-header trust | Disabled and rejected for handoff; no reverse proxy support | Public deployment is forbidden |
| Privilege escalation | User-level install/data paths; no service/admin requirement in PoC | Installer design and Windows ACL review remain open |
| Provider/network activation | Global and source switches remain false; no external URL is opened | Future connector enabling needs separate review |

The existing CSP remains the browser policy: `default-src 'none'`, same-origin
scripts only, no unsafe-eval, `connect-src 'none'`, no object/base/frame sources,
and temporary inline CSS only. The packaged launcher must not weaken it. The Workbench
referrer rule and custom-TLE canonical-origin contract remain unchanged.

## Performance Targets

These are proposed engineering targets, not measurements of the current repository:

| Metric | Target for the first Windows POC |
| --- | --- |
| Double-click to backend-ready | <= 15 seconds cold on a reference Windows 10/11 x86-64 laptop |
| Ready-to-Workbench paint | <= 2 seconds after readiness on the reference browser |
| First useful catalog result | <= 10 seconds for the existing bounded offline request |
| Aggregate idle process memory | <= 512 MiB after startup, excluding the browser |
| Clean shutdown | <= 5 seconds for an idle runtime |
| Extracted bundle size | <= 500 MiB before user data, measured rather than assumed |
| Update package size | <= 500 MiB for a full package; delta updates are optional later |
| Runtime log growth | <= 10 MiB/day with rotation and fixed retention targets |
| Installed user data overhead | <= 1 GiB excluding projects, artifacts, models, and caches |

U5.0B must measure cold/warm startup, RSS/working set, first paint, first result,
shutdown, bundle size, antivirus scan behavior, disk growth, and log rotation on a
clean Windows 10/11 x86-64 environment. Report p50/p95 across at least five runs,
hardware, browser version, database state, and whether PostgreSQL is involved. No
current value may be inferred from these targets.

## UX Requirements

The first runtime surface should remain small rather than become a dashboard. It must
provide:

- one obvious Start action, normally a double-clicked executable;
- visible `Local only`, `Offline`, and `Predicted geometry` status;
- exact `http://127.0.0.1:<port>/workbench` URL;
- Open Workbench action after readiness;
- Stop action and Ctrl-C compatibility;
- current application version and port;
- database status and migration state;
- bounded CPU/RAM/disk summary with no unsupported capability claim;
- future update availability text only after signed metadata exists;
- fixed safe startup failures with recovery guidance.

The Workbench remains the useful result surface. Runtime status must not hide source
age, provenance, limitations, human approval, or the fact that results are predicted
and not live tracking. No camera/microphone permission prompt is shown by the first
runtime.

## Compatibility

The first supported packaging environment is:

- Windows 10 and Windows 11;
- x86-64 hardware;
- a current system browser with the existing HTML/CSP support, with Chromium-based
  browser QA as the reference;
- user-level installation or extraction;
- an embedded Python 3.12 runtime matching the production baseline, so the user need
  not install Python for the packaged POC.

The first POC does not promise support for macOS, Linux, Windows ARM, multi-user
server deployment, public hosting, reverse proxies, background services, auto-start,
multiple workers, or a system-wide admin installation. Future cross-platform work
must preserve the same domain services and security contracts but is a separate
packaging decision.

## U5.0B Packaging POC Exit Criteria

U5.0B may be accepted only when all of the following are evidenced on a clean Windows
10/11 x86-64 machine or isolated VM:

1. A reproducible PyInstaller one-folder bundle can be built from the Python 3.12
  baseline environment and contains the application package data, including the replay
   controller asset.
2. The bundle starts by double-click without a repository checkout or manual Python
   installation.
3. The backend binds only to `127.0.0.1`; port collision and invalid settings fail
   safely; no automatic port substitution occurs.
4. Readiness is bounded, the exact Workbench URL is shown, and the browser opens only
   after the local backend is ready.
5. Default mode works with no provider credential or external network call.
6. The catalog Workbench, mission-window result, catalog replay, and one-command
   sample or equivalent run remain deterministic and useful.
7. SQLite project data survives a clean restart; the transient custom-TLE handoff
   remains process-local and is lost on restart.
8. Enabled custom-TLE handoff mode still enforces loopback, one worker, no reload,
   matching port, and no forwarded-header trust.
9. Clean shutdown clears transient state, closes resources, preserves user data, and
   records no partial scientific success.
10. Uninstall/removal preserves user projects and data unless explicitly selected.
11. No external network or provider request occurs under default or approved local
    test flows; local browser traffic is distinguished from external traffic.
12. The bundle has no admin requirement unless a separately justified installer step
    requires it.
13. Startup, memory, disk, shutdown, log-growth, browser, antivirus, and package-size
    measurements meet or explain the targets above.
14. No scientific source, migration, or behavior change was introduced by packaging.
15. Rollback, removal, database backup, and user-data recovery instructions are tested.

## Explicit Exclusions

U5.0A and the first POC do not add:

- Tauri, Electron, Rust rewrite, tray service, Windows service, auto-start, or cloud
  control plane;
- accounts, authentication, authorization, public CSRF protection, reverse proxy,
  multi-worker, or public hosting;
- live CelesTrak/JPL/provider access or external model APIs;
- camera, microphone, browser geolocation, raw sensor synchronization, or hardware
  command authority;
- 3D globe, interactive map tiles, crawling, research adapters, scheduler, agents,
  LLMs, Laboratory, Quantum Studio, or quantum mission behavior;
- a new database schema, migration, durable transient-handoff state, or generic cache;
- unreviewed background work, silent updates, telemetry, analytics, or self-modifying
  generated code.

## U5.0B Kickoff Decisions

The following design decisions must be agreed before U5.0B implementation begins:

- exact PyInstaller version and reproducible build command;
- package-data and hidden-import collection rules;
- extraction/runtime location;
- per-user directory and ACL behavior;
- versioned user-config format;
- config migration and adapter boundary into `Settings`;
- required single-instance guard and selected Windows primitive;
- packaged SQLite migration and backup approach; and
- failure behavior for migration, corruption, and port collision.

These are kickoff design gates. They are not measurements that must exist before the
spike starts.

## U5.0B Produced and Approved Exit Evidence

The following outputs are produced and reviewed during U5.0B before the spike is
accepted or merged:

- reproducible bundle evidence;
- clean-machine execution evidence;
- Python 3.12 scientific and deterministic parity results;
- startup timing, memory use, bundle size, disk growth, and shutdown timing;
- no-network evidence;
- antivirus and SmartScreen observations;
- console/status-surface evidence;
- removal and rollback evidence;
- data-preservation evidence; and
- an explicit exit-criteria verdict.

Until kickoff decisions are approved and exit evidence passes, no document should
describe OrbitMind as a supported distribution, self-updating runtime, hosted service,
authenticated product, or public-ready release.

## Recommendation

**APPROVE WITH REQUIRED DECISION CLOSURE.** U5.0B may proceed only as a bounded,
non-distributable Windows packaging and architecture spike using the existing
Python/FastAPI application in a PyInstaller one-folder, single-process bundle. It
must close the kickoff decisions above and produce the exit evidence before a later
packaging acceptance decision. Do not begin a shell rewrite, service, updater,
hardware integration, or cloud control plane. External distribution remains blocked.
