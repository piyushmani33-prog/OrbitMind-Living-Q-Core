# Custom-TLE Transient Handoff Architecture

## Status

- **Document status:** Decision closed; U4.3E implementation and QA recorded
- **Slices:** U4.3C architecture, U4.3D decision closure, U4.3E implementation, and U4.3F browser compatibility
- **Decision date:** 2026-07-12
- **Design verdict:** **APPROVE DESIGN FOR IMPLEMENTATION**
- **Browser compatibility verdict:** **APPROVE WITH REQUIRED IMPLEMENTATION CONDITIONS**
- **U4.3E implementation status:** Implemented on this branch; merge review-ready after the
  validations recorded below. This remains a local Solo Alpha implementation and is not a public
  deployment authorization.

All material architecture decisions identified by U4.3C are closed below. Approval remains limited
to an explicitly enabled, loopback-bound, single-process Solo Alpha application. Public,
non-loopback, multi-worker, and distributed use remain forbidden.

U4.3F closed a browser incompatibility found during U4.3E QA. U4.3E now applies the route-scoped
Referrer-Policy and request-validation contract frozen below. The focused, adjacent, and real-browser
gates passed; the full suite was attempted but exceeded the local 900-second limit and is not
claimed as a full-suite pass.

## U4.3F browser evidence

Chrome `150.0.7871.114` was launched directly on Windows 10 with a fresh temporary profile,
extensions disabled, and no request interception or header overrides. The launch used the installed
`chrome.exe` with `--headless=new`, a temporary `--remote-debugging-port`, and a temporary
`--user-data-dir`; CDP performed navigation, a trusted mouse click, and observation only. It did
not construct the production document, submit through fetch, or modify headers. The real OrbitMind
app was started with the documented Uvicorn command on `http://127.0.0.1:8000`. A top-level page loaded
directly from `/workbench`; it was not a `file:` document, copied markup, or a frame. A trusted
mouse click submitted the server-rendered, same-origin `POST /workbench/run` form without requiring
JavaScript. Chrome sent:

| Header | Observed value |
| --- | --- |
| `Host` | `127.0.0.1:8000` |
| `Origin` | `null` |
| `Referer` | absent |
| `Sec-Fetch-Site` | `same-origin` |
| `Sec-Fetch-Mode` | `navigate` |
| `Sec-Fetch-Dest` | `document` |
| `Content-Type` | `application/x-www-form-urlencoded` |

The response that created the document carried `Referrer-Policy: no-referrer`; Chrome's request
metadata reported the same effective policy. This was the pre-U4.3E decision evidence: current
main at that point contained the U4.3D design but not the handoff route, so `/workbench/run` was
used to reproduce the production browser/header behavior. The implemented branch now applies the
approved compatibility policy and the same natural form submits with canonical Origin.

Local inspection used FastAPI `0.139.0` and Starlette `1.3.1`. The production form has a literal
same-origin action and no redirect. The HTML-only middleware applies `no-referrer` from the response
media type, while CSP separately restricts forms to self and blocks framing. Starlette exposes the
raw ASGI header list needed for duplicate-header validation. No framework normalization, redirect,
form attribute, cookie attribute, or CSP directive explained the matrix; changing only the response
Referrer-Policy changed the resulting Origin.

An isolated loopback server then varied only the response `Referrer-Policy` for identical
top-level same-origin HTML forms. Server-side raw-header capture produced this matrix; every row
was a successful HTTP 200 top-level form navigation with JavaScript enabled,
`Sec-Fetch-Site: same-origin`, and the probe's `SameSite=Strict; HttpOnly` cookie present:

| Referrer-Policy | Origin | Referer |
| --- | --- | --- |
| no header (browser default) | canonical origin | full same-origin page URL |
| `no-referrer` | `null` | absent |
| `same-origin` | canonical origin | full same-origin page URL |
| `strict-origin` | canonical origin | origin only |
| `strict-origin-when-cross-origin` | canonical origin | full same-origin page URL |
| `origin` | canonical origin | origin only |
| `origin-when-cross-origin` | canonical origin | full same-origin page URL |

The same `no-referrer` result occurred in a fresh browser profile, an existing profile, a
same-origin iframe, and with JavaScript disabled. A sandboxed iframe and an automation-created
`data:` document also sent `Origin: null`, but were distinguishable from the legitimate top-level
flow: each sent `Sec-Fetch-Site: cross-site` and omitted the Strict cookie. A same-origin iframe
under `no-referrer` sent `Origin: null`, `Sec-Fetch-Site: same-origin`, and the cookie, which is an
additional reason not to accept `null` as equivalent to the canonical origin. With
`Referrer-Policy: same-origin`, the JavaScript-disabled top-level form sent the exact canonical
Origin and the cookie.

