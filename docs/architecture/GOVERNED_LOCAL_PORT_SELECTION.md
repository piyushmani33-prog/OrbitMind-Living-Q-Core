# Governed Local Port Selection

Status: design approved for review; no implementation is authorized by this document.

## Problem Statement

The U5.0I1 external installer test installed OrbitMind successfully on a separate
Windows computer, but OrbitMind could not start while another local application,
`sutra-backend.exe`, owned `127.0.0.1:8000`. OrbitMind correctly failed closed with
`reason=port_collision`, did not take over the port, and worked after the conflicting
process stopped. The evidence is user-attested with screenshot-observed details; it is
not independent target-machine telemetry or formal clean-machine evidence.

The product needs a deterministic, explicit recovery path that lets a standard user
select another approved loopback port without weakening local-only boundaries. The
first supported user-facing override is command line only:

```text
OrbitMind.exe --port 8010
```

## Goals

- Keep `127.0.0.1:8000` as the safe default.
- Support one explicit, validated port for the entire process lifetime.
- Make collision failure and recovery understandable without inspecting private
  process details.
- Keep one OrbitMind instance per Windows user, independent of selected port.
- Use one selected-port value for socket ownership, Uvicorn, readiness, browser URL,
  status, and runtime evidence.
- Detect an occupied selected port before database mutation or application startup.
- Preserve source-mode operation, frozen-runtime safety, deterministic exit codes,
  shutdown cleanup, and offline behavior.

## Non-Goals

- Automatic, random, or silent fallback.
- Port scanning, including a scan of the recommended range.
- Binding to `0.0.0.0`, a LAN address, a public interface, an IPv6 wildcard, or a
  remotely reachable interface.
- Firewall rules, UPnP, external discovery, remote access, or elevation.
- Stopping, signaling, attaching to, or taking over another process.
- Adding an installer wizard field, registry setting, or multiple port shortcuts.
- Adding a new persisted port preference in the first implementation.
- Changing scientific records, provenance semantics, migrations, dependencies, or
  source-mode PostgreSQL support.
- Camera support, signing, publishing, or public distribution.

## Current Behavior

The current implementation already contains a bounded explicit-port path, but the
external installer surface does not explain it.

- `src/orbitmind/runtime/configuration.py` defines default `8000`, range
  `1024` through `65535`, `--port`, and immutable `LauncherArguments` and
  `RuntimeConfiguration` values.
- The packaged adapter currently resolves defaults, `config/config.json`,
  `ORBITMIND_*` environment settings, and launcher arguments. In practice the port can
  come from JSON key `port`, existing setting
  `ORBITMIND_CUSTOM_TLE_HANDOFF_PORT`, or `--port`; command line wins.
- The current `argparse` declaration validates integer conversion and range, but it
  accepts repeated `--port` options by retaining the final value. That does not meet
  this design's single-value rule.
- `src/orbitmind/runtime/launcher.py` acquires the SID-qualified mutex, prepares paths,
  builds configuration, runs SQLite preflight, and only then reserves the socket.
  Therefore a collision is currently detected after database preflight. The future
  launcher-propagation slice must reserve the selected socket before database mutation.
- `src/orbitmind/runtime/server.py` binds an IPv4 socket to exact
  `127.0.0.1:<port>`, uses `SO_EXCLUSIVEADDRUSE` when available, passes the preowned
  socket to one Uvicorn thread, and performs no fallback.
- Readiness probes use `/health` and `/workbench` at a base URL derived from the
  selected port. The Workbench URL property and browser launch use the same selected
  port, and the browser opens only after readiness.
- Collision maps to exit code `21` and reason `port_collision`. Current normal output
  is sanitized but does not provide recovery guidance or a safe process name.
- The named mutex identity is per Windows user and independent of port, so a second
  instance is rejected with exit code `20` even when it requests another port.
- The current installer Start Menu and optional desktop shortcuts pass no arguments.
  The post-install launch is also argument-free, so all use default port `8000`.
- The current verifier accepts an explicit port and sends that port to every frozen
  launch. Source and frozen tests already exercise non-default explicit ports.
- `RuntimePaths.runtime_marker` identifies `runtime/runtime.json`, but the current
  launcher does not write a selected-port runtime record.
- There is no current process-owner lookup in the product runtime.

## Configuration Contract

### First supported user-facing surface

The first governed user-facing contract supports only:

1. no port argument, selecting default `8000`; or
2. one explicit command-line argument, `--port <PORT>`.

No new environment variable or persisted preference is added. The existing JSON and
`ORBITMIND_CUSTOM_TLE_HANDOFF_PORT` compatibility inputs must not be silently removed
or reinterpreted; they remain validated lower-precedence inputs until a separate
compatibility decision changes them. They are not installer-facing recovery features
in the first slice.

### Precedence

The resolved precedence, highest first, is:

