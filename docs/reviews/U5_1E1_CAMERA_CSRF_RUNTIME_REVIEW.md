# U5.1E1 Camera CSRF and Runtime-Root Architecture Review

Status: architecture review complete
Branch: `feature/u5-1a-local-camera-creation-studio`
Base and HEAD: `a0c0be9009ff61880306946b381230a7ac665e4c`

## Gate Identity

U5.1E-R was blocked because raw camera-media mutation required a session-bound CSRF
authority that did not exist and because the packaged runtime temp root did not reach
application services. U5.1E1 is documentation-only. It defines those contracts without
adding production code, tests, routes, storage, persistence, migrations, dependencies,
or frontend behavior.

## Files Inspected

- `README.md`
- `AGENTS.md`
- `src/orbitmind/api/app.py`
- `src/orbitmind/api/container.py`
- `src/orbitmind/api/deps.py`
- `src/orbitmind/api/errors.py`
- `src/orbitmind/api/transient_handoff.py`
- `src/orbitmind/api/routers/workbench.py`
- `src/orbitmind/api/assets/camera_preview.js`
- `src/orbitmind/core/config.py`
- `src/orbitmind/core/logging.py`
- `src/orbitmind/runtime/configuration.py`
- `src/orbitmind/runtime/launcher.py`
- `src/orbitmind/runtime/paths.py`
- `src/orbitmind/runtime/server.py`
- `docs/architecture/LOCAL_CAMERA_CREATION_STUDIO.md`
- `docs/architecture/CUSTOM_TLE_TRANSIENT_HANDOFF_ARCHITECTURE.md`
- `tests/conftest.py`
- `tests/test_browser_security_headers.py`
- `tests/test_custom_tle_transient_handoff.py`
- `tests/test_camera_preview_sandbox.py`
- `tests/test_windows_runtime.py`
- `tests/test_schema_provisioning_startup.py`
- `tests/test_architecture_boundaries.py`

## Current Security Findings

### Host

The current custom-TLE protocol validator uses raw ASGI headers, rejects forwarded
headers, and requires one exact Host of `127.0.0.1:<configured-port>` plus scheme
`http`. It rejects aliases, duplicate Host values, and wrong ports before handoff state
is created or consumed. This is a valid convention for the camera validator, but the
existing function is handoff-specific and is not itself a camera CSRF subsystem.

### Origin

The same validator requires exactly one Origin equal to the canonical selected
loopback origin. It rejects absent, null, duplicate, malformed, alternate-host,
alternate-port, and alternate-scheme values. There is no CORS or missing-Origin
fallback.

### Fetch Metadata

Exactly one `Sec-Fetch-Site: same-origin` value is required. Missing, duplicate,
same-site, cross-site, and none values fail. This remains defense in depth and is not
treated as browser identity because non-browser clients can forge it.

### Cookies and Sessions

OrbitMind currently issues `orbitmind_handoff_session` only for the explicitly enabled
custom-TLE handoff. It is HttpOnly, SameSite Strict, host-only, scoped to `/workbench`,
and not Secure on the approved loopback HTTP origin. Its application-scoped store uses
injected clocks and randomness, keyed session binding, a lock, bounded capacity, fixed
errors, and shutdown clearing.

The camera GET currently issues no cookie. The handoff session is purpose-specific and
cannot be reused as a camera page session.

### CSRF

There is no reusable session-bound CSRF token, CSRF header validator, rotation
contract, token registry, or camera mutation route. Existing Host, Origin, Fetch
Metadata, SameSite cookie, and form-action CSP controls do not satisfy the U5.1A camera
raw-body requirement. The custom-TLE handoff token is replay capability, not CSRF.

## Selected CSRF Design

- Camera page-session ID: independent 32-byte CSPRNG value, unpadded base64url, cookie
  only.
- Server page binding: HMAC-SHA-256 under an independent process-only 32-byte key; no
  raw cookie in records.
- CSRF token: independent 32-byte CSPRNG value, unpadded base64url.
- Token storage: SHA-256 digest only, compared with `hmac.compare_digest`.
- Delivery: one inert `<meta name="orbitmind-camera-csrf">` value in no-store camera
  HTML.
- Browser storage: private JavaScript memory only; no localStorage, sessionStorage,
  IndexedDB, Cache Storage, URL, query, cookie, or asset embedding.
- Request header: `X-OrbitMind-Camera-CSRF`.
- Next-token response header: `X-OrbitMind-Camera-CSRF-Next`.
- Public error: HTTP 403, `camera_request_csrf_invalid`, without branch detail.
- Lifetime: absolute maximum 900 seconds under an injected UTC clock, no sliding use.
- Capacity: 16 active sessions, lazy expiry, no valid-session eviction.

## Selected Cookie Attributes

Exact cookie name: `OrbitMind-Camera-Page`

- `HttpOnly`
- `SameSite=Strict`
- `Path=/workbench/camera`
- `Max-Age=900`
- host-only, with no `Domain`
- `Secure` omitted only for exact loopback HTTP

The cookie contains only the opaque page-session ID. It contains no token, media
capability, owner, timestamp, path, or camera information.

## Secure-Cookie Decision

