# Solo Alpha End-to-End Acceptance

## Acceptance Summary

| Item | Result |
| --- | --- |
| Branch | phase/u4-4a-solo-alpha-acceptance-gate |
| Base commit | 4ca88d1 (Merge pull request #87 from U4.3E implementation) |
| Session date | 2026-07-13 (Asia/Calcutta) |
| Scope | Local, offline Solo Alpha acceptance only |
| Alembic head | n9c0d1e2f3g4 (one head) |
| Verdict | PASS WITH REQUIRED FIXES |
| Production/public readiness | Not claimed; explicitly deferred |

The deterministic scientific, browser-security, persistence, and transient-handoff
boundaries passed the acceptance checks. The required follow-up is documentation
friction: the first-time operator path does not make the Mission Workbench or the
explicitly enabled, single-process custom-TLE handoff configuration sufficiently
discoverable in the README/runbook.

## Scope and Entry Criteria

This acceptance reviewed the implemented local product surface, not roadmap claims.
No production source, test, schema, dependency, deployment, authentication, provider,
agent, LLM, scheduler, or quantum behavior was changed.

The pre-session checkout was clean. The acceptance branch was at the main-derived base
4ca88d17c93a9d81e22366ee186a0ce4750d3971. git diff --check passed and Alembic
reported exactly one head, n9c0d1e2f3g4.

The active defaults were verified as:

- ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED=false;
- ORBITMIND_OPEN_RESEARCH_ENABLED=false;
- ORBITMIND_NETWORK_ENABLED=false; and
- ORBITMIND_CELESTRAK_ENABLED=false.

No live-provider or proxy-trust mode was enabled.

## Environment

| Item | Recorded value |
| --- | --- |
| Operating system | Microsoft Windows 10 Pro, 10.0.19045, 64-bit |
| Python | CPython 3.14.3 from .venv |
| Browser | Google Chrome 150.0.7871.114 |
| Browser mode | Real Chrome with DevTools Protocol; temporary isolated profiles; headless Chrome plus device emulation for mobile |
| Desktop viewport | Chrome default headless viewport reported 764 x 429; prior full desktop review used 1440 x 900 |
| Mobile viewport | 390 x 844 device emulation |
| JavaScript disabled | Tested against the server-rendered replay HTML |
| Reduced motion | prefers-reduced-motion: reduce tested in Chrome |
| PostgreSQL | PostgreSQL 16 Docker Compose profile, healthy on 127.0.0.1:55432 |
| Application bind | 127.0.0.1:8000 only |
| Temporary evidence | Stored outside the repository and removed; no screenshots or traces were committed |

The application startup command was the documented command with explicit local binding:

    .venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000

The sample command was run as documented:

    .venv\Scripts\python.exe -m orbitmind.sample

The PostgreSQL lane used the documented Docker Compose profile, a disposable
orbitmind_test database, Alembic upgrade head, and pytest -m postgres -ra with
ORBITMIND_TEST_POSTGRES_URL set to the loopback PostgreSQL URL.

## Implemented Product Surface

### Implemented and tested

- python -m orbitmind.sample: deterministic bundled ISS workflow, artifacts, static report, provenance, and audit.
- GET /health, GET /version, and GET /api/v1/system/capabilities.
- Reviewer sandbox: /review, /review/run, and /review/custom-tle.
- Mission Workbench: GET /workbench, POST /workbench/run, and POST /workbench/replay.
- Offline catalog and request-local custom-TLE mission-window calculations.
- Catalog Replay this request handoff with exact request continuity.
- Default-off custom-TLE transient handoff at POST /workbench/replay/custom-handoff.
- Server-authoritative trajectory replay with local SVG and same-origin controller asset.
- Mission detail and artifact reads under /api/v1/missions.
- Read-only visual manifest, static report, map/orbit context, provenance graph,
  observation geometry, observation planning, and product-summary API surfaces.
- SQLite offline validation and live PostgreSQL migration/read-product/regression paths.

### Implemented but not the primary browser operator path

Mission detail, static reports, visual manifests, map/orbit context, provenance graphs,
observation geometry, and observation planning are API/read-product surfaces. They are
implemented and tested but are not presented as a broad browser dashboard or as part of
the Workbench replay calculation.

### Deliberately unsupported or deferred

Live CelesTrak/JPL/provider use, public deployment, authentication, authorization,
general CSRF protection, reverse-proxy support, multi-worker handoff, durable replay
state, scheduler, agents, LLM calls, model training, self-modification, collision or
maneuver guidance, and quantum behavior on the orbital mission path remain outside this
acceptance.

## Full Test and Quality Results

The complete offline suite was allowed to run to process exit without the prior 900-second
cutoff:

    1460 passed, 262 skipped, 1 warning in 2345.87s (0:39:05)

The 1,722 collected tests therefore had no failures. The warning was the existing
Starlette/httpx deprecation warning from fastapi.testclient; it was not an OrbitMind
failure. Skips were the documented optional PostgreSQL tests in the default offline
run and optional Qiskit-dependent tests.

Quality gates:

| Command | Result |
| --- | --- |
| .venv\Scripts\python.exe -m ruff check . | Passed: All checks passed! |
| .venv\Scripts\python.exe -m ruff format --check . | Passed: 356 files already formatted |
| .venv\Scripts\python.exe -m mypy src --show-error-codes --no-incremental | Passed: no issues in 203 source files |
| .venv\Scripts\python.exe -m alembic heads | Passed: n9c0d1e2f3g4 (head) |
| git diff --check | Passed |

The live PostgreSQL-marked suite ran separately against the disposable Docker database:

    136 passed, 4 skipped, 1582 deselected, 1 warning in 613.18s (0:10:13)

The PostgreSQL database migrated to n9c0d1e2f3g4 (head). The four skips were optional
Qiskit/quantum cases. No transient handoff state is represented in PostgreSQL tables.

## One-Command Offline Sample

The sample exited with code 0 and printed:

- status: completed;
- epistemic_status: deterministic-calculation;
- source.test_only: true;
- source checksum and input hash;
- 31 samples; and
- the explicit stale-sample, not-live-tracking, and no-provider-fetch safety footer.

The generated report was inspected at the temporary path pattern
artifacts\<mission-id>\static_report.json. The report was valid UTF-8 JSON, ended
with a trailing newline, contained the deterministic report schema and limitation
sections, and included the not-live-tracking boundary. Generated image, sidecar, and
static-report files were removed after inspection.

## Acceptance Matrix

| Area | Result | Evidence |
| --- | --- | --- |
| Repository state | Pass | Clean before testing; base 4ca88d1; one Alembic head |
| Default startup | Pass | Fresh process started normally; handoff defaulted off; /health returned 200 |
| Catalog Workbench | Pass | Real Chrome 24-hour request showed the next predicted window, ordered additional windows, source age, collapsed evidence, and Replay this request |
| Catalog replay | Pass | Same request-local POST replay loaded paused; SVG, markers, 1,441-sample bounded replay, and segment-safe track rendered |
| Custom-TLE with handoff disabled | Pass | Real Chrome returned useful mission result, stated direct replay was unavailable, issued no handoff cookie, and did not substitute ISS/catalog |
| Custom-TLE with handoff enabled | Pass | Natural browser submission created the temporary handoff and replayed the exact custom source path |
| Startup rejection gates | Pass | Invalid port, worker count, reload, non-loopback bind, and forwarded-trust settings were rejected |
| Source/observer/interval continuity | Pass | Focused tests captured the exact TLE, checksum, observer, UTC interval, and replay request; browser replay displayed the same source identity |
| Duplicate consume | Pass | First consume returned 200; repeat returned identical safe 410 behavior |
| Owner mismatch | Pass | A separate Chrome profile could not replay the token and did not consume it; focused route test asserted 410 and original-owner success afterward |
| Expiry | Pass | Focused store/route expiry tests passed; prior real-Chrome U4.3E expiry evidence remains valid on this unchanged implementation |
| JavaScript disabled | Pass | Chrome DOM inspection of actual rendered replay HTML found SVG, markers, payload, limitations, noscript guidance, and all five controls disabled |
| Reduced motion | Pass | Chrome media emulation reported reduced motion and replay remained paused at sample 1 |
| Mobile | Pass | 390 x 844 replay measurement reported scrollWidth == clientWidth == 390 |
| Keyboard/focus | Pass | Existing Solo Alpha browser evidence and focused accessibility/security regressions passed; native controls and details remain keyboard reachable |
| Network boundary | Pass | Browser request capture had no external origins; active test guard blocks real httpx network transports |
| Persistence boundary | Pass | Fresh enabled SQLite counts and artifact/cache snapshots were unchanged by Workbench/handoff/replay |
| PostgreSQL acceptance | Pass | Docker PostgreSQL 16 healthy; migration and 136-test live lane passed |

## Browser Workflow Evidence

### Catalog source

Chrome 150.0.7871.114 submitted a 24-hour bundled iss request for observer
12.9716 N, 77.5946 E, 920 m, starting 2019-12-09T17:00:00Z with a 10 degree
minimum elevation. The result visibly contained Next predicted pass/contact window,
All qualifying windows, source age guidance, and a collapsed Method and evidence
section. The request-local Replay this request form remained POST-only. Replay loaded
paused and the static result carried the predicted/not-live language.

### Custom source, handoff, and replay

The valid bundled ISS TLE was submitted through custom mode with a bounded safe label.
The custom result rendered without either raw line. With the feature enabled, it created
one 43-character opaque token in the temporary POST handoff form. The response cookie was
orbitmind_handoff_session with HttpOnly, SameSite=Strict, Path=/workbench, Max-Age=1800,
host-only scope, and Secure=False on the approved loopback HTTP origin.

Chrome sent the canonical Origin: http://127.0.0.1:8000 on natural form POSTs. The
handoff route accepted only the exact server-side Sec-Fetch-Site: same-origin rule;
the Chrome DevTools request object did not expose that Fetch Metadata header in its
captured header projection, so its acceptance is corroborated by the route’s exact
protocol gate and the focused positive/negative tests rather than claimed as a raw CDP
header dump.

The replay page showed the same predicted source, observer, and interval, loaded paused,
and the Play action advanced the readout from sample 1 to sample 7. A second browser
profile showed the fixed unavailable response for the first profile’s token; the original
profile then consumed it successfully. A repeat submission failed closed.

### JavaScript, reduced motion, and mobile

The JavaScript-disabled Chrome target inspected the server-rendered replay without running
the controller. It found the SVG, observer marker, satellite marker, inert payload,
limitations, noscript explanation, and disabled Play/Previous/slider/Next/speed controls.
No replacement markup or network recovery was attempted.

With prefers-reduced-motion: reduce, Chrome reported the media preference and the replay
remained paused at Sample 1 of 241 until explicit play. At 390 x 844, the replay document
reported no page-level horizontal overflow.

Temporary browser profiles, HTML probes, and browser output were outside the repository;
no screenshot or trace was retained.

## Security Headers and Browser Boundary

The approved CSP was unchanged:

    default-src 'none'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self' data:;
    font-src 'none'; connect-src 'none'; object-src 'none'; base-uri 'none';
    frame-ancestors 'none'; form-action 'self'; worker-src 'none'; media-src 'none';
    manifest-src 'none'

HTML responses also carried:

    X-Content-Type-Options: nosniff
    X-Frame-Options: DENY
    Referrer-Policy: no-referrer or same-origin by route
    Permissions-Policy: geolocation=(), microphone=(), camera=(), payment=(), usb=(),
    magnetometer=(), gyroscope=(), accelerometer=()

The exact Workbench route scope returned Referrer-Policy: same-origin for /workbench,
/workbench/run, /workbench/replay, and safe handoff errors. /review remained
no-referrer. JSON responses had no HTML CSP or HTML Referrer-Policy, and the JavaScript
asset retained its own JavaScript content type and asset headers. The focused browser
security suite also covers artifact/binary scope, route boundary matching, and safe errors.

Normal replay generated zero CSP violations and zero console errors. All captured browser
requests were same-origin localhost requests; no external script, font, map, provider,
WebSocket, XHR, or fetch request occurred. The only cosmetic request observed in earlier
browser evidence was same-origin favicon.ico 404.

## Raw-TLE, Token, and Session Non-Disclosure

The non-disclosure checks used valid custom input and recorded only boolean outcomes, not
the marker text. Across result HTML, replay HTML, inert payload, URLs, JavaScript,
cookies, application logs, diagnostics, errors, temporary artifacts, cache, and database
snapshots:

- raw TLE lines were absent;
- the opaque token appeared only in the expected temporary POST form/body boundary;
- the raw session value was confined to the HttpOnly cookie boundary;
- no source checksum appeared in transient diagnostic output;
- no stack trace or local path appeared in user-facing errors; and
- no catalog or ISS fallback was introduced.

The enabled-process server logs contained neither raw TLE line and no traceback. The
application’s transient record was process-local and was not written to SQLite,
PostgreSQL, artifacts, cache, or durable audit tables.

## Persistence and Artifact Comparison

A fresh enabled SQLite process was started with a disposable database and isolated
artifact/cache roots. Before Workbench/handoff activity, all application state tables were
zero; only the expected five source_definitions rows and five source_policies rows
existed after startup. After custom mission-window calculation, handoff creation, replay
consumption, and duplicate rejection, the counts were identical:

- missions, mission_inputs, orbital_element_records, orbital_samples, audit_events,
  artifact_records, source_cache_entries, and all other application state tables remained zero;
- the five source-definition rows and five source-policy rows were unchanged;
- the isolated artifact directory remained empty; and
- the isolated cache directory remained empty.

The optional sample workflow intentionally persists its normal sample mission/artifacts
for inspection; those temporary sample outputs were removed after validation. This is
distinct from Workbench and transient-handoff behavior.

## Offline and Read-Product Boundary

The sample, catalog Workbench, custom-TLE calculation, transient handoff, replay, static
report, visual-manifest, provenance, and map/orbit read-product code paths were covered by
the complete offline suite and documented local smoke paths. The active test guard in
tests/conftest.py replaces real httpx transports with a raising implementation, and
tests/unit/test_no_network.py passed. Browser capture separately found no external origin.
Same-origin localhost traffic is reported as local application traffic, not external network
access.

## Operator Documentation Review

The README and runbook accurately describe installation, the offline sample, local API
startup, SQLite defaults, safety boundaries, and the optional PostgreSQL lane. The product
documents accurately describe the Workbench, raw-TLE boundary, source-age semantics, and
default-off custom handoff.

The operator friction is that the top-level five-minute README path leads to the sample
and reviewer sandbox but does not directly point to /workbench or summarize the U4.3E
enabled configuration. The runbook’s example uses --reload, which is valid for the
default-disabled application but incompatible with an explicitly enabled transient
handoff. An operator must find the product/architecture documentation to learn the exact
loopback, one-worker, no-reload, no-proxy contract.

## Findings by Severity

### P0

None observed.

### P1

None observed. No raw-TLE disclosure, owner-isolation failure, fallback source, unsafe
external action, persistence corruption, or deterministic replay failure was found.

### P2

#### U44A-P2-01 — Enabled handoff contract is not prominent in the operator entry path

- Route/screen: README/runbook entry path to /review and /workbench.
- Reproduction: Follow the README’s first five-minute path, start the documented
  uvicorn --reload example, and look for the Workbench/custom-TLE handoff configuration.
- Expected: The operator should be directed to the Workbench and told that custom-TLE
  transient replay is default-off and, when enabled, requires canonical loopback binding,
  one worker, no reload, and no forwarded-header trust.
- Actual: The README/runbook lead with the sample/reviewer flow and generic reload
  startup. Detailed product and architecture documents contain the constraints, but
  the operator must discover them separately.
- Evidence: Product browser flows passed only after using explicit U4.3E settings;
  startup validation rejected reload, non-loopback bind, multiple workers, and forwarded
  trust as designed.
- User impact: A solo operator can miss the primary Workbench entry point or start an
  incompatible configuration before understanding why the handoff is unavailable.
- Safety/scientific impact: No calculation or disclosure boundary is weakened; the risk
  is operational confusion around a security-sensitive local feature.
- Smallest correction: Add a short README/runbook pointer to the Workbench and a concise
  default-off/enabled-configuration note. Keep the existing reload example clearly scoped
  to the default-disabled flow.
- Blocks broader Solo Alpha continuation: Yes, until operator documentation is clarified;
  it does not block local technical use by an informed reviewer.

### P3

The following earlier Solo Alpha observations remain non-blocking and were not changed in
this acceptance: the 24-hour schematic track is visually dense, opening copy uses some
domain terminology early, and implementation evidence labels are not perfectly harmonized
between mission-window and replay results. These are polish/reviewer-friction items, not
acceptance blockers, and no P3 correction was attempted here.

## Deferred Public-Deployment Controls

This acceptance does not authorize public or multi-user use. The following remain deferred:

- HTTPS termination and HSTS policy for deployment;
- trusted host/origin and reverse-proxy configuration;
- authentication and authorization;
- general CSRF protection;
- rate limiting and abuse controls;
- operational logging, alerting, and durable audit policy;
- dependency/security scanning and release review;
- multi-worker or distributed transient state; and
- provider/network deployment review.

The custom-TLE handoff remains local Solo Alpha only, process-local, default-off,
non-authenticated, non-authorized, and not a claim of complete CSRF protection.

## Final Verdict

**PASS WITH REQUIRED FIXES**

The product can be installed, started, exercised, inspected, and scientifically framed
by an informed solo technical operator on one Windows laptop within its documented local
boundary. Full offline and live PostgreSQL regression evidence passed; the sample,
catalog/custom Workbench, replay, owner-mismatch, duplicate, expiry, no-JavaScript,
reduced-motion, mobile, browser-security, non-disclosure, persistence, and network checks
passed.

The gate is not a plain PASS because one unresolved P2 documentation finding remains.
It is not a FAIL: no P0 or P1 issue was observed, and the required correction is a
narrow operator-documentation update rather than a scientific, security, or persistence
redesign.

## Required Fixes and Recommendation

1. Add a minimal README/runbook pointer to /workbench and the product Workbench document.
2. Add the exact U4.3E enabled-mode constraints to the operator path: canonical
   127.0.0.1:<port>, one worker, reload disabled, forwarded-header trust disabled,
   default-off behavior, and no public/proxy/multi-worker use.
3. Re-run this acceptance’s browser and final-validation checklist after the documentation
   correction. No production code change is required by this finding.

Recommendation: continue local Solo Alpha use by informed technical operators after the
documentation correction is reviewed. Do not describe OrbitMind as production-ready,
public-alpha-ready, authenticated, live-tracking, or certified for operational decisions.