1. explicit command-line port;
2. the existing approved environment setting;
3. the existing validated per-user JSON value, with any future preference requiring
   separate approval;
4. built-in default `8000`.

This is equivalent to applying defaults, then persisted JSON, then environment, then
command line. The resolution result must include both the selected integer and one
source value: `default`, `command_line`, `environment`, or `persisted_preference`.

### Validation

- Accept exactly one port value.
- Accept ASCII decimal integer text only.
- Accept range `1024` through `65535`, inclusive.
- Recommend `8000` through `8999` in user guidance; do not scan or silently select
  from that range.
- Reject a missing value, text, zero, negative values, `1`, `1023`, `65536`, decimal
  fractions, URLs, host names, `host:port`, whitespace-only values, and repeated or
  multiple `--port` arguments.
- Do not accept a host as part of port configuration. The host is fixed separately.
- Invalid configuration fails before socket, database, application, or browser work
  with exit code `10` and reason `invalid_configuration`.
- The selected port is immutable for the process lifetime. A bind failure never
  changes it. Retrying requires a new process launch with an explicit value.

## Loopback Guarantee

The host is a constant authority, not user input: `127.0.0.1`.

The same exact host must govern socket reservation, Uvicorn, readiness, Workbench,
browser launch, verification, and evidence. The launcher must reject any effective
setting that requests `localhost`, `0.0.0.0`, `::`, `::1`, a LAN address, a public
address, or another hostname. No firewall rule, UPnP operation, network-interface
discovery, remote access, or administrator privilege is allowed.

## Startup and Socket Authority

The future launcher order is:

1. validate Windows, architecture, and non-elevated execution;
2. acquire the existing per-user mutex;
3. parse and validate the port contract;
4. derive and prepare approved user-scoped paths;
5. construct Settings and the immutable port selection;
6. reserve `127.0.0.1:<selected_port>` with the existing preowned-socket mechanism;
7. run SQLite preflight and any approved migration behavior;
8. construct the FastAPI application;
9. start Uvicorn using the preowned socket;
10. probe readiness using the selected-port base URL;
11. report ready and optionally open the selected-port Workbench URL.

Path-directory preparation may occur before reservation, but database creation,
migration, application construction, backend startup, and browser launch may not.
Every acquired resource remains in the existing bounded cleanup path. Socket and
mutex release are required after every failure and clean shutdown.

## Collision Behavior

When the selected port is occupied, OrbitMind must:

- stop before database mutation or application startup;
- preserve fail-closed exit code `21` and reason `port_collision`;
- keep the selected port fixed and perform no fallback or scan;
- leave the owning process untouched;
- open no browser;
- expose no full process command line, arguments, secrets, or unrelated details; and
- display deterministic recovery guidance.

Required primary message:

```text
OrbitMind could not start because local port <PORT> is already in use.
```

Required recovery message:

```text
Close the other local application or start OrbitMind with an explicitly selected port:
OrbitMind.exe --port 8010
```

The example is guidance, not an automatic selection. OrbitMind must attempt `8010`
only when the user launches it with that exact argument.

### Process-owner privacy

Process-owner display is optional and best effort. It may show only a safely obtained
executable base name associated with the exact local listening socket:

```text
Port 8000 is currently used by: sutra-backend.exe
```

If identity lookup fails, requires elevation, races with process exit or PID reuse, or
cannot establish an exact local-listener mapping, use:

```text
Port 8000 is already in use by another local process.
```

Do not read or display the full command line, working directory, environment,
credentials, service account, or unrelated process information. Do not characterize
the owner as malicious and do not recommend killing system processes.

## Browser and URL Behavior

The selected port is the single source of truth for:

- the preowned socket and Uvicorn;
- `http://127.0.0.1:<port>/health`;
- `http://127.0.0.1:<port>/workbench`;
- browser launch;
- startup console output;
- verification output; and
- runtime evidence.

Examples:

```text
http://127.0.0.1:8000/workbench
http://127.0.0.1:8010/workbench
```

The browser may open only after socket ownership, database preflight, backend startup,
and the existing readiness condition succeed. No browser path may retain stale port
`8000` after an explicit override. `--no-browser` retains its current authority.

## Installer Behavior

The first implementation does not modify the installer.

- Keep Start Menu and optional desktop shortcuts argument-free.
- Keep the default at port `8000`.
- Add no installer wizard port field, registry value, firewall rule, alternate-port
  shortcut, elevation, or machine-wide setting.
- Collision recovery is a manual explicit launch from a console or an equivalent
  separately approved local UI that invokes `OrbitMind.exe --port 8010`.
- A later installer preference is deferred and requires its own source, persistence,
  upgrade, uninstall, and verification decisions.

## Runtime Evidence and Provenance

Port selection is runtime transport configuration. It is not scientific evidence, a
mission input, a persisted scientific record, installer configuration, or user
project data.

