# U5.1A Camera Creation Studio Architecture Review

Status: architecture review complete; implementation not started.

## Gate Identity

- Branch: `feature/u5-1a-local-camera-creation-studio`
- Base branch: `main`
- Base and current HEAD: `a0c0be9009ff61880306946b381230a7ac665e4c`
- Scope: documentation and review only
- Product boundary: one explicitly captured local still frame becomes a reviewable
  proposal; no automatic action

## Files Inspected

Architecture, security, and packaging:

- `README.md`
- `docs/architecture/SYSTEM_ARCHITECTURE.md`
- `docs/architecture/MODULE_BOUNDARIES.md`
- `docs/architecture/LOCAL_RUNTIME_ARCHITECTURE.md`
- `docs/architecture/GOVERNED_LOCAL_PORT_SELECTION.md`
- `docs/security/BROWSER_SECURITY_BASELINE.md`
- `pyproject.toml`
- `requirements/u5.0b0-windows-py312.lock.txt`
- `packaging/orbitmind.spec`
- `scripts/build_windows_poc.ps1`
- `scripts/verify_windows_poc.ps1`
- external U5.0I2L installer source, read-only and outside Git

API, Workbench, ownership, runtime, persistence, and provenance:

- `src/orbitmind/api/app.py`
- `src/orbitmind/api/container.py`
- `src/orbitmind/api/deps.py`
- `src/orbitmind/api/transient_handoff.py`
- `src/orbitmind/api/routers/workbench.py`
- `src/orbitmind/api/routers/review.py`
- `src/orbitmind/api/assets/trajectory_replay.js`
- `src/orbitmind/runtime/configuration.py`
- `src/orbitmind/runtime/paths.py`
- `src/orbitmind/core/config.py`
- `src/orbitmind/core/paths.py`
- `src/orbitmind/governance/provenance.py`
- `src/orbitmind/persistence/database.py`
- `src/orbitmind/persistence/models.py`
- `src/orbitmind/persistence/observation_planning_models.py`
- `src/orbitmind/persistence/research_models.py`
- `src/orbitmind/visualization/models.py`

Existing tests inspected:

- `tests/test_mission_workbench.py`
- `tests/test_trajectory_replay_workbench.py`
- `tests/test_browser_security_headers.py`
- `tests/test_reviewer_sandbox.py`
- `tests/test_custom_tle_transient_handoff.py`
- `tests/test_architecture_boundaries.py`
- `tests/unit/test_paths.py`
- `tests/unit/test_artifacts.py`
- `tests/test_windows_packaging_sources.py`

## Current Workbench Architecture

`src/orbitmind/api/app.py` constructs one FastAPI application, installs HTML security
headers in middleware, and includes the Workbench router. The Workbench router serves:

- `GET /workbench` as server-rendered HTML;
- bounded URL-encoded POST routes for mission-window and replay operations;
- a single exact JavaScript resource route at `/assets/trajectory-replay.js`;
- inline page CSS and one same-origin external replay controller;
- no template directory, generic static mount, or frontend framework.

`/workbench/camera` fits the current Workbench route and security-header scope. The
recommended implementation is a separate camera router and controller asset so the
large mission Workbench module does not acquire camera authority. Shared presentation
styles may be reused without allowing the mission router to access media devices.

The local launcher uses `http://127.0.0.1:<selected-port>/workbench`. Standards and
current browsers treat loopback HTTP origins as potentially trustworthy for secure
context checks, so `getUserMedia` is architecturally viable. Physical browser and OS
permission behavior remains unproven until U5.1H.

## Current CSP

The current policy is:

```text
default-src 'none';
script-src 'self';
style-src 'unsafe-inline';
img-src 'self' data:;
font-src 'none';
connect-src 'none';
object-src 'none';
base-uri 'none';
frame-ancestors 'none';
form-action 'self';
worker-src 'none';
media-src 'none';
manifest-src 'none'
```

Same-origin packaged JavaScript is already allowed. Inline executable JavaScript,
`eval`, external fetches, workers, frames, objects, and external form actions remain
blocked. The camera page must preserve those restrictions. Browser tests must decide
whether its local `MediaStream` preview can retain `media-src 'none'` or needs a
route-specific minimum `media-src` exception. No global relaxation is justified.

