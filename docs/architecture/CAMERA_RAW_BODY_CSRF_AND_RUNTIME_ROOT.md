# Camera Raw-Body CSRF and Runtime-Root Architecture

Status: approved design for U5.1E-R implementation review
Scope: local loopback camera-media requests and application-scoped ephemeral storage
Implementation status: architecture only; no route, service, storage, or frontend change is made here

## Problem Statement

U5.1D keeps a captured still entirely in browser memory. U5.1E-R will introduce the
first raw camera-media request that can create or delete backend ephemeral state. The
current local Workbench has strong loopback protocol checks, but it has no reusable
session-bound CSRF token for a JavaScript raw-body request. The packaged runtime also
owns `RuntimePaths.temp_dir`, while the API container currently receives only settings
derived from selected runtime paths. Request handlers therefore have no approved,
application-scoped camera-media temporary root.

This document closes both boundaries before implementation. It defines a camera-page
CSRF authority that is separate from media capability authority and an immutable
runtime context that carries the approved temporary root from launcher composition to
the application container. The design remains local, single-user, offline, in-memory,
and fail-closed.

## Existing Security Findings

The current repository provides the following relevant controls:

- `src/orbitmind/api/routers/workbench.py::_validate_handoff_protocol` examines raw
  ASGI headers, rejects forwarded-header families, requires exactly one Host equal to
  `127.0.0.1:<selected-port>`, requires scheme `http`, requires exactly one canonical
  Origin, and requires exactly one `Sec-Fetch-Site: same-origin` value.
- The selected port is represented by runtime configuration and is copied into
  `Settings.custom_tle_handoff_port`; the camera contract must receive the same
  selected authority without rereading the environment in a request.
- HTML middleware applies a restrictive CSP, `X-Content-Type-Options`, frame denial,
  referrer policy, and permissions policy. The camera page already has a route-specific
  camera permission and a same-origin package script.
- The current camera GET issues no cookie, contains no CSRF token, and has no modifying
  backend route. Its script performs no network request.
- The custom-TLE handoff issues one `HttpOnly`, `SameSite=Strict`, host-only, process-
  local session cookie and uses a bounded `threading.Lock`-protected registry with
  injectable clocks and randomness. That store is purpose-specific and is not a CSRF
  service.
- `AppContainer` is created once, is stored on `app.state.container`, and owns mutable
  services through FastAPI lifespan. Tests replace it directly. Shutdown clears the
  transient handoff and disposes the database.
- `RuntimePaths.temp_dir` is exactly `<runtime-root>/temp`, is prepared by the launcher,
  and is replaceable through `RuntimePaths.from_local_app_data(injected_root=...)` or an
  injected `paths_factory`. It is not currently carried into `AppContainer`.
- Safe browser errors use fixed messages. Application errors do not expose stack
  traces, paths, headers, or request bodies. JavaScript assets use `Cache-Control:
  no-store`.

These controls are reusable conventions, not an existing camera CSRF implementation.
The custom-TLE handoff token is single-purpose replay authority and must never be
treated as a camera CSRF token.

## Trust Boundaries

1. **Loopback transport boundary.** OrbitMind accepts the one canonical HTTP origin
   `http://127.0.0.1:<selected-port>`. Hostnames, IPv6, alternate IPv4 spellings,
   proxy headers, and public interfaces are outside the boundary.
2. **Browser page boundary.** A server-rendered camera page receives one short-lived
   token. Same-origin camera JavaScript may read that token from inert HTML and keep it
   in memory. Other origins, browser storage, URLs, and logs may not receive it.
3. **Camera page-session boundary.** A host-only `HttpOnly` cookie correlates the
   browser request with one in-memory server record. It is not authentication,
   tenancy, or physical-camera permission.
4. **Media capability boundary.** A separate high-entropy capability authorizes
   access to one ephemeral media session. It does not satisfy CSRF checks.