A future sanitized runtime record may use the existing user-scoped runtime marker and
must contain only:

- bind host;
- selected port;
- configuration source: `default`, `command_line`, `environment`, or
  `persisted_preference`;
- startup result;
- collision result; and
- a UTC timestamp where the existing runtime evidence convention uses timestamps.

Write the record atomically and treat it as operational evidence. Do not store a full
command line, unrelated environment variables, browser history, interface inventory,
process command lines, secrets, credentials, request bodies, raw TLEs, or scientific
results. Console output may show the selected port and canonical URL because neither
is sensitive.

## Exit-Code Policy

Existing numeric codes remain stable.

| Outcome | Code | Existing reason/policy |
| --- | ---: | --- |
| Clean shutdown | `0` | `success` |
| Invalid port or runtime configuration | `10` | `invalid_configuration` |
| Duplicate OrbitMind instance | `20` | `single_instance_conflict` |
| Selected port occupied | `21` | `port_collision` |
| Database integrity failure | `30` | `database_corruption` |
| Migration failure | `31` | `migration_failure` |
| Readiness timeout | `40` | `readiness_timeout` |
| Backend startup/crash or shutdown timeout | `50` | `backend_failure` or bounded `shutdown_timeout` reason |
| Unsupported Windows environment | `60` | `unsupported_environment` |

No existing code is renumbered. A new shutdown-specific numeric code is not justified
for the first slice; the current bounded code `50` remains the failure outcome.

## Mutex Policy

One OrbitMind instance per Windows user remains authoritative regardless of port. The
SID-qualified named mutex is acquired before database access and retained until final
cleanup. A second launch on the same port or another explicit port exits with `20`;
it does not create a second database, listener, browser session, or backend. Port
selection is collision avoidance with other local products, not a multi-instance mode.

## Threat Analysis

| Threat | Risk | Prevention | Detection | Fail-closed behavior | Test requirement |
| --- | --- | --- | --- | --- | --- |
| SUTRA or another local service owns the port | OrbitMind cannot start | Explicit validated override; no takeover | Exclusive bind fails | Code `21`, fixed port retained, safe guidance | Hold selected loopback port; assert no database/browser/fallback |
| Malicious local process squats on the port | Denial of local startup | No trust based on owner identity; no attach/kill | Exclusive bind fails | Same generic collision path | Squatting listener remains alive and unchanged |
| Privileged or invalid port | Permission error or unsafe configuration | Strict decimal range `1024`-`65535` | Parser/Settings validation | Code `10` before socket or database | Boundary and malformed-value matrix |
| Port value injection | Host/URL/extra arguments alter behavior | Port-only typed parser; reject duplicate and non-decimal input | Parse failure | Code `10`; no side effects | URL, `host:port`, whitespace, duplicate, metacharacter cases |
| Stale browser URL | Browser reaches wrong service | Derive every URL from immutable selection | Ready output and URL assertions | Do not open browser unless selected-port readiness passes | Explicit-port browser and no-stale-8000 test |
| Automatic fallback hides configuration | Evidence and browser disagree with actual port | No retry, scan, random selection, or port mutation | Selected-port evidence compared with listener | Code `21`; user must relaunch | Occupy selected port while another is free |
| Non-loopback bind | Remote exposure | Constant `127.0.0.1`; reject host inputs and hostile environment | Listener inspection and Settings guard | Code `10` before backend | Assert no wildcard, IPv6, LAN, or public listener |
| Duplicate OrbitMind on different ports | SQLite, logs, handoff, and projects race | Per-user mutex independent of port | Mutex conflict | Code `20`; second launch does no work | First on 8000, second on 8010 |
| Persisted preference becomes stale | Repeated collision after environment changes | No new preference in first slice; explicit source evidence | Collision record identifies persisted source if legacy input used | No fallback; explicit relaunch | Legacy persisted value collision remains deterministic |
| Process-owner inspection leaks data | Command-line secrets or unrelated metadata exposed | Base executable name only; optional exact-listener lookup | Output audit | Generic owner message | Lookup unavailable/denied/race and secret-bearing command line |
| Attacker-controlled environment variable | Unexpected port selection | Existing allowlisted name, strict validation, CLI precedence | Record source as `environment` | Invalid value code `10`; no fallback | Hostile, malformed, boundary, and CLI-override tests |
| Installer shortcut arguments are modified | Unexpected launch port or additional options | Official shortcut remains argument-free; launcher allowlist rejects extras | Shortcut audit and parser rejection | Code `10` for unsupported arguments | Installed shortcut and tampered-argument negative tests |
| Verification uses a different port | False health or collision conclusion | Pass one explicit port through launch, probes, evidence, and listener checks | Cross-check PID/listener/URLs | Verification fails without probing alternatives | Source, frozen, and installed explicit-port parity |

