# Solo Alpha Usability and Safety Session

## Session metadata

| Item | Recorded value |
| --- | --- |
| Session date | 2026-07-12 (Asia/Calcutta) |
| Branch | `phase/u4-3a-solo-alpha-usability-safety-session` |
| Base and session commit | `5afddeb` |
| Base description | Current clean pulled `main`; merge of PR #81 |
| Session type | Local, offline Solo Alpha usability and safety evaluation |
| Verdict | **PASS WITH REQUIRED FIXES** |
| Production/public-alpha status | Not assessed as ready; explicitly deferred |

## Scope

This session evaluated the complete server-rendered offline browser path:

`/review` -> `/workbench` -> `/workbench/run` or `/workbench/replay`

The evaluation covered the bundled offline catalog, request-local custom TLE input,
mission-window results, no-window and clipped-window states, animated trajectory replay,
evidence disclosure, mobile layout, keyboard operation, JavaScript-disabled behavior,
reduced motion, CSP, input failure handling, and persistence/network boundaries.

This was an evaluation-only slice. No product behavior, production source, test, schema,
dependency, deployment, or security configuration was changed. Screenshots were viewed in
memory and were not written to the repository.

## Environment

| Item | Value |
| --- | --- |
| Operating system | Microsoft Windows 10 Pro 10.0.19045, 64-bit |
| Python | CPython 3.14.3 from the repository `.venv` |
| Browser | Installed Google Chrome through Playwright |
| Browser version | 150.0.7871.114 |
| Desktop viewport | 1440 x 900 |
| Mobile viewport | 390 x 844 |
| JavaScript disabled | Tested in a separate browser context |
| Reduced motion | Tested with `prefers-reduced-motion: reduce` |
| Database | Local SQLite (`sqlite:///./data/orbitmind.db`) |
| PostgreSQL | Not running; Docker Desktop engine was unavailable |
| Alembic head | `n9c0d1e2f3g4` |
| Startup command | `.venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000` |
| Bind address | `127.0.0.1:8000` only |

The startup command is the existing command documented in
`docs/operations/SOLO_ALPHA_SMOKE_FLOW.md`. Uvicorn started without an application error,
reported successful startup, and `GET /health` returned HTTP 200.

## Entry criteria

- The working tree was clean before the session.
- `HEAD`, local `main`, and `origin/main` all resolved to `5afddeb`.
- `ORBITMIND_NETWORK_ENABLED` was false.
- `ORBITMIND_CELESTRAK_ENABLED` was false.
- `ORBITMIND_JPL_SBDB_ENABLED` and `ORBITMIND_JPL_CAD_ENABLED` were false.
- `ORBITMIND_OPEN_RESEARCH_ENABLED` was false and inert.
- No `ORBITMIND_*` environment override was present in the process environment.
- Alembic reported exactly one head, `n9c0d1e2f3g4`.
- The pre-session database, artifact, cache, and Git snapshots were recorded.

## Scenario matrix

| Scenario | Result | Evidence summary |
| --- | --- | --- |
| A. First-time discovery | Pass with friction | Workbench was one click from `/review`; labels and units were visible. The first domain-heavy phrase was "identified orbital element set." |
| B. Catalog mission windows | Pass | ISS catalog request for 12.9716 N, 77.5946 E, 920 m, 24 hours, and 10 deg minimum elevation returned two ordered windows. |
| C. Custom TLE | Pass | Bundled ISS TLE succeeded request-locally; label escaped; no TLE appeared in HTML or URL. Malformed TLE returned sanitized HTTP 422. |
| D. No-window result | Pass | A minimum elevation of 89 deg returned HTTP 200 with a clear empty state and next-step suggestion. |
| E. Clipped windows | Pass, partial coverage | Real fixture exercised clipped-at-start and clipped-at-end. A full-interval clipped ISS pass was not reachable under the one-hour minimum duration and was not manufactured. |
| F. Animated replay | Pass | SVG, markers, controls, synchronized readouts, source/model details, and evidence worked. Playback started paused. |
| G. Dateline | Pass | A 24-hour replay produced 16 server segments; the first crossing remained continuous from sample 29 to 30 without a cross-world polyline. |
| H. Mobile | Pass | No page-level overflow at 390 x 844; form, buttons, SVG, controls, readouts, and evidence remained usable. |
| I. Keyboard-only | Pass | Workbench link, form controls, both actions, replay controls, slider, and details were reachable and operable with visible focus. |
| J. JavaScript disabled | Finding | Static track, summary, limitations, and `noscript` message remained, but inert replay controls still looked usable. |
| K. Reduced motion | Pass | Replay stayed paused at sample 1 until explicit action; static SVG remained visible. |
| L. Input/security probes | Pass | All probes failed closed with HTTP 422 or 413, sanitized HTML, CSP, no fallback, and no partial result. |
| M. CSP/network | Pass | Normal replay loaded only same-origin document and JavaScript. Inline execution was blocked. No external request occurred. |
| N. Evidence/trust | Pass with friction | Replay evidence was complete and collapsed by default; implementation identifiers remain difficult for non-experts. |