5. **Filesystem boundary.** Only the exact injected `camera-sessions` child of the
   packaged runtime temp directory is writable for camera media. Requests cannot
   select or recompute it.
6. **Application lifecycle boundary.** The FastAPI lifespan and its `AppContainer`
   own initialization and shutdown. No module-level mutable singleton survives an
   application instance.

## Threat Model

| Threat | Trust boundary | Mitigation | Failure behavior | Deterministic test |
| --- | --- | --- | --- | --- |
| Cross-site raw-body submission | Loopback and browser | Exact Host, Origin, Fetch Metadata, cookie, and header token; no CORS | 400 or generic 403 before body read or mutation | Submit cross-origin headers and assert no service call |
| Malicious local webpage targeting `127.0.0.1` | Browser | `SameSite=Strict`, non-simple CSRF header, exact Origin, no CORS | `camera_request_csrf_invalid` or protocol rejection | Same-site/cross-site matrix with a valid-looking body |
| Missing or forged Origin | Loopback | Exactly one byte-exact canonical Origin | Generic 403, no lookup or body read | Missing, null, duplicate, alias, and wrong-port cases |
| Forged or absent Fetch Metadata | Browser | Exactly one lower-case `same-origin` value | Generic 403, no state access | Missing, duplicate, same-site, cross-site, and none |
| Token stolen without cookie | Page session | Independent cookie binding plus token digest | Generic 403 | Valid token with absent and different cookies |
| Cookie stolen without token | Page session | Independent 256-bit token in header only | Generic 403 | Valid cookie with missing and wrong headers |
| Token replay | Registry | Atomic generation check and rotate-on-acceptance | First accepted; subsequent request generic 403 | Two sequential uses of one generation |
| Reuse after rotation | Registry | Previous digest is replaced atomically | Generic 403 | Old token after successful and media-error responses |
| Use after expiry | Registry | Absolute injected-UTC expiry, maximum 900 seconds | Generic 403 | Advance fixed clock to exact boundary |
| Token from another page session | Page session | Token digest is stored in one cookie-bound record | Generic 403 | Cross-pair two cookies and two tokens |
| Token from another camera tab | Page lifecycle | New camera GET invalidates the prior page session | Generic 403; stale tab must reload | Open two page sessions and use the first token |
| Leakage through URL, logs, error, or history | Browser and diagnostics | Meta delivery and dedicated headers only; fixed errors; redacted events | No token reflection | Scan response, URL, logs, and event fields |
| Capability confused with CSRF | Authority separation | Distinct generators, names, records, and headers | Generic 403 or capability denial | Swap the two values in each header |
| Simultaneous modifying requests | Registry concurrency | Frontend serialization and atomic server rotation under a lock | At most one generation accepted | Barrier-based concurrent requests without sleeps |
| Stale back-forward-cache page | Browser lifecycle | Disable modification on persisted `pageshow`; require reload | No request is sent while stale | Dispatch `pageshow` with `persisted=true` |
| Page reload | Browser lifecycle | Invalidate submitted prior page session and issue a fresh pair | Old token fails; new pair works | GET twice with the shared cookie jar |
| Server restart | Application lifecycle | Registry and process binding key are memory-only | Every prior pair fails | Create two app instances with the same presented values |
| Application shutdown | Application lifecycle | Close registry and clear records, digests, and process key | Later calls fail closed | Shutdown then inspect counts and operation failure |
| Temporary-root substitution | Filesystem | Immutable injected context and strict containment | Startup fails before route readiness | Inject sibling, parent, symlink escape, and file paths |
| Tests touching real user data | Test boundary | Explicit temp context is mandatory for camera service tests | Test construction fails when context is absent or unsafe | Assert all writes remain below `tmp_path` |

A compromised same-origin page, browser process, operating-system account, or OrbitMind
process remains outside this local control set. HTTPS, authentication, multi-user
authorization, and public deployment are non-goals.

## Camera Page-Session Model