## Deterministic Test Matrix

### A. Default behavior

- No port argument selects source `default` and port `8000`.
- The only listener is `127.0.0.1:8000`.
- Health and Workbench URLs use port `8000`.
- Startup output and evidence report `8000`.

### B. Explicit valid port

- `--port 8010` selects source `command_line` and port `8010`.
- The only listener is `127.0.0.1:8010`.
- Health, Workbench, browser, output, and evidence use `8010`.
- Port `8000` is never probed, bound, or opened.

### C. Invalid values

Each of the following returns `10` before socket or database work: missing value,
text, zero, negative, `1`, `1023`, `65536`, decimal fraction, URL, hostname,
`host:port`, duplicate arguments, multiple values, and whitespace-only value.

### D. Collision

- A verifier-owned listener holds the selected port.
- OrbitMind returns `21` with the selected port and safe guidance.
- No fallback, port scan, database mutation, application construction, or browser
  launch occurs.
- The listener owner remains running and unchanged.
- Owner-name lookup is tested for success, access denial, process exit, PID reuse
  uncertainty, and generic fallback without command-line disclosure.

### E. Duplicate OrbitMind

- First instance on default port; second default launch returns `20`.
- First instance on default port; second `--port 8010` launch also returns `20`.
- First instance on explicit port; second launch on another explicit port returns
  `20`.
- The first instance remains healthy and no second database or listener appears.

### F. Shutdown

- Clean shutdown returns `0`.
- Preowned socket and per-user mutex are released.
- Selected port becomes available after shutdown.
- No backend thread, process, listener, or browser-owned lifecycle remains.
- A bounded shutdown timeout retains exit code `50` and cleanup behavior.

### G. Packaging and installer

- Source execution, frozen executable, and installed executable produce matching
  default and explicit-port behavior without network or new dependencies.
- The Start Menu and optional desktop shortcuts remain argument-free and use default
  port `8000`.
- Manual installed invocation with `--port 8010` succeeds while SUTRA owns `8000`.
- Frozen evidence verifies exact loopback listener, URL parity, exit codes, mutex,
  shutdown, and no external endpoint.

## Implementation Slices

### U5.0I2A - Port configuration contract

- Refine the existing immutable port selection into value plus source.
- Enforce exact one-value syntax, range, duplicate rejection, and fail-closed parsing.
- Preserve Settings as policy authority and existing compatibility precedence.
- Add focused unit tests only; do not change server behavior in this slice.

### U5.0I2B - Launcher propagation

- Make the immutable selection the sole authority for socket, Settings handoff port,
  Uvicorn, readiness, Workbench, browser, console status, and runtime evidence.
- Reserve the socket before SQLite preflight and application construction.
- Preserve cleanup, source-mode behavior, and one-process Uvicorn execution.

### U5.0I2C - Collision guidance

- Add fixed recovery text and optional privacy-bounded process base-name lookup.
- Never require owner identity and never terminate or signal another process.
- Add denial, race, PID reuse, redaction, and generic-fallback tests.

### U5.0I2D - Frozen candidate verification

- Rebuild only after source gates pass.
- Verify default and explicit ports, exact loopback binding, collision-before-database,
  duplicate mutex behavior, readiness, browser suppression, shutdown, evidence, and
  offline operation.

### U5.0I2E - Installer refresh

- Package only the verified candidate.
- Keep installer shortcuts argument-free and add no wizard port preference.
- On a separate approved Windows test, keep SUTRA on `8000` and manually launch the
  installed OrbitMind executable on `8010`.

## Acceptance Criteria

- Default remains `127.0.0.1:8000`.
- The first supported user-facing override is exactly one command-line port.
- Valid range is `1024` through `65535`; guidance recommends `8000` through `8999`.
- There is no silent fallback, random selection, scan, takeover, process termination,
  public bind, firewall change, elevation, migration, or dependency change.
- Collision occurs before database mutation and application construction.
- One selected value reaches every bind, URL, output, and evidence surface.
- One OrbitMind instance per Windows user remains enforced across ports.
- Installer shortcuts remain argument-free.
- Current exit-code numbers remain stable.
- Unit, integration, frozen, and installed tests pass offline with injected state.

## Deferred Decisions

- Whether the existing JSON port field and environment compatibility input should be
  promoted as public user-facing controls, retained as advanced compatibility inputs,
  or deprecated in a separately approved migration-free change.
- Whether a future local UI may manage a persisted preference and how it handles stale
  values, upgrades, uninstall, and provenance.
- Whether Windows process-owner lookup is reliable enough to enable by default after
  privacy and race testing; generic collision text remains sufficient.
- Whether a future installer may offer a port preference. The first installer refresh
  may not.
- Any multi-instance mode, automatic port choice, public-network mode, camera support,
  or remote access. None is authorized here.