This establishes causation for Chrome 150: `no-referrer`, rather than an opaque top-level
document, redirect, copied form, extension, or request-interception harness, caused the legitimate
form's `Origin: null`. It also matches the Fetch Standard's Origin-header algorithm: for a
non-CORS, non-GET/HEAD request, `no-referrer` sets the serialized Origin to `null`, while
`same-origin` retains it when current and request origins match. The HTML form-navigation algorithm
passes the document's referrer policy into Fetch. See the WHATWG
[Fetch Standard](https://fetch.spec.whatwg.org/#origin-header) and
[HTML Standard](https://html.spec.whatwg.org/multipage/form-control-infrastructure.html#form-submission-algorithm).

The compatibility options were decided as follows:

| Option | Decision | Reason |
| --- | --- | --- |
| A. Preserve exact Origin and change a proven header condition | **Selected** | Workbench-only `same-origin` restores canonical Origin for ordinary and no-JavaScript forms without exposing token/TLE or changing CSP |
| B. Accept `Origin: null` under local constraints | Rejected | `null` conflates the legitimate flow with opaque/sandboxed initiators and makes Fetch Metadata carry more security weight than necessary |
| C. Add a separate anti-CSRF form value | Deferred | Technically viable, but additional state and cryptography are disproportionate after Option A succeeds; reconsider for a public authenticated design |
| JavaScript fetch/XHR | Rejected | Breaks the no-JavaScript requirement and conflicts with `connect-src 'none'` |
| Keep the handoff blocked | Rejected | Unnecessary once Option A is implemented and the full browser gates pass |

## Problem statement

The Mission Workbench accepts a request-local custom TLE, validates it, and can calculate mission
windows or a trajectory replay while the raw lines remain in that request. A successful custom-TLE
mission-window result should offer `Replay this request` without asking the user to enter those
lines again.

The handoff must not disclose raw TLE through HTML, URLs, JavaScript, browser storage, cookies,
logs, errors, artifacts, caches, or durable database records. It must not substitute a catalog
object and must not introduce a provider or network path.

## Existing limitation

`POST /workbench/run` parses a bounded `WorkbenchForm`, resolves custom input through the existing
custom-TLE validator, builds a typed `MissionWindowRequest`, and renders a result. That result
retains only safe display identity and checksum information. Its stable identity is
`custom-tle:<element-checksum>`.

A checksum can authenticate matching recovered input but cannot reconstruct the two orbital-element
lines. `POST /workbench/replay` therefore cannot replay the result unless the user submits the raw
TLE again. U4.3B correctly leaves direct custom-TLE handoff unavailable and never falls back to a
bundled object.

Current boundaries relevant to this decision are:

- the Workbench request body is bounded to 4,096 bytes;
- the validator bounds each TLE line to 100 characters and the optional label to 80 characters;
- Workbench calculations do not persist missions, replays, artifacts, or source-cache entries;
- network, CelesTrak, and open research are disabled by default;
- browser CSP permits same-origin scripts and forms and sets `connect-src 'none'`;
- the application container owns process-lifetime services;
- OrbitMind has no browser session framework or authenticated browser principal;
- the fixed `local-owner` dependency used by selected persisted APIs cannot distinguish browsers;
  and
- the governed `AuditEvent` path is database-backed and is not used by this transient design.

## Goals

- Carry one validated custom-TLE mission-window request into exactly one trajectory replay.
- Keep raw TLE entirely server-side after the original POST.
- Bind the handoff to one short-lived local browser session and one replay-only purpose.
- Use a 256-bit opaque identifier with fixed expiry and strict capacity limits.
- Guarantee atomic single use under concurrent submissions.
- Fail closed on absence, malformed input, expiry, reuse, owner mismatch, restart, or capacity
  exhaustion.
- Preserve `TrajectoryReplayService` as the scientific authority.
- Provide bounded transient diagnostic observability without sensitive data.

## Non-goals

- Authentication, authorization, tenancy, or proof of human identity
- Public, multi-user, multi-worker, or distributed deployment
- Durable handoff recovery across restart
- Database, filesystem, artifact, browser-storage, or cache persistence
- Provider calls, source refresh, catalog substitution, or network access
- A general session framework, general cache, or durable audit system
- Replay for any purpose other than custom-TLE trajectory replay
- Changes to SGP4, mission-window, geometry, or trajectory-replay calculations
- A complete public-deployment CSRF system

## Safety invariants

1. Raw TLE is never emitted in HTML, a URL, JavaScript, browser storage, a cookie, a log, an
   error, an artifact, a cache file, or a database record.
2. The client receives only a server-generated opaque handoff identifier.
3. The identifier is accepted only by a fixed same-origin POST endpoint for custom-TLE replay.
4. A record is bound to one ephemeral browser session and one purpose.
5. Correct consumption atomically removes the record before replay begins.
6. Owner mismatch does not remove or consume the record.
7. Missing, malformed, expired, consumed, mismatched, or restart-lost state produces no replay and
   no source fallback.
8. Capacity, per-session capacity, input sizes, and lifetimes are fixed and bounded.
9. Shutdown clears state; restart cannot recover it.
10. Diagnostic output never contains raw TLE, token, session value, session digest, request body,
    authorization material, path, or stack trace.
11. This mechanism provides local request continuity, not authentication or authorization.

## Threat model

| Threat | Local Solo Alpha treatment | Residual/public concern |
| --- | --- | --- |
| Raw TLE in HTML or hidden fields | Raw lines stay in a server-side record; the form carries only an opaque identifier | Independent disclosure review remains required |
| Identifier in URL, Referer, history, or query logs | POST body only; no GET/query route; Workbench `same-origin` policy can disclose only the non-secret same-origin page path | Proxy request-body logging requires separate review |
| Alternate host or DNS rebinding | Exact configured Host and port; no DNS resolution; forwarded headers rejected | Trusted-proxy design remains deferred |
| Cross-origin form submission | Exact canonical Origin and exact same-origin Fetch Metadata are both required | A public CSRF framework remains mandatory |
| Another browser consumes a token | Keyed session binding checked before removal | Cookie theft requires HTTPS and authentication |
| Expired or reused token | Monotonic expiry and atomic pop | Distributed atomicity is not addressed |
| Token guessing or fixation | 256 CSPRNG bits; server creates identifiers; strict format | Public rate limiting remains required |
| Cross-request source substitution | All replay inputs are in one immutable server record | No client scientific fields are accepted |
| Catalog/ISS fallback | Prohibited on every failure | No fallback is accepted |
| Restart, reload, or multiple workers | Feature is one-process only; restart/reload loses state; multi-worker enablement is rejected | Shared-state design remains deferred |
| Unbounded memory or creation abuse | Fixed global/session caps, logical-size bound, TTL, and cleanup | Host DoS and public rate limiting remain deferred |
| Concurrent duplicate consume | One lock-held validation and removal gives exactly one success | Multiple processes are prohibited |
| Error/debug leakage | Fixed browser messages and bounded reason codes | Deployment logging/proxy policy remains deferred |

The local design addresses client disclosure, guessing, reuse, short-lived cross-request
continuity, DNS-rebinding inputs, bounded memory, and same-process races. It does not protect a
compromised browser, host, process, debugger, crash dump, or reverse proxy.

## Options considered

| Option | Confidentiality | Expiry / single use | Owner binding | Restart | Local Solo Alpha | Future multi-user |
| --- | --- | --- | --- | --- | --- | --- |
| Raw TLE hidden fields | Fails: raw TLE is HTML | Replayable | None | Page retains it | **Reject** | **Reject** |
| Raw TLE URL/query | Fails through history, Referer, and logs | Poor | None | URL retains it | **Reject** | **Reject** |
| Base64/reversible client value | Encoding is not confidentiality | Replayable | None | Client retains it | **Reject** | **Reject** |
| Signed/encrypted client payload | Depends on key custody | Needs replay state | Complex | Can survive | Not the smallest safe option | Reconsider only with managed keys and auth |
| Bounded process-local store | Raw TLE stays server-side | Native TTL and atomic pop | Ephemeral session HMAC | Deliberate loss | **Approved** | **Not suitable** |
| Database transient record | Server-side | Transactional | Principal possible | Can survive | Reject for this no-persistence boundary | Separate future review only |
| Browser storage/cookie with raw TLE | Fails client boundary | Browser-controlled | Weak | Browser-dependent | **Reject** | **Reject** |
| Catalog substitution | Changes scientific source | Irrelevant | Irrelevant | Irrelevant | **Reject** | **Reject** |

An encrypted client-carried payload would still require key rotation, expiry, replay prevention,
session binding, ciphertext-log review, and size controls. It is not approved for this feature.

## Decision

Approve an application-container-owned, bounded, process-local transient handoff store. It is
available only when explicitly enabled for one process bound to the canonical loopback origin.

After existing custom-TLE validation and successful mission-window calculation, the server stores
one immutable replay record containing the validated elements and all scientifically relevant
inputs. It renders only a random opaque handoff identifier in a same-origin POST form.

The approved route is:

```text
POST /workbench/replay/custom-handoff
```

It is replay-only, accepts one form field, is not a JSON API, and does not use the full Workbench
form parser. The token digest is the store key. Session binding is a keyed in-process HMAC digest.
Neither raw identifier is retained in a record or diagnostic event.

## Canonical origin and host validation

The feature has exactly one configured canonical origin:

```text
http://127.0.0.1:<configured-port>
```

The future setting `ORBITMIND_CUSTOM_TLE_HANDOFF_PORT` is an integer from 1,024 through 65,535 and
defaults to `8000`. The canonical origin contains that explicit decimal port, no trailing slash,
path, query, fragment, user information, or alternate spelling.

`localhost`, `::1`, bracketed IPv6 loopback, hostnames that resolve to loopback, alternate IPv4
forms, and another port are rejected. `localhost` is not an alias and is not a separately supported
cookie scope. Trust is never inferred through DNS resolution.

For every Workbench request that can create or consume handoff state:

- raw ASGI headers must contain exactly one `Host` header;
- its value must be exactly `127.0.0.1:<configured-port>` after trimming optional HTTP whitespace;
- commas, user information, empty host/port, malformed port, and duplicate Host headers fail;
- the ASGI request scheme must be exactly `http` for this approved local origin;
- any `Forwarded` header, any header whose lower-case name starts with `x-forwarded-`, or
  `X-Original-Host`, `X-Original-Proto`, `X-Real-IP`, or `X-Rewrite-URL` fails closed; and
- forwarded values are never consulted, even when they claim loopback.

Validation occurs before reading a request body, issuing a session cookie, creating state, or
looking up a token. Failure returns status 400 with fixed safe HTML:

> This local Workbench request is unavailable.

The response retains browser-security headers and contains no supplied header, host, port, raw
TLE, token, path, or internal detail.

## Origin policy

Every state-changing Workbench POST involved in creation or consumption uses this policy:

- raw headers must contain exactly one `Origin` header;
- its value must be exactly the canonical origin string;
- `Origin: null`, malformed origins, trailing slash, alternate host, `localhost`, `::1`, different
  port, HTTPS/HTTP mismatch, duplicate Origin headers, credentials, path, query, or fragment fail;
- supplied Origin comparison is exact after trimming optional surrounding HTTP whitespace; no DNS,
  default-port, case, or alias normalization creates equivalence;
- raw headers must also contain exactly one `Sec-Fetch-Site` header with the exact lower-case value
  `same-origin`; and
- absent, duplicate, malformed, `none`, `same-site`, or `cross-site` Fetch Metadata fails closed
  regardless of the Origin value.

Rejected Origin/fetch-metadata requests return status 403 with the same fixed safe HTML used for
Host rejection. No body is parsed and no state is created, looked up, rotated, or consumed.

There is no absent-Origin fallback. `Origin: null` is never treated as canonical. Non-browser and
older clients that do not provide both exact fields must not use this browser handoff. A
non-browser client can spoof these headers, so they remain defense in depth rather than identity;
successful consumption still requires possession of both the valid single-use token and the
matching HttpOnly session cookie.

All HTML responses for the exact `/workbench` path and the `/workbench/` path subtree, including
safe HTML errors, must use:

```text
Referrer-Policy: same-origin
```

This is a route-scoped compatibility exception. Other HTML surfaces retain `no-referrer`; JSON,
JavaScript assets, artifacts, and binary responses remain outside the HTML header policy. Under
`same-origin`, Chrome 150 sends the canonical Origin for the ordinary and JavaScript-disabled
same-origin forms. The same-origin `Referer` includes the Workbench page path, but never a handoff
token because the architecture forbids tokens in URLs. Cross-origin requests receive no Referer.
The fixed form action remains same-origin, CSP retains `form-action 'self'` and
`connect-src 'none'`, and no external request or redirect is introduced.

The frozen request decision table is:

| Origin | Sec-Fetch-Site | Result |
| --- | --- | --- |
| Exactly one canonical origin | Exactly one `same-origin` | Continue to cookie, media-type, body, token, and owner checks |
| `null` | Any value or absent | HTTP 403 fixed safe HTML |
| Absent | Any value or absent | HTTP 403 fixed safe HTML |
| Malformed, duplicate, mismatched, `localhost`, alternate port/scheme | Any value or absent | HTTP 403 fixed safe HTML |
| Exactly one canonical origin | Absent, duplicate, malformed, `none`, `same-site`, or `cross-site` | HTTP 403 fixed safe HTML |

Host, scheme, and forwarded-header failures still occur first and return HTTP 400. The 403 body is
always `This local Workbench request is unavailable.` and reflects no header or state. A natural
JavaScript-disabled Chrome form under the selected policy supplies both accepted values. A
non-browser client receives no compatibility relaxation.

## Session/owner binding

A browser-specific binding requires a minimal ephemeral session cookie. IP address, User-Agent,
and the fixed `local-owner` value are not owner identities for this purpose.

The approved cookie contract is:

- name: `orbitmind_handoff_session`;
- value: 32 bytes from the operating-system CSPRNG, encoded as exactly 43 unpadded base64url
  characters from `[A-Za-z0-9_-]`;
- `HttpOnly`;
- `SameSite=Strict`;
- no `Domain` attribute, making it host-only;
- `Path=/workbench`;
- `Max-Age=1800`;
- absolute 30-minute server-side monotonic expiry with no sliding extension;
- `Secure=False` only on the approved canonical loopback HTTP origin;
- `Secure=True` is mandatory for any separately approved HTTPS design;
- the feature is disabled on non-loopback HTTP;
- no credentials, raw TLE, ownership claim, or replay data in the value; and
- no raw session value in records, diagnostics, logs, errors, or rendered content.

The container creates one 32-byte CSPRNG HMAC key at startup. It is never configured, persisted,
logged, rendered, or exported and is discarded at shutdown. The store uses
`HMAC-SHA-256(process_key, raw_session_value)` as the session binding. This prevents a reusable raw
cookie or unsalted digest from entering records and makes all bindings invalid after restart.

A bounded in-memory session registry stores only the HMAC digest plus monotonic creation/expiry
deadlines. It has the same global maximum of 128 live entries as the handoff store. A session is
created only after a successful custom-TLE mission-window calculation needs a handoff, not on GET.

On the creation path, a missing, malformed, expired, or registry-unknown cookie is replaced with a
new server-generated value if capacity permits. The submitted value is never registered or treated
as authoritative. Rotation invalidates prior handoffs for that browser. On the consume path, an
invalid or unknown cookie is not rotated into authority for the submitted handoff; consumption
fails as unavailable. Consuming one handoff does not rotate a valid session.

This is browser correlation, not authentication, authorization, tenancy, or proof of identity.

## Handoff token contract

- Generate exactly 32 bytes with the operating-system CSPRNG.
- Encode as exactly 43 unpadded base64url characters.
- Permit only ASCII `[A-Za-z0-9_-]`.
- Reject length or alphabet errors before hashing or store lookup.
- Use the 32-byte SHA-256 digest of the ASCII token as the store key.
- Place the raw token only in the POST request body.
- Never place it in a URL, query, fragment, cookie, log, diagnostic event, error, or redirect.
- Retry generation at most three times if its digest collides with a live key.
- After three collisions, create no record and return the fixed capacity/internal-unavailable
  presentation without exposing collision details.

SHA-256 is sufficient for the store key because the input has 256 bits of server-generated
entropy. The session binding uses keyed HMAC because session values have a separate lifecycle and
must not leave reusable digests in records.

## Transient record model

The future record is frozen and typed. It contains only:

- 32-byte handoff lookup digest;
- 32-byte session HMAC digest;
- fixed purpose `CUSTOM_TLE_TRAJECTORY_REPLAY`;
- fixed record schema version;
- monotonic creation, handoff-expiry, and session-expiry deadlines;
- validated safe custom label;
- validated TLE line 1 and line 2;
- 64-character lowercase hexadecimal source checksum;
- safe stable custom source reference;
- UTC replay start and end;
- observer latitude, longitude, and altitude as finite binary64 values;
- deterministic sample interval; and
- maximum sample count.

All replay inputs remain server-side. The client cannot alter source, observer, interval, or
sampling policy between mission-window calculation and replay.

The record explicitly excludes passwords, provider keys, authorization/cookie headers, raw
session values, arbitrary headers, paths, metadata, ORM objects, database connections, HTML,
browser state, artifacts, and unrelated form fields.

The record type must not use a default representation that includes sensitive fields. Raw TLE
fields use `repr=False`, and the type provides only a fixed redacted representation such as:

```text
TransientCustomTleHandoffRecord(<redacted>)
```

Logging the record object is prohibited. Exceptions, assertions, validation messages, and
diagnostic events must identify only a safe field name and fixed reason code, never a rejected or
stored value.

## Logical record-size definition

The enforceable logical size is not Python heap usage and must not use `sys.getsizeof`. Before
insertion, compute:

```text
logical_size =
    raw byte length of fixed binary scalar fields
  + UTF-8 byte length of every textual scalar
  + 4 bytes of framing for each textual scalar
```

Approved per-field maxima are:

| Field group | Maximum encoded bytes |
| --- | ---: |
| Handoff digest and session HMAC | 64 total |
| Purpose | 32 |
| Record schema version | 32 |
| Custom label | 80 |
| TLE line 1 | 100 |
| TLE line 2 | 100 |
| Source checksum | 64 |
| Stable source reference | 80 |
| UTC start and end | 35 each, 70 total |
| Observer binary64 values | 24 total |
| Creation, handoff-expiry, session-expiry binary64 values | 24 total |
| Sample interval and maximum sample count as unsigned 64-bit integers | 16 total |
| Text framing for nine textual fields | 36 total |

The total logical record size must be at most **1,024 bytes**. The implementation must calculate
and reject above-limit records before acquiring capacity for insertion. This bound has deliberate
headroom over the enumerated maximum while remaining deterministic and enforceable.

## Lifecycle and state transitions

The stored state is deliberately small:

```text
validated request
      |
      v
  AVAILABLE --atomic remove--> CONSUMED (record absent)
      |
      +--expiry cleanup-------> EXPIRED (record absent)

Any pre-storage or lookup failure -> REJECTED (diagnostic outcome only)
```

Creation occurs only after existing form/custom-TLE validation and successful mission-window
calculation. Under the store lock, creation removes expired records and sessions, checks limits,
generates a unique digest within three attempts, and inserts one immutable `AVAILABLE` record.

Atomic consumption uses this exact ordering:

1. Validate token length and alphabet.
2. Derive the SHA-256 lookup digest.
3. Acquire the single store lock.
4. Remove expired records and sessions.
5. Look up the record.
6. Validate purpose.
7. Validate the handoff and bound-session expiry deadlines.
8. Validate the current session HMAC binding.
9. Atomically remove the record.
10. Release the lock.
11. Execute replay from the immutable record.

There is no `await`, logging, replay calculation, TLE parsing, HTML rendering, or other external
call while the lock is held. There is no reinsertion after replay or rendering failure. Two
concurrent attempts yield exactly one successful removal.

Owner/session binding is validated before removal. A mismatch does not delete, expire, mutate, or
consume the record. The correct session may consume it later before expiry. The mismatched client
receives the same unavailable response as an unknown or consumed identifier and cannot learn that
another session owns it.

## Limits and expiry

These values are approved for the initial implementation:

| Limit | Approved value |
| --- | --- |
| Handoff entropy | 32 random bytes / 256 bits |
| Encoded token | 43 unpadded base64url characters |
| Handoff TTL | 5 minutes absolute, monotonic |
| Session TTL | 30 minutes absolute, monotonic |
| Global live handoff records | 128 |
| Live handoff records per session | 4 |
| Global live session entries | 128 |
| TLE line | 100 characters each, existing validator |
| Custom label | 80 characters, existing validator |
| Original Workbench body | 4,096 bytes, unchanged |
| Handoff POST body | 512 wire bytes |
| Logical record | 1,024 encoded scalar bytes |
| Token collision retries | 3 |
| Diagnostic event ring | 256 events |

Use `time.monotonic()` for expiry and UTC-aware wall time only for display-safe diagnostic event
timestamps. Cleanup is request-driven: sweep expired records and sessions before every creation
capacity check and before every consume lookup. There is no timer, scheduler, or background job.

Never evict a live record to make capacity. Never evict another session's record. At per-session or
global capacity, retain no new raw TLE record and show:

> A temporary replay handoff is not available right now. The mission-window result remains valid;
> return to the Workbench to try again.

The mission-window response remains HTTP 200 because its scientific calculation succeeded.

## Request/UI contract

```text
POST /workbench/run (validated custom TLE)
  -> mission-window result
  -> POST /workbench/replay/custom-handoff
       handoff_id=<43-character opaque identifier only>
  -> atomic server consume
  -> existing TrajectoryReplayService
  -> server-rendered predicted replay
```

The handoff route contract is:

- method: POST only; no GET equivalent;
- fixed same-origin action `/workbench/replay/custom-handoff`;
- media type: exactly `application/x-www-form-urlencoded` after lower-casing and trimming the media
  type;
- parameters: absent or exactly one case-insensitive `charset=utf-8`; duplicate Content-Type,
  duplicate charset, unknown parameter, or another charset is rejected;
- body: at most 512 wire bytes, decoded as strict UTF-8;
- form fields: exactly one `handoff_id`; duplicate, missing, blank, or unknown fields are rejected;
- value: exact 43-character token contract after form decoding;
- no query, redirect carrying state, raw-TLE field, client scientific field, or JavaScript
  requirement; and
- security headers apply to every HTML success and error.

The normal encoded body is 54 bytes (`handoff_id=` plus 43 safe characters). A 512-byte wire limit
leaves more than nine times that size for standard form framing while remaining small enough to
reject padding, repeated fields, and oversized parser input before framework form parsing. Python
object or framework allocation overhead is not part of the wire-size calculation.

The mission-window result states that the handoff is temporary, single-use, uses the exact same
source, observer, and interval, opens a predicted replay, and is not live tracking. It works as an
ordinary HTML form without JavaScript.

## Failure semantics

All responses are fixed server-rendered HTML with browser-security headers and no reflected input.

| Condition | Status | Fixed user-facing behavior |
| --- | ---: | --- |
| Invalid/duplicate Host or forwarded header | 400 | `This local Workbench request is unavailable.` |
| Missing, null, invalid, mismatched, or duplicate Origin; missing, invalid, or duplicate Fetch Metadata | 403 | `This local Workbench request is unavailable.` |
| Unsupported Content-Type | 415 | `The temporary replay handoff request is invalid.` |
| Body over 512 bytes | 413 | `The temporary replay handoff request is invalid.` |
| Missing/duplicate/unknown field or malformed token | 422 | `The temporary replay handoff request is invalid.` |
| Unknown, expired, consumed, owner-mismatched, purpose-mismatched, or restart-lost token | 410 | `This temporary replay handoff is unavailable or no longer valid. Return to the Workbench and submit the custom TLE again.` |
| Creation capacity unavailable | 200 mission result | Show the fixed capacity message; create no handoff |
| Internal creation/store failure | 500 | `A temporary replay handoff could not be created safely.` |
| Expected replay validation/calculation failure after consume | 422 | `The trajectory replay calculation could not complete safely.` |
| Unexpected replay/rendering failure after consume | 500 | `The trajectory replay calculation could not complete safely.` |

Purpose mismatch does not remove the record and is treated as unavailable externally. Expired
records are removed during the required sweep. Consumed and restart-lost identifiers have no
tombstone and are indistinguishable from unknown. Missing or invalid session state on consume is
also unavailable, not a new authoritative session.

No failure path returns a partial scientific result, restores a consumed record, invokes a
provider, writes persistence/artifacts/cache, or falls back to catalog/ISS.

## Transient diagnostic observability

The exact term is **transient diagnostic observability**. It is not audit evidence, governed audit,
or a durable lifecycle record.

One container-owned ring holds at most 256 typed events. When full, a new event overwrites the
oldest. It is cleared on restart and shutdown. Permitted fields are:

- fixed event type;
- UTC-aware event timestamp;
- fixed purpose enum;
- fixed result status; and
- bounded reason-code enum.

Approved event types are `created`, `consumed`, `expired`, `rejected`, `capacity_rejected`,
`owner_mismatch`, and `malformed_identifier`. Reason codes are an implementation-reviewed enum,
not arbitrary strings.

The ring must not contain raw TLE, source checksum, token, raw session identifier, reusable session
digest/HMAC, request body, arbitrary header, authorization/cookie material, label, path, exception
message, or stack trace. Source checksum is intentionally prohibited because even memory-only
retention would permit cross-session correlation of the same custom source. Aggregate counters may
use only the same fixed event/status/reason vocabulary.

The existing database-backed `AuditEvent` system is not used. Process logs may state only a fixed
event name and bounded reason code if tests prove all prohibited values absent; logging the record,
request, token, cookie, or exception object is forbidden.

## Container ownership and process lifecycle

The store, session registry, process HMAC key, and diagnostic ring are:

- constructed by `AppContainer` from immutable validated limits;
- explicitly injected into the Workbench handoff service/routes;
- replaceable by a bounded test implementation;
- never module globals or mutable default arguments;
- unavailable to unrelated routes and domain/scientific services; and
- cleared through application lifespan shutdown, with startup always empty.

Use one thread-safe lock for session/record cleanup, capacity checks, insertion, and atomic consume.
Never hold it during validation, propagation, rendering, logging, or `await`.

## Single-process enforcement

The future feature is disabled by default through:

```text
ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED=false
```

Enabling it requires all of:

- canonical host fixed to `127.0.0.1` and configured port in the approved range;
- authoritative OrbitMind worker setting `ORBITMIND_API_WORKERS=1`;
- authoritative reload setting `ORBITMIND_API_RELOAD_ENABLED=false`;
- supported startup binding exactly to that host and port; and
- no trusted-proxy or forwarded-header mode.

The supported local launcher must derive its Uvicorn worker/reload arguments from these settings;
operators must not override them with direct CLI worker or reload flags. Startup validation occurs
before the store is constructed. If the feature is enabled and workers are not exactly one, reload
is enabled, origin configuration is invalid, or proxy forwarding is enabled, the application
rejects startup with the fixed operator-facing error:

```text
Custom-TLE transient handoff requires canonical loopback HTTP, exactly one worker, reload disabled,
and forwarded-header trust disabled.
```

It must not silently disable only some workers or provide partial handoff behavior. Development
auto-reload is unsupported because restart loses all handoffs. Multiple workers, horizontal
replicas, sticky sessions, non-loopback binding, or a direct unsupported launcher remain forbidden.

A process-local store works only for a single application process. Broader deployment requires a
separately reviewed authenticated shared atomic store; PostgreSQL must not be introduced silently.

## CSRF considerations

Implementation may proceed before a general CSRF subsystem only under this exact local policy:

- explicit feature enablement;
- canonical loopback HTTP origin only;
- one process and no reload;
- exact Host/scheme and forwarded-header rejection;
- exact canonical Origin and exactly one `Sec-Fetch-Site: same-origin`, with no null/absent-Origin
  fallback;
- Workbench-only `Referrer-Policy: same-origin` so natural browser forms reliably provide that
  canonical Origin;
- same-origin POST form;
- `SameSite=Strict` host-only ephemeral session cookie; and
- opaque replay-only single-use handoff token.

POST-only is not complete CSRF protection. The handoff token is not a CSRF token. SameSite is
defense in depth, not authentication or authorization. This policy does not authorize non-loopback,
public, authenticated, reverse-proxied, or multi-user use.

Option B, accepting `Origin: null` under Host, Fetch Metadata, cookie, and token constraints, is
not selected. Although it could be risk-accepted for this loopback-only boundary, `null` also
represents sandboxed and other opaque initiators, and non-browser clients can spoof Fetch Metadata.
Option C, a separate session-bound anti-CSRF form value, remains technically viable but is
disproportionate when the proven route-scoped policy restores a canonical Origin without raw-TLE
or token exposure. Option D, replacing the form with JavaScript fetch/XHR, remains rejected because
the no-JavaScript flow is required and CSP sets `connect-src 'none'`. Keeping the handoff blocked
entirely is unnecessary once the implementation condition and browser gates are met.

Dedicated CSRF tokens/validation, HTTPS, `Secure` cookies, trusted-host/origin configuration,
authentication, authorization, and rate limiting are mandatory before broader external deployment.

## Privacy and non-disclosure

Normal client-visible state contains only the opaque handoff token, safe result metadata, and the
opaque session cookie. Neither opaque value encodes or permits reconstruction of raw orbital
elements.

Fail-closed guarantees are:

- missing/malformed token -> no replay;
- expired/reused token -> no replay;
- owner mismatch -> no replay and no consumption;
- process restart/reload -> no replay;
- capacity failure -> no retained raw-TLE record;
- internal exception -> sanitized HTML and no partial result;
- every failure -> no catalog/ISS fallback, provider call, persistence, or artifact write; and
- every diagnostic/log path -> no raw TLE, token, session value/digest, checksum, body, header,
  path, record representation, or stack trace.

This is data minimization, not process-memory encryption or protection from an administrator,
debugger, crash dump, or compromised runtime.

## Implementation test plan

The U4.3E implementation tests and browser QA cover:

1. successful custom-TLE mission-window-to-replay handoff;
2. exact source checksum, observer, UTC interval, and sampling-policy continuity;
3. POST-only route, exact Content-Type, 512-byte limit, and strict one-field parser;
4. raw TLE/token/session absent from HTML, URL, JavaScript, logs, errors, diagnostics, and storage;
5. token entropy, alphabet, length, digest lookup, collision retries, and strict pre-lookup rejection;
6. five-minute handoff expiry and 30-minute absolute session expiry using a controllable monotonic
   clock;
7. session creation, rotation, host-only path, SameSite, HttpOnly, Max-Age, and loopback HTTP
   `Secure=False` behavior;
8. future HTTPS mode requires `Secure=True`, while non-loopback HTTP cannot enable the feature;
9. owner mismatch does not delete or consume the valid record;
10. the correct owner can consume after a mismatched attempt;
11. concurrent duplicate consume yields exactly one success;
12. unknown, consumed, purpose-mismatched, restart-lost, malformed, and missing state;
13. global, per-session, session-registry, and logical 1,024-byte limits;
14. cleanup before capacity checks, no live eviction, and capacity recovery after expiry;
15. record `repr` redaction and absence of raw values from exceptions/assertions;
16. source checksum is absent from diagnostic events, proving no memory-ring cross-session
    correlation;
17. 256-event overwrite-oldest behavior and shutdown/restart clearing;
18. `localhost`, `::1`, alternate IPv4, different port, malformed/duplicate Host, and arbitrary
    DNS hostname rejection;
19. every listed forwarded header and prefix rejection;
20. matching/mismatched/duplicate/malformed/null/missing Origin cases and accepted/missing/
    duplicate/`none`/`same-site`/`cross-site` Fetch Metadata, including rejection before body or
    state access;
21. HTTP/HTTPS scheme mismatch rejection;
22. feature default-off and startup rejection for worker count other than one, reload, bad origin,
    or forwarded trust;
23. no fallback or reinsertion after replay/rendering failure;
24. CSP/security headers on all safe HTML errors;
25. database counts and artifact/cache trees unchanged before/after success and failure;
26. active no-network/provider proof;
27. mobile and no-JavaScript form handoff; and
28. existing catalog handoff, Workbench, replay, architecture, CSP, and scientific regressions.

Real-browser QA must inspect page source, URL, cookies, console, requests, and errors. Tests use the
real typed store and typed replay result rather than arbitrary scientific dictionaries.

## Review gates

The architecture, cookie, Host/Origin, local CSRF, token, route/body, logical-size, capacity,
owner-mismatch, atomicity, process, container, observability, representation, and failure-status
decisions are closed by U4.3D, with the Referrer-Policy and Origin/Fetch-Metadata compatibility
contract superseded and closed by U4.3F.

U4.3E implementation gate result:

- the `/workbench` HTML scope implements `Referrer-Policy: same-origin` while other HTML retains
  `no-referrer` and non-HTML responses remain unaffected;
- every state-changing handoff POST requires exactly one canonical Origin and exactly one
  `Sec-Fetch-Site: same-origin`, with null and absent Origin rejected;
- implementation and security review approve conformance to this document;
- adversarial, concurrency, startup-policy, and non-disclosure tests pass;
- no migration, persistence, network, provider, artifact, or dependency is added;
- existing Workbench/scientific behavior remains unchanged; and
- the implementation remains default-off and local Solo Alpha-only.

These gates passed on 2026-07-12. The full repository suite was attempted with a 900-second cap,
timed out, and is not represented as passed. The focused and adjacent suites, browser QA, and
database/artifact/cache snapshot checks passed.

Before broader external review:

- implementation is merged;
- real-browser desktop/mobile/no-JavaScript QA passes;
- raw-TLE/token/session non-disclosure is independently reviewed;
- expiry, single use, owner mismatch preservation, and restart loss are independently reproduced;
- database, artifact, cache, and network snapshots remain unchanged; and
- the Solo Alpha follow-up report is updated without rewriting its historical verdict.

The required U4.3E real-browser gates are:

1. feature-disabled behavior remains unchanged;
2. feature-enabled natural custom-TLE form POST succeeds from the canonical origin;
3. replay uses the same source, observer, and interval;
4. duplicate consume returns the fixed unavailable response;
5. a second browser context receives owner mismatch without consuming the record;
6. the correct owner can consume after that mismatch;
7. expiry fails closed;
8. JavaScript-disabled submission succeeds and replay static content remains useful;
9. reduced-motion and mobile `390 x 844` behavior pass;
10. no normal-use CSP violation or external request occurs;
11. raw TLE, token, and session values are absent from URLs, JavaScript, logs, diagnostics, and
    user-facing errors; and
12. database, artifact, and cache snapshots remain unchanged.

## Deployment limitations

This architecture is unsuitable for multiple workers, horizontal scaling, reverse proxies,
non-loopback access, public deployment, or multiple authenticated users. It provides no durable
availability, distributed atomicity, authentication, authorization, rate limiting, or public CSRF
protection.

Broader use requires a new review covering HTTPS, trusted proxies/origins/hosts, authenticated
principals, tenant isolation, distributed atomic storage, encryption/retention, rate limiting,
monitoring, proxy logging, incident response, and deployment rollback.

## Open decisions

There are **no remaining material architecture decisions for the local single-process Solo Alpha
implementation**. The browser compatibility decision is closed and the approved implementation
conditions have been exercised. Future requests for localhost aliases, IPv6, HTTPS, reverse
proxies, multiple workers, non-loopback access, durable state, persistent audit, authentication,
or public deployment reopen architecture and security review.

Any request to support `localhost`, IPv6 loopback, HTTPS, reverse proxies, multiple workers,
non-loopback access, durable state, persistent audit, authentication, or public deployment reopens
architecture and security review and is not an implementation detail.

## Final recommendation

**U4.3E IMPLEMENTATION COMPLETE FOR MERGE REVIEW.**

The implementation conforms to the approved default-off, canonical-origin, single-process
transient handoff and the Workbench-only `same-origin` policy. It is merge-review-ready based on
the focused/adjacent validation and real-browser evidence recorded here. The full suite timed out
at 900 seconds, so no full-suite pass is claimed. This does not authorize public or multi-worker
deployment; authentication, authorization, complete CSRF protection, proxy support, durable audit,
and production readiness remain deferred.