## Successful flows

### First-time discovery

The Mission Workbench card is visible on the normal reviewer entry page. It takes one click
to reach the Workbench. A first reading of the form took approximately two minutes. The
offline, predicted, and not-live boundaries are visible before input. Source modes are
separated, units are on field labels, UTC has an example and helper, and the two actions are
visually and textually distinct.

The first confusing phrase was "identified orbital element set." The first help needed was
not field mechanics, but interpretation: what source age means for usefulness and why the
user should prefer one age over another.

### Catalog mission-window calculation

The catalog scenario used:

- Object: bundled `iss` / ISS (ZARYA)
- Observer: 12.9716 deg latitude, 77.5946 deg longitude, 920 m altitude
- Start: `2019-12-09T17:00:00Z`
- Duration: 24 hours
- Minimum elevation: 10 deg

The HTTP 200 result placed the first useful window before evidence. It showed source epoch,
source age, explicit UTC rise/peak/set values, maximum elevation, compass directions with
degrees, duration, and two deterministically ordered windows. The first window rose at
`2019-12-10 04:36:54.814 UTC`, peaked at `04:39:54.123 UTC` at 31.70 deg, and set at
`04:42:53.583 UTC`. Optical visibility and live-tracking exclusions remained visible. Raw
TLE lines were absent. Method and evidence was collapsed initially and expanded correctly.

### Custom TLE and safe failure

The existing bundled ISS TLE was submitted through the custom mode with the label
`Alpha & Beta`. The label displayed safely, the source was identified as a user-provided
offline TLE, and no raw TLE appeared in the response HTML, URL, browser console, or error
surface. The calculation did not fall back to the catalog.

A malformed line returned HTTP 422 with the fixed source-validation message. CSP and all
browser-security headers remained present. No raw input, traceback, internal exception,
fallback result, or partial window output appeared.

### No-window and clipped-window states

The 89 deg threshold returned HTTP 200 and stated that no qualifying geometric window was
found. It repeated the interval, threshold, source epoch/age, and suggested lowering the
threshold or expanding the interval. The state did not imply a missing object, provider
failure, or application error.

The fixed fixture also produced:

- `2019-12-09T20:00:00Z`: "Active at analysis start" with "Rise / boundary."
- `2019-12-09T19:00:00Z`: "Continues after analysis end" with "Set / boundary."

These classifications were visible without expanding evidence and did not present request
boundaries as true horizon crossings.

### Trajectory replay and dateline

The 24-hour replay selected a deterministic 60-second interval and returned 1,441 samples
in 16 track segments. It displayed a schematic SVG, observer marker, satellite marker,
sample/segment counts, UTC timestamp, geodetic latitude, canonical longitude, WGS84
altitude, azimuth, elevation, and range.

Playback started paused. In a timed check, Play advanced from sample 1 to sample 35 and
moved the marker; Pause returned the control to "Play." The slider selected sample 101,
Next selected 102, and Previous returned to 101. Changing speed to 4x did not change the
selected sample timestamp.

At a genuine dateline crossing, sample indexes 28 and 29 were adjacent. Longitude changed
from 177.9842 deg to -177.5832 deg and display x moved from 994.4 to 6.713. The samples
belonged to separate polylines, sequence remained continuous, every sample appeared exactly
once, and the largest within-segment x change was only 16.67 display units.

## Defects and friction

No P0 or P1 finding was observed.

### U43A-01: Mission-window result does not carry the request into replay