### Identifier

For each successful `GET /workbench/camera`, the server generates a fresh camera
page-session identifier from exactly 32 bytes (256 bits) produced by the operating-
system CSPRNG. It is encoded as 43 unpadded base64url characters. It is opaque and is
carried only in the camera page cookie.

The raw page-session identifier is not a media-session ID, capability, owner name,
timestamp, path, or device identifier. It is not rendered, placed in the DOM, accepted
from a query, or logged.

The registry generates an independent 32-byte process binding key. Server records are
keyed by `HMAC-SHA-256(binding_key, page_session_id)`, not the raw cookie. The process
key and keyed digest are camera-CSRF state only; neither is shared with custom-TLE
handoff or camera-media capabilities. The key is cleared at shutdown, which also makes
all prior cookies useless after restart.

### Registry Record

One record contains only:

- the keyed page-session digest;
- the SHA-256 digest of the current CSRF token;
- an integer token generation starting at one;
- timezone-aware UTC `issued_at` and `expires_at` values;
- valid, closed, and rotation state needed for atomic operation;
- no plaintext cookie, token, capability, media path, or request content.

No prior-token grace record is retained. An unknown or expired record is never
silently replaced on a modifying request.

### Capacity and Lifetime

The registry permits at most 16 active page sessions. Before creating a session it
removes expired records while holding its synchronization lock. At capacity it does
not evict a valid session; the camera page GET returns a fixed sanitized 503 response
and creates neither a cookie nor token. Each record expires no later than 900 seconds
after issue. The expiry is absolute and never slides on use.

The UTC clock, page-session generator, CSRF generator, and process-key generator are
injected. Production defaults use timezone-aware UTC and `secrets.token_bytes`; tests
use fixed values without real time or randomness.

## CSRF Token Model

The CSRF token is generated independently from exactly 32 CSPRNG bytes (256 bits) and
encoded as 43 unpadded base64url characters. The registry stores only
`SHA-256(ascii_token)`. Validation hashes the presented token and compares fixed-length
digest bytes with `hmac.compare_digest` while the registry lock protects generation
state.

Plaintext exists only in the server response being constructed, the inert camera-page
HTML meta element, and the camera controller's private in-memory variable. It is never
persisted server-side or client-side and never appears in a URL, query, fragment,
cookie, request body, media bytes, capability header, `Authorization`, log, diagnostic
event, traceback, or browser storage.

## Browser Delivery and Storage

`GET /workbench/camera` creates a new page session and token, stores only their server
digests, and renders exactly one inert element:

```html
<meta name="orbitmind-camera-csrf" content="<opaque-token>">
```

The response is `Cache-Control: no-store`. The same-origin packaged camera controller
reads the value once and keeps it in a closure. It must not use `localStorage`,
`sessionStorage`, IndexedDB, Cache Storage, a service worker, a URL, a dataset mirrored
elsewhere, or a cookie. The token is not compiled into the JavaScript asset and no
inline executable JavaScript is added.

U5.1E-R will need the camera page's route-specific CSP to permit only same-origin
camera API fetches, for example `connect-src 'self'`. All unrelated HTML keeps
`connect-src 'none'`; no CORS header or external origin is introduced. This gate does
not make that frontend or CSP change.

## Cookie Contract

The exact cookie name is:

```text
OrbitMind-Camera-Page
```

Its attributes are:

- `HttpOnly`;
- `SameSite=Strict`;
- `Path=/workbench/camera`;
- `Max-Age=900`;
- no `Domain` attribute, so it is host-only;
- no readable timestamp or other structured value;
- `Secure` omitted for the approved loopback HTTP runtime.

The omission of `Secure` is a narrow compatibility decision, not a claim that the
cookie is transport-secure. OrbitMind currently serves `http://127.0.0.1`; a Secure
cookie is not assumed to work consistently for that HTTP origin across supported
browsers. The feature is forbidden outside exact loopback HTTP. Any HTTPS or broader
deployment requires a separate review and `Secure` must then be enabled. `HttpOnly`
and `SameSite=Strict` may not be weakened.

