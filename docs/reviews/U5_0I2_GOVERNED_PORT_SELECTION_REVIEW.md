# U5.0I2 Governed Port Selection Review

Status: design review complete; implementation not started.

## Gate Identity

- Repository: the repository root
- Branch: `phase/u5-0b1-windows-packaging-spike`
- HEAD: `e22c831bfc6ca0b838e7b092975bdf1c8c80fbda`
- Prior result: `INTERNAL INSTALLER TEST PASS WITH USABILITY FINDING`
- Finding: fixed local port `8000` conflicted with `sutra-backend.exe` on an external
  nonpristine Windows machine.
- Evidence quality: user attestation with screenshot-observed details, not independent
  target telemetry or formal clean-machine verification.

## Inspected Files

Repository sources and decisions:

- `README.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/architecture/LOCAL_RUNTIME_ARCHITECTURE.md`
- `docs/architecture/WINDOWS_PACKAGING_KICKOFF_DECISIONS.md`
- `docs/operations/U5_0B_WINDOWS_PACKAGING_SPIKE.md`
- `src/orbitmind/core/config.py`
- `src/orbitmind/runtime/__init__.py`
- `src/orbitmind/runtime/configuration.py`
- `src/orbitmind/runtime/database.py`
- `src/orbitmind/runtime/launcher.py`
- `src/orbitmind/runtime/paths.py`
- `src/orbitmind/runtime/server.py`
- `src/orbitmind/runtime/status.py`
- `src/orbitmind/runtime/windows.py`
- `tests/test_windows_runtime.py`
- `tests/integration/test_windows_runtime_launcher.py`
- `tests/test_windows_packaging_sources.py`
- `packaging/orbitmind.spec`
- `scripts/build_windows_poc.ps1`
- `scripts/verify_windows_poc.ps1`

External internal-test records inspected read-only:

- U5.0I0 authoritative installer source: `OrbitMind-U5.0C-Internal.iss` (stored outside Git)
- U5.0I0 final installer build evidence: `internal-installer-build-verification.json`
  (stored outside Git)
- U5.0I1 external installer test closure evidence:
  `external-installer-test-closure.json` (stored outside Git)

## Current Implementation Findings

| Area | Finding | Design consequence |
| --- | --- | --- |
| Default | `_DEFAULT_PORT = 8000` | Preserve |
| Explicit input | `--port` already exists and range-checks `1024`-`65535` | Refine rather than invent a second parser |
| Duplicate input | Standard `argparse` retains the last repeated `--port` | Future contract must reject duplicates |
| Persisted input | Strict `config.json` currently includes `port` | Preserve as compatibility input; add no new preference in first slice |
| Environment input | Existing `ORBITMIND_CUSTOM_TLE_HANDOFF_PORT` can select the port | Preserve validated precedence; do not promote through installer |
| Immutability | Launcher argument and runtime configuration dataclasses are frozen | Extend with source metadata |
| Settings | Selected port is stored in `Settings.custom_tle_handoff_port` | Keep Settings as policy authority |
| Socket | Exact IPv4 `127.0.0.1` preowned socket; exclusive use when available | Retain as sole bind authority |
| Ordering | SQLite preflight currently precedes socket reservation | Reorder in U5.0I2B so collision precedes database mutation |
| Fallback | No automatic fallback exists | Preserve |
| Readiness | Health and Workbench use selected-port base URL | Preserve and add parity tests |
| Browser | Workbench URL uses selected port and opens only after readiness | Preserve; test stale-port absence |
| Status | Port and ready URL can be emitted; collision gives only reason code | Add fixed recovery guidance later |
| Owner identity | No product process-owner lookup exists | Optional privacy-bounded U5.0I2C work |
| Mutex | SID-qualified mutex is independent of port | One instance per user across all ports |
| Evidence | `runtime.json` path exists but is not written | Add bounded operational record only in approved source slice |
| Verifier | Explicit port is consistently passed to launch and probes | Extend default/override and no-database-on-collision assertions |
| Installer | All shortcuts and post-install launch are argument-free | Preserve default `8000`; manual recovery only |
| Packaging | Launcher is the frozen entry point; no port-specific package data | No spec or dependency change expected |

## Compatibility Findings

The requested first user-facing override is already technically functional. The gap
is governance and usability: duplicate arguments are not rejected, configuration
source is not recorded, collision happens after database preflight, collision output
lacks recovery guidance, and the installer test did not expose the manual override.

The closed packaging decisions specify defaults to JSON to environment to launcher
argument precedence. This review does not silently reverse that decision. U5.0I2A
must treat command line as the first supported external recovery control while
preserving existing lower-precedence compatibility inputs and adding no new persisted
preference.

Source mode remains separate: ordinary `python -m uvicorn orbitmind.api.app:app`
continues to use its existing Uvicorn and Settings behavior. The governed launcher
contract applies only through the Windows runtime composition root.

## Architecture Decisions

1. Default port remains `8000`.
2. First supported user-facing override is command line only:
   `OrbitMind.exe --port 8010`.
3. Accepted range is `1024` through `65535`; guidance recommends `8000` through
   `8999` without scanning it.
4. Bind host is fixed to `127.0.0.1`.
5. No silent fallback, random port, port scan, or broad range scan is allowed.
6. OrbitMind never terminates, signals, attaches to, or takes over the owner.
7. One OrbitMind instance per Windows user remains enforced regardless of port.
8. Socket reservation moves before database mutation and application construction.
9. Browser, readiness, Workbench, status, and evidence derive from one immutable
   selected-port value.