| Field | Detail |
| --- | --- |
| Severity | P2 |
| Route/screen | `POST /workbench/run` result |
| Reproduction | Submit a catalog or custom-TLE mission-window request, inspect the result, then try to replay that same request. |
| Expected | A clear request-local path to replay the same validated source, observer, and interval without re-entry. |
| Actual | The result offers "Calculate another mission window" and "Reviewer sandbox." The user must return and re-enter the request before choosing replay. |
| Evidence | The catalog result retained no replay action or submitted form. The two actions exist only on the initial form. |
| User impact | The intended windows-then-replay workflow is interrupted and custom TLE users must paste sensitive-looking orbital text again. |
| Safety/scientific impact | Re-entry increases the chance that replay inputs differ from the window calculation while appearing to be the same investigation. |
| Smallest correction | Add a request-local, POST-only "Replay this request" handoff that reuses the already validated values without persistence or URL parameters. |
| Blocks Solo Alpha continuation | No, but it should be the first P2 correction. |

### U43A-02: JavaScript-disabled replay leaves inert controls looking active

| Field | Detail |
| --- | --- |
| Severity | P2 |
| Route/screen | `POST /workbench/replay` with JavaScript disabled |
| Reproduction | Load a successful replay in a JavaScript-disabled browser context. |
| Expected | Static track and summary remain; unavailable playback controls are hidden or unmistakably disabled. |
| Actual | Static content and the `noscript` explanation are correct, but Play, Previous, Next, slider, and speed controls remain visible and look usable while doing nothing. |
| Evidence | Browser inspection reported the SVG, summary, limitations, `noscript` message, replay control container, and Play button all visible. |
| User impact | A user may repeatedly activate controls and conclude that replay is broken. |
| Safety/scientific impact | No calculation is corrupted, but the state is misleading and weakens trust in the static fallback. |
| Smallest correction | In a separately reviewed UI slice, hide the interactive control group with a `noscript` style or render it disabled by default and enable it only after controller initialization. |
| Blocks Solo Alpha continuation | No, but required before broader external review. |

### U43A-03: Source age is precise but not interpreted

| Field | Detail |
| --- | --- |
| Severity | P2 |
| Route/screen | Mission-window and replay result summaries |
| Reproduction | Run a catalog result and read "Source age at start" and "Maximum prediction offset" as a non-expert. |
| Expected | The user understands why the age/offset matters and that no universal accuracy threshold exists. |
| Actual | Exact age and offset are shown, but no concise nearby explanation connects larger offsets to reduced prediction usefulness. |
| Evidence | The result showed "21 min 31 s after source epoch" and a one-day maximum offset; the explanatory dependency on age appears only in the limitations text. |
| User impact | A user can read the number but cannot judge its practical meaning. |
| Safety/scientific impact | Users may over-trust old elements even though the page avoids a universal accuracy claim. |
| Smallest correction | Add one short visible sentence near source age: prediction usefulness generally degrades as element age/offset grows, with no universal distance guarantee. Do not invent thresholds. |
| Blocks Solo Alpha continuation | No, but required before describing source freshness as user-friendly. |

### U43A-04: Full-day replay track is visually dense

| Field | Detail |
| --- | --- |
| Severity | P3 |
| Route/screen | 24-hour `POST /workbench/replay` |
| Reproduction | Replay the ISS for 24 hours at desktop or 390 px mobile width. |
| Expected | Track history remains understandable as a schematic trajectory. |
| Actual | Sixteen overlapping orbital segments create a dense lattice, making the selected segment and travel direction hard to distinguish. |
| Evidence | The rendered SVG contained 16 separate polylines and 1,441 samples; segmentation was correct but visually crowded. |
| User impact | The map is impressive but takes longer to interpret, particularly on mobile. |
| Safety/scientific impact | No false geometry was drawn; risk is interpretation rather than calculation. |
| Smallest correction | In a future presentation-only slice, visually emphasize the active segment/sample while keeping server segments authoritative. |
| Blocks Solo Alpha continuation | No. |

### U43A-05: Opening copy uses domain terminology before plain-language meaning

| Field | Detail |
| --- | --- |
| Severity | P3 |
| Route/screen | `GET /workbench` |
| Reproduction | Enter from `/review` as a first-time non-expert. |
| Expected | The first sentence explains the task in ordinary terms. |
| Actual | "Identified orbital element set" appears before a plain-language explanation of TLE/catalog source data. |
| Evidence | This was the first label requiring interpretation during the approximately two-minute form review. |
| User impact | Mild onboarding friction. |
| Safety/scientific impact | None; the wording is scientifically honest. |
| Smallest correction | Pair the technical term with a short plain-language phrase, without changing its scientific meaning. |
| Blocks Solo Alpha continuation | No. |

### U43A-06: Evidence metadata differs between result types