Cookie Path creates an endpoint constraint. A cookie at `/workbench/camera` is not
sent to the conceptual U5.1A `/api/v1/camera-sessions` paths. U5.1E-R therefore must
place its page-session-dependent endpoints under the same narrow namespace:

```text
POST   /workbench/camera/api/sessions
GET    /workbench/camera/api/sessions/{session_id}
DELETE /workbench/camera/api/sessions/{session_id}
```

This E1 contract refines the earlier conceptual route table. It deliberately avoids a
`Path=/` cookie. No route is added in this architecture gate.

## Request and Response Headers

Every modifying camera-media request carries the current token only in:

```text
X-OrbitMind-Camera-CSRF
```

After an accepted modifying request, the response carries the independently generated
next token only in:

```text
X-OrbitMind-Camera-CSRF-Next
```

The request token is never accepted from a query, form field, JSON, media bytes,
cookie alone, `Authorization`, or the media-capability header. The next token is never
placed in a response body, cookie, redirect, URL, or browser storage. The browser
replaces its in-memory value only after it receives a valid response with that exact
header.

## Modifying-Request Validation Order

The implementation uses one reviewed validator/dependency for every modifying camera
route. Its order is deterministic:

1. require exactly one Host equal to `127.0.0.1:<selected-port>`, scheme `http`, and
   no forwarded-header family;
2. require exactly one Origin equal to
   `http://127.0.0.1:<selected-port>`;
3. require exactly one `Sec-Fetch-Site: same-origin` value;
4. if `Content-Length` is present, require one canonical non-negative decimal value
   within the raw-body limit before any body read;
5. require the `OrbitMind-Camera-Page` cookie;
6. compute its keyed binding and locate one active page-session record;
7. require exactly one `X-OrbitMind-Camera-CSRF` header with the exact token shape;
8. hash the presented token and compare its digest in constant time;
9. verify absolute page-session expiry using the injected UTC clock;
10. verify that the record is valid and the token generation is current;
11. verify the exact route and method against the camera-CSRF modifying allowlist;
12. atomically accept the generation, rotate it, and invalidate the old digest;
13. only then stream, decode, or mutate camera-media state.

Step 4 is the only early size branch. A clearly oversized, duplicate, malformed, or
negative `Content-Length` returns one fixed sanitized 413 response, reads no body, and
performs no registry or media mutation. An absent `Content-Length` is allowed; after
CSRF acceptance, streaming enforces both observed-byte and protocol-overhead limits.
No image decode occurs before step 12.

Framework route matching may reject an unknown method or path before this dependency,
but no such route receives camera state. Tests and non-browser tools get no production
bypass: they must synthesize the exact Host, Origin, Fetch Metadata, cookie, and token.

## Origin and Fetch Metadata Composition

The token supplements rather than replaces current protocol checks. All modifying
requests require all of the following:

- exact canonical Host and HTTP scheme;
- no proxy or forwarded headers;
- exact canonical loopback Origin;
- exactly one `Sec-Fetch-Site: same-origin` value;
- current page-session cookie;
- current CSRF header token.

There is no wildcard Origin, `Origin: null`, `localhost`, IPv6, same-site exception,
missing-Origin fallback, public interface, automatic port fallback, or CORS support.
Fetch Metadata is defense in depth because a non-browser client can forge it. Cookie
and token possession are still mandatory.

## Expiry, Rotation, and Replay

### Rotation Point

Rotation occurs after the complete protocol and CSRF checks accept a modifying
request, but before any body read, image decode, or media mutation. Under the registry
lock, the server generates the next independent token, increments the generation,
replaces the stored digest, and invalidates the old token as one atomic operation.