The current runtime is HTTP on `127.0.0.1`. This review does not claim that all
supported browsers accept a Secure cookie on that origin. The selected internal
loopback contract therefore omits `Secure`, documents that limitation, and forbids use
outside exact loopback HTTP. HTTPS or broader deployment requires a new review and a
Secure cookie. HttpOnly and SameSite Strict remain mandatory.

## Endpoint Path Decision

`Path=/workbench/camera` does not cover the earlier conceptual `/api/v1/...` routes.
Broadening the cookie to `/` was rejected. U5.1E-R must keep page-session-dependent
media endpoints under `/workbench/camera/api/...`. This is the narrow route refinement
needed to make the cookie contract internally consistent; no endpoint is added here.

## Selected Rotation and Replay Policy

After Host, Origin, Fetch Metadata, cookie, token, expiry, generation, and route checks
pass, the registry atomically replaces the current token digest before any body read or
media mutation. It rotates on every accepted modifying request, including later media
validation or internal failure. Every post-acceptance response returns the next token
only in `X-OrbitMind-Camera-CSRF-Next`; pre-acceptance failures return none.

The old token fails immediately and no prior-token grace exists. If a rotated response
is lost, the page cannot modify until reload. There is no token recovery endpoint or
cookie-only recovery.

## Selected Concurrency Policy

The frontend serializes modifying requests. The application-scoped registry also
performs validation and rotation under synchronization. One token generation can be
accepted once; concurrent replay gets the same generic 403 and cannot receive a second
next token. Deterministic tests use barriers, not sleeps.

## Page Lifecycle Decision

Every camera GET creates a fresh pair and invalidates a prior submitted camera-page
session. Because tabs share cookies, this intentionally permits only the newest tab to
modify. Reload obtains a new pair. A persisted back-forward-cache page disables
modifying controls until full reload. Page close does not claim immediate registry
deletion. Application restart and shutdown invalidate all sessions.

## Media-Capability Separation

Session creation requires CSRF. Status retrieval is non-modifying and requires the
separate media capability. DELETE requires both current CSRF and the correct media
capability. Neither value can substitute for the other, and their generators, digest
fields, headers, and lifecycle records remain independent.

## Runtime-Root Injection Decision

The approved production root is exactly:

```text
RuntimePaths.temp_dir / "camera-sessions"
```

A camera-owned immutable `CameraMediaRuntimeContext` is constructed at the packaged
launcher composition boundary from the already resolved `RuntimePaths`. It carries
the resolved temp and media roots, fixed clock/generator dependencies, and an optional
narrow filesystem adapter. The future launcher passes it explicitly to `AppContainer`.
The API does not import, reread, or reconstruct `RuntimePaths`.

Containment is strict: the resolved media root must be the exact direct child of the
resolved runtime temp root. No request, setting, environment reread, current working
directory, or user path can change it. If context is absent, backend camera media is
unavailable; there is no LocalAppData or TEMP fallback. Tests inject an isolated
`tmp_path` context.

## Lifecycle Ownership

FastAPI lifespan and its active `AppContainer` own initialization and shutdown.
Startup validates containment, initializes CSRF and media registries, creates only the
approved directory, and cleans only recognized stale entries before readiness.
Unknown files are not removed. Unsafe or unwritable roots fail startup closed.

Requests receive the initialized service from the container and do not resolve paths.
Shutdown rejects new work, closes handles, deletes registered ephemeral media, clears
capability and CSRF digests, closes registries, leaves unknown files untouched, and
records bounded cleanup failures without paths or secrets.

## Required Future Tests

The architecture document freezes the complete CSRF A-AE matrix and runtime-root
matrix. The required themes are:

- exact cookie, inert token delivery, and no browser persistence;
- Host/Origin/Fetch/cookie/header composition and stable errors;
- digest-only storage and constant-time comparison;
- accepted-request rotation, replay rejection, concurrency, and lost responses;
- reload, multiple tabs, bfcache, expiry, capacity, shutdown, and restart;
- independent media capability on status and DELETE;
- exact root derivation, containment, no environment or working-directory reread;
- startup, recognized stale cleanup, unknown-file preservation, shutdown, and no
  cross-application singleton;
- fixed clocks, deterministic generators, isolated temp roots, no physical camera,
  and no external network.

## Unresolved Blockers

No architecture choice remains open for U5.1E-R. Implementation is still blocked
until a separate approval authorizes production and test changes. The implementation
must use the refined camera endpoint namespace and must not silently broaden cookie
scope, retain old-token grace, or add a runtime-root fallback.

## Scope Confirmation

- Production source changed: no.
- Tests changed: no.
- Existing U5.1A-U5.1E0 files changed by this gate: no.
- Dependency or lock changed: no.
- API route added: no.
- Media storage or persistence added: no.
- Migration, model, agent, or external-AI change: no.
- Camera frontend changed: no.
- Physical camera accessed: no.
- Staging, commit, push, or PR: no.

## Review Decision

The exact CSRF cookie, token, validation, rotation, concurrency, lifecycle, capability,
and runtime-root contracts are closed. The recommended next gate is a rerun of U5.1E-R
under explicit approval to implement these reviewed decisions.

Decision: `READY TO RERUN U5.1E-R WITH APPROVED CSRF CONTRACT`