| Field | Detail |
| --- | --- |
| Severity | P3 |
| Route/screen | Mission-window versus replay Method and evidence sections |
| Reproduction | Expand Method and evidence on both result types and compare identifiers. |
| Expected | Reviewers can apply one consistent mental model to source, model, and result identity. |
| Actual | Replay exposes source and element checksums plus frame/geodetic and observer-geometry identifiers. Mission windows expose source checksum, trajectory reference, schema/engine, and visible model names but not the same complete identifier set. |
| Evidence | Replay evidence included every Scenario N field. Mission-window evidence lacked a separately labeled element checksum and explicit frame/geodetic identifier. |
| User impact | Reviewers must infer which fields are equivalent across products. |
| Safety/scientific impact | Existing references remain deterministic; this is consistency and discoverability friction. |
| Smallest correction | Document or align the evidence labels in a future evidence-presentation review without changing scientific schemas casually. |
| Blocks Solo Alpha continuation | No. |

## Security observations

- All HTML success and error responses inspected carried the restrictive CSP and browser
  security headers.
- The replay controller loaded from `http://127.0.0.1:8000/assets/trajectory-replay.js`
  with HTTP 200, JavaScript content type, `nosniff`, and `Cache-Control: no-store`.
- Normal replay produced no CSP violation and no page exception.
- An injected inline script did not execute. Chrome reported that `script-src 'self'`
  blocked it.
- `connect-src 'none'` remained present.
- No fetch, XHR, WebSocket, EventSource, external script, font, map, tile, or CDN request
  occurred.
- The only incidental console error was a same-origin `/favicon.ico` HTTP 404 on the
  reviewer page. It was cosmetic and separate from the scientific workflow.
- Script, image-handler, template-breakout, Windows path, POSIX path, Authorization,
  Cookie, NaN, Infinity, invalid UTC, overlong duration, 90 deg elevation, unknown
  catalog, both-mode, neither-mode, duplicate-field, unexpected-field, and oversized-body
  probes all failed closed.
- Probe statuses were HTTP 422 except the oversized body, which returned HTTP 413.
- No probe returned executable markup, reflected sensitive markers, a traceback, raw TLE,
  local path, environment value, silent fallback, or partial scientific result.

## Scientific-claim observations

The product consistently described outputs as predicted geometry from pinned orbital
elements. "Not live tracking" is prominent on the form and replay. Mission windows state
that optical visibility is not assessed and that the result is not certified for command,
collision, or safety decisions. Replay states that the map is schematic, UTC approximates
UT1, external EOP/polar-motion corrections are absent, altitude is WGS84 ellipsoid-relative,
and no universal position-error guarantee exists.

No page claimed a current true position, 100 percent accuracy, guaranteed visibility,
collision probability, maneuver guidance, command readiness, approval, or certification.
The scientific weakness observed was interpretive rather than computational: source age is
shown accurately but its practical significance is not explained close to the value.

## Accessibility/mobile observations

- At 390 x 844, both form and replay had `scrollWidth == clientWidth == 390`; no page-level
  horizontal overflow occurred.
- Workbench action buttons remained separate, the SVG scaled to 334 px, the timeline to
  336 px, and evidence to 370 px.
- Scientific cards remained legible. No element required excessive horizontal scrolling.
- The Workbench link was the second Tab stop on `/review` after the bundled-sample button.
- Form focus order followed source, observer, interval, both actions, and return link.
- Radio selection followed native group behavior; replay controls, slider, and details were
  keyboard-operable with no trap.
- Focus used a visible 3 px outline on replay controls.
- Reduced-motion replay remained paused at sample 1 for the observation period.
- JavaScript-disabled static content was useful, but U43A-02 records the misleading inert
  controls.

## Evidence/provenance observations

Replay Method and evidence was collapsed by default and included:

- input and result references;
- source and element checksums;
- source reference;
- schema and engine versions;
- propagator, frame/geodetic, and observer-geometry identifiers;
- exact interval, 15-second sample interval for the one-hour live browser replay, and the
  2,001-sample bound;
- observer coordinates;
- the full limitation set.

The input/result references, checksums, exact request, and fixed limitations are useful to a
reviewer. Raw engine strings are useful for audit but too technical for a normal user, which
supports keeping them collapsed. Critical no-live, optical-visibility, and authority
limitations are also visible outside the details section, so they are not hidden too deeply.
U43A-06 records the remaining cross-result consistency issue.

## Persistence/network verification

### Database

The SQLite database contained 73 tables. Before and after the browser session, the same 14
tables were non-empty with exactly the same counts:

| Table | Before | After |
| --- | ---: | ---: |
| `alembic_version` | 1 | 1 |
| `artifact_records` | 20 | 20 |
| `audit_events` | 84 | 84 |
| `missions` | 11 | 11 |
| `observation_opportunities` | 4 | 4 |
| `optimization_problems` | 1 | 1 |
| `orbital_element_records` | 10 | 10 |
| `orbital_samples` | 310 | 310 |
| `provenance_records` | 10 | 10 |
| `scheduling_constraints` | 3 | 3 |
| `source_definitions` | 5 | 5 |
| `source_policies` | 5 | 5 |
| `verification_findings` | 90 | 90 |
| `workflow_runs` | 10 | 10 |

All other tables remained at zero, including `source_fetches`, `source_cache_entries`, and
all governed-research tables. Workbench and replay caused no database write.

### Files

| Area | Before | After |
| --- | --- | --- |
| Artifacts | 227 files, 3,299,406 bytes | 227 files, 3,299,406 bytes |
| Source cache | 1 file (`.gitkeep`), 150 bytes | 1 file (`.gitkeep`), 150 bytes |
| Tracked working tree | Clean | Clean before report creation |

No screenshot, trace, browser output, artifact, provider payload, or raw TLE was written to
the repository. Uvicorn startup and access logs were temporary process output, not persisted
application state.

### Network

The normal browser replay request set was limited to:

- same-origin `GET /workbench`;
- same-origin `POST /workbench/replay`;
- same-origin `GET /assets/trajectory-replay.js`.

No external origin was contacted. The 24-hour request used the bundled catalog and produced
no source fetch or cache write.

## Deferred public-deployment controls

This Solo Alpha verdict does not authorize production or public-alpha use. The following
remain deferred and were not evaluated as implemented:

- HTTPS termination and transport policy;
- trusted host and origin configuration;
- authentication and owner authorization;
- CSRF strategy for browser forms;
- rate limiting and abuse protection;
- public-provider rights and guarded live-source operations;
- operational logging, monitoring, and alerting;
- retention and disk cleanup operations;
- dependency and security scanning;
- backup, rollback, and deployment review.

## Final verdict

**PASS WITH REQUIRED FIXES**

OrbitMind is suitable for continued local Solo Alpha use. The deterministic offline workflow
completed, safety claims remained bounded, security probes failed closed, CSP blocked inline
execution, no external network request occurred, and no database/artifact/cache write was
introduced by Workbench or replay.

No P0 or P1 issue was observed. The three P2 findings should be corrected before expanding
to external reviewers: preserve a request-local path from windows to replay, make the
JavaScript-disabled controls unmistakably unavailable, and explain source-age significance
near the displayed value.

This verdict is not production readiness, public-alpha readiness, certified tracking,
operational authority, or approval for live-provider use.

## Recommended next slice

Run one small, reviewed U4.3B usability correction slice limited to the three P2 findings:

1. Add a safe POST-only "Replay this request" handoff without persistence, URLs, or raw-TLE
   exposure.
2. Hide or disable replay controls until the local controller initializes, preserving the
   static no-JavaScript result.
3. Add concise, scientifically honest source-age interpretation without universal accuracy
   thresholds.

Keep U43A-04 through U43A-06 as non-blocking presentation/evidence follow-ups. Do not combine
this correction with live providers, authentication, deployment, schema changes, or new
scientific calculations.

## U4.3B follow-up status (2026-07-12)

This note records correction status without changing the historical session observations or
verdict above.

- U43A-01 is resolved for bundled catalog requests. Successful catalog results now provide a
  POST-only `Replay this request` handoff carrying the same allowlisted catalog identifier,
  observer, UTC interval, duration, and threshold. It adds no persistence or browser storage.
- U43A-01 remains blocked for request-local custom TLE input. The existing opaque checksum
  identity cannot reconstruct raw orbital elements, and the raw TLE cannot safely be placed in
  HTML, a URL, JavaScript, browser storage, or an unsigned token. The result now states this
  limitation and does not substitute a catalog object.
- U43A-02 is resolved. Replay controls render disabled and the same-origin controller enables
  them only after required elements and the complete embedded payload validate successfully.
- U43A-03 is resolved. Mission-window and replay source-age values now share the same nearby
  plain-language explanation without thresholds, scores, or freshness certification.
- U43A-04, U43A-05, and U43A-06 remain unchanged and open as P3 findings.

A future custom-TLE handoff requires a separately reviewed design. The smallest credible option
would need bounded, expiring, single-use, owner-bound server-side state; no such session or
authorization contract exists in U4.3B.