This policy rotates for every accepted modifying request, including a request that
later receives a bounded media-validation or internal error. The next-token header is
therefore attached to every response produced after acceptance, including POST
success, DELETE 204, bounded media 4xx, and sanitized media 5xx. Protocol, size,
cookie, token, expiry, and allowlist failures occur before acceptance and return no
next token.

If next-token generation cannot complete before acceptance, media state is not read
or changed and the current generation remains authoritative. No partial rotation is
committed.

### Concurrency

The browser controller serializes modifying requests and has at most one in flight.
The server independently protects the registry with application-scoped
synchronization. Because rotation precedes media work, two concurrent requests using
one generation cannot both pass: one atomically receives the next generation and the
other gets `camera_request_csrf_invalid`. The server never emits two valid next tokens
for one generation.

Tests coordinate concurrent calls with barriers and events, never timing sleeps.

### Replay and Lost Responses

An old token fails immediately after acceptance. Repeated use, use after expiry, use
with a different cookie, and use after application restart all fail with the same
public response.

If the server rotates and the response is lost, the browser retains an invalid old
token. It must not roll the server back, fetch a token using cookie authority alone,
or use a recovery endpoint. Modifying controls remain unavailable until the user
reloads the camera page. This deliberate fail-closed desynchronization is acceptable
for an ephemeral local workflow.

## Page Reload, Multiple Tabs, and Back-Forward Cache

- Every camera page GET creates a new page-session ID and token.
- If the request carries a current camera-page cookie, the matching old record is
  invalidated before the new pair is committed. The response overwrites the cookie.
- Because browser tabs share this cookie, only the most recently loaded camera page
  in a browser profile can modify state. Earlier tabs retain stale tokens and fail.
- Page close does not claim immediate server deletion. Records expire and shutdown
  clears them.
- `pagehide` continues to stop camera tracks and clear captured browser media.
- On `pageshow` with `event.persisted === true`, all modifying controls remain disabled
  and no camera or request restarts automatically. The page requires a full reload.
- Reload never reuses the prior token. Application restart invalidates all pairs.

## Registry Lifecycle

The camera CSRF registry is application-scoped, in-memory, bounded to 16 sessions,
replaceable in tests, and protected by a non-module-level lock. Construction receives
its clocks and generators. Startup creates the registry explicitly. Lazy expiry runs
before creation and validation. Capacity never silently evicts a valid record.

Shutdown closes the registry, clears every record and digest, overwrites or releases
the process binding key where practical, and persists nothing. Operations after close
fail safely. A new application receives a new registry and binding key.

## Camera-Media Capability Separation

CSRF authority proves only that a modifying request possesses the current token for a
current same-origin camera page session. It does not prove media-session ownership,
physical camera permission, user identity, or authorization for another record.

The media capability is generated independently, stored and compared under its own
contract, and authorizes one ephemeral media session:

- session creation requires current CSRF authority;
- status GET is non-modifying and requires the correct media capability, not CSRF;
- discard DELETE requires both current CSRF authority and the correct media
  capability;
- CSRF alone cannot read or discard a media session;
- capability alone cannot create or delete;
- the two secrets never share a generator output, digest field, cookie, or header.

The exact media-capability header belongs to U5.1E-R's existing media-session contract;
it cannot be substituted for `X-OrbitMind-Camera-CSRF`.

## Public Errors and Logging Privacy

Every missing, malformed, unknown, mismatched, expired, stale-generation, or replayed
camera CSRF authority returns HTTP 403 with the stable code:

```text
camera_request_csrf_invalid
```

The response does not distinguish cookie, record, token, expiry, route generation, or
digest outcomes. It contains no raw header, path, local root, capability, or traceback.
Protocol Host failures retain a fixed 400 boundary and early declared-size failures a
fixed 413 boundary; neither reveals CSRF state.

The only permitted internal event is `camera_csrf_rejected` with timestamp and a
bounded route class. It contains no token, token digest, cookie, cookie digest, raw
header, generation, media capability, request body, image metadata, path, or exception
object. Metrics may count the fixed event but may not split public validation reasons.