## Current Permissions-Policy

Current HTML responses use:

```text
geolocation=(), microphone=(), camera=(), payment=(), usb=(),
magnetometer=(), gyroscope=(), accelerometer=()
```

Camera access is therefore intentionally denied today. A future camera page needs a
route-specific `camera=(self)` or narrower verified equivalent. Every other HTML page
must retain `camera=()`, and `microphone=()` remains denied everywhere.

## Current Upload and Request-Boundary Support

- Workbench forms are URL encoded and streamed into a 4,096-byte bound.
- The custom-TLE handoff uses a stricter 512-byte streamed reader with exact content
  type, content length, transfer encoding, Origin, and Fetch Metadata validation.
- Reviewer forms use fixed small body limits.
- No `UploadFile`, file-form route, generic binary-upload service, or multipart parser
  exists.
- `python-multipart` is absent from project dependencies and the approved lock.
- `multipart/form-data` is explicitly rejected by the transient handoff.

The recommended camera protocol sends one raw `image/jpeg` or `image/png` body to an
already owner-bound ephemeral session and uses bounded JSON for metadata. This avoids
adding multipart solely for one file while reusing the repository's bounded streaming
pattern.

## Current Temporary-Storage Capability

The API has a bounded, process-local custom-TLE handoff store with expiry, session
binding, capacity limits, fixed diagnostics, and shutdown clearing. It stores typed
text data in memory, not binary media. Runtime paths include an approved per-user
`temp` directory, but no camera/media temporary store, restart cleanup protocol, or
deletion audit exists.

Therefore temporary media support does not exist yet. U5.1E needs a dedicated service
with generated paths, containment checks, 15-minute expiry, startup/shutdown cleanup,
and honest deletion status.

## Current Persistence and Ownership Support

OrbitMind has SQLAlchemy repositories, SQLite migrations, per-request sessions,
checksummed artifact metadata, and user-scoped runtime directories. Newer planning
and research schemas use `owner_id` and composite owner relationships. The API owner
dependency currently returns a trusted single-user principal, `local-owner`, and
explicitly forbids request bodies from supplying authoritative ownership.

There is no authentication or multi-tenant identity boundary. Legacy mission artifact
records and `/review/artifacts/{mission_id}/{filename}` are UUID/filename allowlisted
and path-contained, but are not owner-scoped. Camera media must therefore use a new
owner-scoped repository and retrieval boundary rather than the legacy artifact route.

## Current Provenance Support

The existing domain and persistence layers support evidence references, method/source
identity, input checksums, UTC generation times, artifact checksums, and epistemic
status in multiple scientific flows. These patterns are suitable foundations, but no
camera capture, retention, deletion, user-edit, or model-interpretation provenance
contract exists.

Camera provenance must distinguish deterministic media facts from visual observation,
user context, model interpretation, inference, uncertainty, and independent
verification status. A proposal remains a draft regardless of provenance completeness.

## Browser Reviewer Sandbox

The reviewer and Workbench are local server-rendered surfaces, not public deployment
boundaries. They escape user content, bound request bodies, sanitize errors, prevent
raw path disclosure, allowlist artifact filenames, and reject traversal. The
Workbench's transient handoff adds exact Host/Origin/Fetch-Metadata/cookie/token
controls for one sensitive same-origin flow.

Those controls are useful precedents, not a complete camera security layer. Camera
mutations still require dedicated CSRF tokens, owner-scoped sessions, binary decoder
limits, and no arbitrary media serving.

## Dependency Findings

| Capability | Current finding | Architecture decision |
| --- | --- | --- |
| Browser capture | Native MediaDevices/video/canvas APIs available in supported browsers | Use native APIs; no capture library |
| Multipart | No project or lock dependency | Prefer one raw bounded frame endpoint |
| Pillow | Present only transitively through Matplotlib in the Windows lock | Review promotion to direct dependency for U5.1E |
| OpenCV | Absent | Do not add for capture or basic validation |
| Hashing/IDs/files | Python standard library sufficient | Reuse with path containment and atomic writes |
| Semantic vision | No approved local component | Defer selection; do not imply interpretation exists |