10. Installer shortcuts remain argument-free and default to `8000`.
11. No installer field, registry port, firewall rule, or new persisted preference is
    added in the first implementation.
12. Port selection is operational transport configuration, not scientific evidence.
13. Existing exit codes `0`, `10`, `20`, `21`, `30`, `31`, `40`, `50`, and `60`
    remain stable.
14. Camera, public-network mode, migration, and dependency changes remain out of
    scope.

## Safety Review

The proposed contract satisfies the required local-only boundary:

- Exact canonical loopback is fixed and not accepted as user input.
- Invalid or hostile port values fail before side effects.
- An occupied selected port returns `21` without fallback or database mutation.
- A second OrbitMind process returns `20` regardless of requested port.
- Process-owner information is optional, base-name only, and generic on uncertainty.
- Browser launch waits for selected-port readiness.
- No firewall, UPnP, external discovery, elevation, or remote bind is introduced.
- Installer behavior stays standard-user, argument-free, and local.

The complete risk, prevention, detection, fail-closed, and test mapping is in
`docs/architecture/GOVERNED_LOCAL_PORT_SELECTION.md`.

## Proposed Test Coverage

The architecture defines deterministic coverage for:

- default `8000` behavior;
- explicit `8010` propagation without touching `8000`;
- malformed, out-of-range, duplicate, URL, hostname, and whitespace values;
- collision before database mutation with no fallback or browser;
- owner-name privacy and generic fallback;
- duplicate launches on the same and different ports;
- selected-port socket and mutex release at shutdown;
- source, frozen, and installed parity;
- argument-free installer shortcuts; and
- external testing with SUTRA retained on `8000` while OrbitMind is explicitly run on
  `8010`.

## Proposed Implementation Order

1. `U5.0I2A` - refine the immutable parser/validation/source contract and focused
   unit tests, without server change.
2. `U5.0I2B` - propagate one authority everywhere and reserve the socket before
   database preflight.
3. `U5.0I2C` - add safe collision guidance and optional process base-name lookup.
4. `U5.0I2D` - rebuild and verify default and explicit frozen behavior.
5. `U5.0I2E` - refresh the installer without a wizard preference and test installed
   explicit-port recovery against a live local conflict.

## Unresolved Questions

These questions are deferred and do not block U5.0I2A:

- Whether the existing JSON and environment compatibility inputs should later become
  documented public controls or be deprecated under a separate compatibility gate.
- Whether process-owner base-name lookup is reliable and private enough to enable by
  default; the generic message is the required fallback.
- Whether a later local UI or installer may manage a persisted preference. No such
  behavior is part of the first implementation.
- Whether a future product ever needs multi-instance or public-network operation.
  Current decision remains no.

## Scope Confirmation

- Production source changed: no.
- Tests changed: no.
- Runtime behavior changed: no.
- PyInstaller spec changed: no.
- Installer script or candidate changed: no.
- Migration changed: no.
- Dependency or lock changed: no.
- Generated evidence changed: no.
- Camera scope changed: no.
- Files added by this gate: this review and the governed-port architecture document
  only.

## Recommendation

Proceed to `U5.0I2A` as a narrow port-configuration contract refinement. Preserve the
existing loopback, Settings, mutex, and exit-code authorities; reject duplicate port
inputs; record configuration source; and defer socket-ordering and user guidance to
their separately reviewed slices. Do not rebuild or refresh the installer until the
source slices and focused tests pass.

## U5.0I2A Implementation Status

Implemented only the configuration-contract refinement in
`src/orbitmind/runtime/configuration.py` and focused coverage in
`tests/test_windows_runtime.py`.

- Added immutable sanitized port-source labels: `default`, `command_line`,
  `environment`, and `json`.
- Added one strict port validator for default construction, command-line input,
  environment input, and validated JSON values.
- Changed repeated `--port` handling from last-value-wins to a sanitized
  configuration failure.
- Preserved default port `8000`, canonical loopback authority, compatible JSON and
  environment inputs, existing selected-port propagation, mutex policy, socket and
  database order, browser behavior, installer behavior, dependencies, migrations,
  and candidate artifacts.

## U5.0I2B Implementation Status

Implemented the launcher-ordering refinement in `src/orbitmind/runtime/launcher.py`
with focused runtime coverage.

- Runtime configuration now resolves before the existing per-user mutex is acquired.
- The immutable selected port now reserves its preowned IPv4 loopback socket before
  runtime paths are prepared or SQLite preflight begins.
- The same immutable port remains authoritative for server startup, readiness, status,
  and browser URLs.
- Focused checks cover default and explicit-port ordering, occupied-port isolation,
  failure cleanup, and the Windows listener lifecycle.
- No configuration-contract, migration, dependency, candidate, installer, build, or
  verification-script change was made.

## U5.0I2C Implementation Status

Implemented bounded selected-port collision guidance in the runtime launcher and
centralized status reporter.

- The existing structured `reason=port_collision` failure remains exit code `21` and
  now includes the immutable selected port.
- Guidance states that OrbitMind did not stop or take over the other local
  application, requires an explicit `--port` selection, and labels one deterministic
  example command as availability-unchecked.
- The example is `8010`, except when the selected port is `8010`, when it is `8011`.
- No port-owner inspection, port scan, fallback, retry, process termination,
  configuration change, persistence change, candidate change, or installer change was
  made.