## Runtime Temporary-Root Injection

### Immutable Context

U5.1E-R must introduce a camera-owned immutable `CameraMediaRuntimeContext`, not a
request-owned path lookup. Its production construction receives:

- resolved runtime temp root;
- exact media root;
- injected timezone-aware UTC clock;
- media-session ID generator;
- media-capability generator;
- camera CSRF token generator;
- camera page-session ID generator;
- independent camera-CSRF process-key generator;
- an optional narrow filesystem adapter for deterministic failure tests.

The exact production derivation is:

```text
runtime_temp_root = RuntimePaths.temp_dir.resolve()
media_root = (RuntimePaths.temp_dir / "camera-sessions").resolve()
```

The factory requires `media_root.parent == runtime_temp_root`, rejects a symlink or
resolution escape, rejects a non-directory temp root, and accepts no user-supplied
path. It never uses the current working directory, repository root, request JSON,
normal Settings environment resolution, or an import-time default.

The packaged launcher already owns `RuntimePaths`. After `paths.prepare()` and before
application construction, the future composition change creates this context and
passes it explicitly to `AppContainer`. The API layer consumes the camera-owned
context and does not import or reconstruct `RuntimePaths`.

`AppContainer` accepts an explicitly injected context. If no context is supplied,
camera backend media operations are unavailable and fail closed; the browser-local
preview may remain available. There is no fallback to `%LOCALAPPDATA%`, `TEMP`, the
working directory, or the repository. Tests always inject a context rooted at
`tmp_path`.

### Application Startup Ownership

FastAPI lifespan and its active `AppContainer` own startup:

1. select the injected container;
2. initialize existing storage;
3. validate the immutable camera context and containment;
4. initialize the CSRF registry and media registry/service;
5. create the exact dedicated directory with inherited user-profile ACLs;
6. remove only recognized, server-owned stale camera session entries;
7. fail startup closed if safety, writability, or containment cannot be established;
8. publish no route-ready service until initialization completes.

Recognized stale state must have the server-generated naming and marker contract
defined by U5.1E-R. Unknown files and directories are not deleted or adopted. A
conflicting unknown entry that prevents safe initialization causes a bounded startup
failure.

### Request-Time Ownership

Handlers obtain the already initialized camera service through `AppContainer` and
FastAPI dependency injection. They never reread the environment, Settings, current
working directory, `RuntimePaths`, or a client path. They cannot switch roots. All
session paths are generated by the service and revalidated beneath `media_root` before
use.

### Shutdown Ownership

`AppContainer.shutdown()` closes the camera media service before database disposal. It:

- prevents new work;
- closes open handles;
- deletes only registered ephemeral camera media;
- clears media-capability digests;
- clears and closes the camera CSRF registry;
- leaves unknown files untouched;
- records bounded cleanup failure without exposing a path or secret;
- returns control to the existing lifespan cleanup path.

Cleanup failure is reported honestly and tested, but must not cause deletion outside
the injected root. A new application instance receives no mutable singleton from the
old one.

## Test Injection Contract

Tests construct an explicit camera runtime context with:

- `tmp_path / "camera-sessions"` beneath an isolated injected temp root;
- a fixed timezone-aware UTC clock that can advance deterministically;
- deterministic, independent page-session IDs and CSRF tokens;
- deterministic media-session IDs and capabilities;
- a deterministic process binding key;
- a controlled filesystem adapter for creation, write, rename, and cleanup failures.

No camera backend test may use real `%LOCALAPPDATA%`, the user runtime root, repository
directories, wall-clock time, CSPRNG output, physical camera hardware, or a network
service. Each application instance receives new registries. Tests use synchronization
primitives instead of sleeps.

## Future CSRF Test Matrix