No dependency was added or changed in U5.1A.

## Storage and Migration Assessment

Browser preview and browser-memory capture require no storage or migration. U5.1E
will need a new temporary-media facility and restart-aware session metadata. U5.1G
requires durable owner-scoped camera session/media/proposal/retention/provenance
records. At least one Alembic migration is expected before backend persistence is
enabled.

Binary media should remain under generated paths in the per-user runtime root. The
database stores metadata, checksums, relationships, relative locators, retention, and
deletion outcomes. No migration was created in this gate.

## Frozen and Installer Implications

- Browser permission and capture occur in the system browser; no native camera driver
  belongs in the Python launcher.
- The current PyInstaller spec explicitly includes only `trajectory_replay.js` from
  API assets. A separate camera controller asset must be explicitly included and
  statically audited in a later packaging gate.
- A future direct image-decoder dependency must be included in the lock, wheelhouse,
  PyInstaller graph, warnings audit, and offline build evidence.
- The installer recursively packages the frozen one-folder candidate. It should not
  request device permission, elevation, firewall changes, services, or camera options.
- Installed camera permission, track cleanup, offline behavior, and browser/device
  compatibility require physical testing in U5.1H and an installer refresh afterward.

The current frozen candidate and installer were not modified or executed by U5.1A.

## Privacy and Authority Review

The architecture satisfies the review boundary:

- permission is user-triggered and never agent-triggered;
- camera-active state and Stop control are mandatory;
- only one still frame is accepted;
- audio, recording, continuous analysis, identity, biometric, emotion, and sensitive
  inference features are prohibited;
- frame bytes remain browser-memory-only until an explicit proposal/save action;
- persistence and downstream tasks require separate approvals;
- people-in-frame notice and neutral non-identifying output are required;
- external frame processing is prohibited;
- visual text cannot grant authority or trigger tools;
- deletion status must remain honest.

## Threat and Test Review

The architecture document maps every required threat to a boundary, mitigation,
fail-closed outcome, and deterministic test. The matrix covers covert capture,
retention after discard, abandoned tracks, prompt injection, malformed/decompression
images, MIME spoofing, owner bypass, CSRF, file write/serve, path disclosure, model
overclaim, external upload, person identification, third-party scripts, memory
exhaustion, replay, stale media, and agent escalation.

Automated media tests must mock browser APIs. Real permission and hardware tests are
explicitly deferred to U5.1H.

## Implementation Plan

1. `U5.1B` - immutable camera session, goal, error, retention, and provenance contracts.
2. `U5.1C` - explicit local preview, active state, stop, and cleanup; no upload.
3. `U5.1D` - one browser-memory still frame with retake/discard; no persistence.
4. `U5.1E` - owner-scoped bounded upload, image validation, temporary store, expiry.
5. `U5.1F` - bounded local proposal workflow and epistemic output; no automatic action.
6. `U5.1G` - explicit save/delete, durable provenance, retention visibility.
7. `U5.1H` - frozen packaging, physical camera, privacy/cleanup, and installer tests.

The recommended next slice is U5.1B. It introduces typed contracts and deterministic
tests only. It does not access a camera or add browser media code.

## Unresolved Decisions

- Which local semantic vision component, if any, is permitted for proposal creation.
- Whether ephemeral backend session metadata is database-backed in U5.1E.
- Exact durable schema and relationship to legacy artifact records.
- Exact route-specific `media-src` policy proven across supported browsers.
- Whether saved frames are deterministically re-encoded and which metadata fields are
  preserved.
- Saved-media default retention duration and delete-retry policy.
- Supported browser/device matrix and camera-label presentation.
- Whether external connected vision will ever receive a separate approval.

None blocks U5.1B because that slice defines contracts only.

## Scope Confirmation

- Production code changed: no.
- Tests changed: no.
- Dependencies changed: no.
- Lock changed: no.
- Migration changed: no.
- Packaging or installer behavior changed: no.
- Camera or microphone permission requested: no.
- Frame captured: no.
- External AI or media service called: no.
- Frozen candidate or installer modified: no.
- Files changed by this gate: the architecture document and this review document only.

## Review Decision

`READY FOR U5.1B CAMERA SESSION CONTRACT APPROVAL`