| ID | Required assertion |
| --- | --- |
| A-E | Camera GET sets exactly one cookie; it is HttpOnly, SameSite Strict, path `/workbench/camera`, and Max-Age at most 900 |
| F-H | HTML contains exactly one meta token; asset, URL, logs, and browser storage contain none |
| I-M | Missing cookie/header, wrong/expired/cross-session token all return the same 403 |
| N-P | Correct authority passes; wrong Origin and non-same-origin Fetch Metadata fail even with it |
| Q-R | Digest comparison is constant-time and server state stores no plaintext token or cookie |
| S-U | Every accepted mutation rotates once; old token fails; next token appears only in the approved header |
| V | Concurrent use of one generation yields at most one accepted request and one next token |
| W | Lost response leaves the page unable to mutate until reload |
| X-Y | Reload invalidates the previous page session and application restart invalidates all sessions |
| Z-AA | Public errors and internal events contain no validation detail, secret, digest, cookie, or raw header |
| AB-AD | DELETE needs CSRF plus media capability; neither authority substitutes for the other |
| AE | Persisted back-forward restoration disables modification until full reload |

Additional tests cover capacity 16 without valid-record eviction, exact expiry
boundary, no sliding lifetime, process-key separation, malformed token shape, duplicate
headers, early `Content-Length` rejection, no body decode before CSRF, post-acceptance
media-error rotation, DELETE 204 next-token delivery, and GET capacity failure.

## Future Runtime-Root Test Matrix

- Production media root is exactly the resolved `camera-sessions` child of injected
  `RuntimePaths.temp_dir`.
- Parent, sibling, symlink, junction, file, and resolution escapes fail closed.
- Current working directory and environment changes after construction have no effect.
- Handlers do not reread Settings, environment, or paths.
- Missing context disables backend camera media without a fallback.
- Startup initializes both registries and creates only the approved directory.
- Unsafe or unwritable roots fail before readiness.
- Recognized stale entries are cleaned and unknown files remain untouched.
- Shutdown closes services, clears both registries, releases files, and reports bounded
  cleanup failures.
- Two application instances share no singleton state.
- Every test write remains under its injected `tmp_path`; the real user root is never
  accessed.

## Acceptance Criteria

U5.1E-R may resume only when its implementation and tests demonstrate all of these:

1. One independent 256-bit page-session identifier and 256-bit CSRF token are issued
   for each camera page load.
2. Only keyed page-session and token digests remain server-side.
3. The exact cookie and header contracts are implemented without broadening cookie
   path or enabling CORS.
4. Exact Host, Origin, Fetch Metadata, cookie, and token checks precede any media read.
5. Accepted modifying requests rotate atomically before media processing.
6. Replay, concurrency, lost responses, reload, bfcache, restart, and capacity all
   fail closed as specified.
7. Media capability and CSRF authority remain independent.
8. The media root is injected once from `RuntimePaths.temp_dir / "camera-sessions"`.
9. Startup and shutdown are owned by application lifespan and leave unknown files
   untouched.
10. Tests use fixed clocks, generators, synchronization, and isolated roots with no
    physical camera or external network.
11. Public errors and logs contain no secrets, digests, validation branch detail,
    local paths, or media body.
12. Existing non-camera Workbench behavior and browser security policies remain
    unchanged.

## Explicit Non-Goals

- Implementing CSRF, routes, media intake, storage, frontend fetch, or persistence in
  this architecture gate.
- General authentication, login sessions, tenancy, or public-network CSRF support.
- HTTPS termination, `Secure` cookie compatibility claims, CORS, reverse proxies, or
  alternate loopback hostnames.
- Reusing the custom-TLE handoff store, token, cookie, or process key.
- Persisting CSRF sessions, media capabilities, or temporary camera media.
- Token recovery, grace generations, silent rollback, or multi-tab simultaneous
  mutation.
- Physical camera access, semantic analysis, external AI, agent execution, or model
  changes.
- A generic upload endpoint, arbitrary path input, or storage outside the injected
  camera-media root.
