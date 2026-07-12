# Custom-TLE Transient Handoff Architecture

## Status

- **Document status:** Proposed; documentation only
- **Slice:** U4.3C
- **Date:** 2026-07-12
- **Design verdict:** **APPROVE DESIGN WITH REQUIRED DECISIONS**
- **Implementation authority:** None. This document does not authorize production code,
  persistence, a migration, authentication, deployment, or a network path.

Implementation remains gated on the decisions in [Review gates](#review-gates). The design is
limited to the local, single-process Solo Alpha environment.

## Problem statement

The Mission Workbench accepts a request-local custom TLE, validates it, and can calculate mission
windows or a trajectory replay when the raw lines are present in that request. A successful
custom-TLE mission-window result should be able to offer `Replay this request` without asking the
user to enter the same TLE again.

The handoff must not disclose raw TLE through HTML, URLs, JavaScript, browser storage, cookies,
logs, errors, artifacts, caches, or durable database records. It must not substitute a catalog
object and must not create a new provider or network path.

## Existing limitation

`POST /workbench/run` parses a bounded `WorkbenchForm`, resolves custom input through the existing
custom-TLE validator, builds a typed `MissionWindowRequest`, and renders a result. The rendered
result retains only safe display identity and checksum information. In particular, its stable
identity is `custom-tle:<element-checksum>`.

A checksum authenticates matching recovered input; it cannot reconstruct the two orbital-element
lines. `POST /workbench/replay` therefore cannot replay that result unless the user submits the raw
TLE again. U4.3B correctly leaves direct custom-TLE handoff unavailable and never falls back to a
bundled object.

Current related boundaries are:

- the Workbench body is bounded to 4,096 bytes;
- the existing validator bounds each TLE line to 100 characters and the optional label to 80;
- Workbench calculations do not persist missions, replay, artifacts, or source-cache entries;
- network, CelesTrak, and open research are disabled by default;
- the browser CSP permits only same-origin script and form actions and sets `connect-src 'none'`;
- the application container owns process-lifetime services;
- OrbitMind has no browser session framework or authenticated user principal;
- `get_current_owner_id()` is a fixed local-owner boundary for selected persisted APIs, not a
  browser identity and not suitable for binding two browser requests; and
- the existing governed `AuditEvent` path is database-backed. Reusing it would make lifecycle
  events durable and therefore needs an explicit persistence/privacy decision.

## Goals

- Carry one validated custom-TLE mission-window request into one trajectory replay.
- Keep raw TLE entirely server-side after the original POST.
- Bind the handoff to one short-lived local browser session and one replay-only purpose.
- Use an unguessable opaque identifier with fixed expiry and strict capacity limits.
- Guarantee atomic single use under concurrent submissions.
- Fail closed on absence, malformed input, expiry, reuse, owner mismatch, restart, or capacity
  exhaustion.
- Preserve the existing typed trajectory-replay service as scientific authority.
- Make lifecycle outcomes auditable without recording raw TLE, token, or session values.

## Non-goals

- Authentication, authorization, tenancy, or proof of human identity
- Public, multi-user, multi-worker, or distributed deployment
- Durable handoff recovery across restart
- Database, filesystem, artifact, browser-storage, or cache persistence
- Provider calls, source refresh, catalog substitution, or network access
- A general session framework or general-purpose cache
- Replay of any purpose other than custom-TLE trajectory replay
- Changes to SGP4, mission-window, geometry, or trajectory-replay calculations
- A complete CSRF solution for future public deployment

## Safety invariants

1. Raw TLE is never emitted in HTML, a URL, JavaScript, browser storage, a cookie, a log, an
   error, an artifact, a cache file, or a database record.
2. The client receives only a cryptographically random opaque handoff identifier.
3. The identifier is accepted only by a fixed same-origin POST endpoint for custom-TLE replay.
4. A record is bound to one ephemeral browser-session identity and one purpose.
5. Consumption atomically removes the record before replay calculation starts.
6. Missing, malformed, expired, consumed, owner-mismatched, or restart-lost state produces no
   replay and no source fallback.
7. Store capacity, per-session capacity, input sizes, and lifetimes are fixed and bounded.
8. Process shutdown clears all remaining state; process restart cannot recover it.
9. Audit output never contains raw TLE, token values, session-cookie values, raw request bodies,
   authorization headers, or local paths.
10. This mechanism is local request continuity, not authentication or authorization.

## Threat model

| Threat | Local Solo Alpha treatment | Residual/public-deployment concern |
| --- | --- | --- |
| Raw TLE in HTML or hidden fields | Raw lines remain only in the server record; client form carries the opaque identifier | Independent disclosure review remains required |
| Token in URL, Referer, browser history, or access-log query | POST body only; no GET route or query parameter; `Referrer-Policy: no-referrer` remains | Reverse-proxy request-body logging must be disabled/reviewed |
| Token leakage through analytics | No analytics or external reporting exists | Public telemetry policy remains required |
| Another browser/user replays a token | Record is bound to a separate opaque session cookie | Cookie theft and real user authorization require HTTPS and authentication |
| Replay after expiry | Monotonic deadline is checked while holding the store lock; expired record is removed | Distributed clock/store behavior is not addressed |
| Token reuse | Atomic pop means only one consumer can receive the record | Distributed atomicity is not addressed |
| Token guessing | 256 bits from an operating-system CSPRNG; fixed bounded parsing | Rate limiting remains required for public exposure |
| Token fixation | Server creates both session and handoff identifiers; client cannot select either | Session fixation controls need broader review with authentication |
| Cross-request source substitution | All source and replay inputs are stored in one immutable record; client cannot resubmit them | No residual substitution within this design |
| Catalog/ISS fallback | Explicitly prohibited on every failure | No residual fallback is accepted |
| Process restart or auto-reload | State is deliberately lost; replay fails closed | Usability and multi-worker routing remain limitations |
| Unbounded memory growth | Global and per-session caps, bounded record shape, TTL, and opportunistic cleanup | Host-level DoS and rate limiting remain public concerns |
| Excessive handoff creation | Per-session/global caps; capacity rejection does not retain input | Distributed abuse protection remains deferred |
| Concurrent duplicate consume | One short thread-safe critical section performs validation and pop | Multiple processes cannot share this atomicity |
| Error/debug leakage | Fixed browser errors and sanitized reason codes; no raw values in exceptions | Server/debug/proxy configuration requires deployment review |
| CSRF | SameSite=Strict, POST-only, opaque single-use token, and strict local Origin/Host checks reduce risk | Dedicated CSRF protection is still required before public deployment |
| Future multi-user use | Explicitly unsupported | Authentication, authorization, tenancy, HTTPS, shared atomic store, and rate limits are required |

The local design addresses accidental client disclosure, guessing, reuse, short-lived cross-request
continuity, bounded memory, and same-process races. It does not address a compromised browser,
host, process, or reverse proxy, nor does it provide public-deployment identity or abuse controls.

## Options considered

| Option | Confidentiality | Expiry / single use | Owner binding | Restart behavior | Complexity / auditability | Local Solo Alpha | Future multi-user |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A. Raw TLE hidden fields | Fails: raw TLE is in HTML | Client can replay indefinitely | None | Survives in page | Simple but disclosive | **Reject** | **Reject** |
| B. Raw TLE URL/query | Fails through history, Referer, and logs | Poor | None | URL survives | Simple and highly observable | **Reject** | **Reject** |
| C. Base64/reversible client value | Encoding provides no confidentiality | Replayable | None | Client retains it | Misleadingly simple | **Reject** | **Reject** |
| D. Signed/encrypted client payload | Encryption can protect content if keys are sound | Must add expiry/replay registry | Possible but complex | Survives process restart if keys do | Key rotation, body logging, size, replay state, and error handling are substantial | Not the smallest safe choice | Reconsider only with managed keys and full session/auth design |
| E. Bounded process-local store | Raw TLE stays server-side | Native TTL and atomic pop | Ephemeral session binding | Deliberate total loss | Small, reviewable, auditable in memory | **Recommended** | **Not suitable** |
| F. Database transient record | Server-side confidentiality | Transactional expiry/use possible | Auth principal possible | Can survive restart | Requires schema, cleanup, retention, encryption/access review | Defer; violates this slice's no-persistence boundary | Candidate only in a separately approved distributed design |
| G. localStorage/sessionStorage/cookie with raw TLE | Fails client non-disclosure boundary | Browser-controlled | Weak | Browser-dependent | Exposes source to scripts/storage tools | **Reject** | **Reject** |
| H. Catalog substitution | Avoids carrying raw TLE by changing scientific source | Irrelevant | Irrelevant | Irrelevant | Scientifically dishonest | **Reject** | **Reject** |

An encrypted client-carried payload is not recommended merely to avoid server memory. It would add
key custody, rotation, ciphertext logging, nonce, expiry, replay prevention, cookie/session
binding, and size concerns while still requiring server-side state for strict single use.

## Decision

The recommended initial architecture is an application-container-owned, bounded, process-local
transient handoff store. It is available only when the app runs as one process on loopback for
Solo Alpha.

After a custom-TLE mission-window request has passed existing form validation, custom-TLE
validation, and mission-window calculation, the server stores one immutable replay record. The
record contains the validated raw elements and every scientifically relevant request input. The
server renders only a 256-bit random opaque handoff identifier in a same-origin POST form.

`POST /workbench/replay/custom-handoff` is the recommended fixed route. A dedicated route makes
the replay-only purpose and strict one-field parser explicit and avoids overloading the existing
full Workbench form parser. It is not a JSON API and accepts no source, observer, interval, or TLE
fields from the browser.

The store hashes the presented handoff identifier for lookup and hashes the session identifier for
binding. Neither raw identifier is retained in records or emitted to audit. A constant-time
comparison should be used wherever digest comparisons are not delegated to exact dictionary-key
lookup.

## Session/owner binding

A safe owner-bound design is not possible in the current browser architecture without introducing
a minimal ephemeral session cookie. IP address and User-Agent are unstable, shared, spoofable, and
must not be used as owner identity.

The proposed local session contract is:

- server-generated 32 random bytes encoded as unpadded base64url;
- cookie name fixed by the implementation review, for example `orbitmind_local_session`;
- contains only the opaque random identifier, never TLE, credentials, ownership claims, or replay
  data;
- `HttpOnly`, `SameSite=Strict`, and `Path=/workbench`;
- 30-minute absolute lifetime, with no sliding extension from arbitrary requests;
- rotate by issuing a new identifier when absent or expired; do not accept a client-selected
  replacement;
- clear on expiry where a response can do so; server-side bindings expire independently;
- `Secure` must be true under HTTPS;
- for the explicitly approved loopback HTTP Solo Alpha command only, `Secure` must be false
  because browsers otherwise withhold it. This exception is not permitted for non-loopback HTTP;
  and
- no `Domain` attribute, so it remains host-only.

This cookie is an ephemeral browser correlation mechanism. It is not authentication, does not
identify a person, does not authorize access, and is not a multi-user tenancy boundary. The fixed
`local-owner` dependency is not reused because it would bind all local browsers to the same owner.

Session rotation invalidates prior handoffs for that browser because their binding digest no
longer matches. Consuming a handoff does not need to rotate the whole session; the handoff itself
is removed atomically.

## Transient record model

The later implementation should define frozen typed models rather than dictionaries. A record
needs only:

- handoff lookup digest (or the digest as its map key);
- session-binding digest;
- fixed purpose enum: `CUSTOM_TLE_TRAJECTORY_REPLAY`;
- monotonic creation and expiry deadlines;
- safe custom source label and stable source/checksum identity;
- validated TLE line 1 and line 2 required to reconstruct `PinnedOrbitElementSet`;
- validated observer latitude, longitude, and altitude;
- UTC replay start and end, or start plus bounded duration;
- selected deterministic replay sample interval and maximum sample bound; and
- immutable schema/version marker for fail-closed decoding across code changes, if needed.

Store all replay-defining inputs server-side. Resubmitting observer, interval, or sample settings as
hidden fields would be non-sensitive but would permit mutation between mission-window and replay
requests. Keeping them in the record guarantees that `Replay this request` means the exact source,
observer, interval, and sampling policy from the successful result. The trade-off is a slightly
larger record, still tightly bounded and short-lived.

Explicitly exclude passwords, provider keys, authorization headers, cookies, raw session values,
arbitrary headers, filesystem paths, arbitrary metadata, ORM objects, sessions/connections, full
HTML, client-generated state, mission records, artifacts, and unrelated form fields.

No consumed flag is required in the live record: successful lookup removes the record. A bounded
reason counter may record a consume outcome, but no token tombstone is required or exposed.

## Lifecycle and state transitions

The stored state model is intentionally small:

```text
validated request
      |
      v
  AVAILABLE --atomic pop--> CONSUMED (record absent)
      |
      +--deadline/capacity cleanup--> EXPIRED (record absent)

Any pre-storage or lookup failure --> REJECTED (event only; no record)
```

`CREATED` is an operation, not a durable state. `CONSUMING` is unnecessary because lookup,
validation, and removal occur in one lock-held operation with no `await` or scientific work inside
the critical section.

Lifecycle details:

1. Parse and validate the original custom-TLE form through the existing path.
2. Resolve the validated custom source and complete the mission-window calculation.
3. Ensure an approved local session exists; generate it server-side if needed.
4. Sweep expired records, then enforce per-session and global capacity while holding the lock.
5. Generate 32 CSPRNG bytes for the handoff and retry only on the practically impossible digest
   collision, with a fixed small retry bound.
6. Store the immutable record as `AVAILABLE`, bound to session and replay purpose.
7. Render a POST-only `Replay this request` form containing only the opaque identifier.
8. On consume, parse the identifier to its exact bounded format, hash it, acquire the store lock,
   sweep if due, find the record, verify purpose, expiry, and session binding, and atomically pop.
9. Release the lock and invoke the existing typed trajectory replay service using the returned
   immutable record.
10. If replay succeeds, render the existing replay page. If replay fails after pop, return a fixed
    sanitized error and do not reinsert the record. The user must resubmit the custom TLE.

Two concurrent submissions cannot both consume: one pop succeeds and the other sees unavailable
state. Duplicate submission, browser back/refresh, missing state, process restart, or auto-reload
also returns unavailable. Capacity rejection does not create a record and does not affect the
already completed mission-window result.

## Limits and expiry

Proposed conservative initial values, subject to implementation review:

| Limit | Proposed value | Rationale |
| --- | --- | --- |
| Handoff token entropy | 32 random bytes (256 bits) | Unguessable opaque capability identifier |
| Encoded token length | 43 unpadded base64url characters | Fixed bounded parser; no arbitrary token input |
| Handoff TTL | 5 minutes absolute | Enough for immediate handoff; small disclosure/replay window |
| Session TTL | 30 minutes absolute | Bounded local browser continuity without a persistent session |
| Global live records | 128 | Hard process-memory ceiling for Solo Alpha |
| Live records per session | 4 | Bounds repeated generation by one browser |
| TLE line length | Existing maximum 100 characters each | Reuse reviewed custom-TLE validator |
| Custom label length | Existing maximum 80 characters | Reuse reviewed label validator |
| Original Workbench body | Existing maximum 4,096 bytes | Preserve current parser boundary |
| Handoff POST body | Maximum 256 bytes | One fixed-name, fixed-length identifier plus form encoding |
| Cleanup cadence | At every create and consume; additionally when 30 seconds have elapsed since the last sweep | Deterministic request-driven cleanup without a scheduler |
| Collision retries | 3 | Fixed bounded behavior before sanitized internal failure |

Use `time.monotonic()` for in-process creation, expiry, and cleanup scheduling so wall-clock changes
cannot extend a handoff. Use UTC-aware wall time only for sanitized human/audit timestamps. On
shutdown, clear the whole store. No background scheduler is needed.

At the stated caps, raw orbital text is below 200 characters per record plus bounded typed data;
the implementation should still define a small maximum record-size assertion (proposed 2 KiB of
bounded scalar input) rather than rely on informal estimates.

## Request/UI contract

```text
POST /workbench/run (validated custom TLE)
  -> mission-window result
  -> POST /workbench/replay/custom-handoff
       handoff_id=<opaque identifier only>
  -> atomic server consume
  -> existing TrajectoryReplayService
  -> server-rendered predicted replay
```

Requirements:

- The action is a normal HTML form and needs no JavaScript.
- It uses one fixed same-origin action and POST only; there is no GET counterpart, redirect to an
  external origin, query parameter, or raw-TLE hidden field.
- The mission-window result states: the handoff is temporary, single-use, uses the same observer
  and interval, and opens a predicted replay that is not live tracking.
- The replay route accepts only the handoff field. Duplicate or unexpected fields fail closed.
- Existing CSP/security headers apply to success and error HTML.
- No missing/error path invokes catalog resolution or bundled ISS fallback.

Externally visible token-state failures should deliberately share one response to avoid revealing
whether another session owns a guessed identifier:

> This temporary replay handoff is unavailable or no longer valid. Return to the Workbench and
> submit the custom TLE again.

Use status 422 for malformed/missing submissions and 409 or 410 for a well-formed but unavailable
handoff, with the exact choice approved and tested. Owner mismatch, expired, consumed, restart-lost,
and unknown state must have the same body. Capacity failure on creation may say:

> A temporary replay handoff is not available right now. The mission-window result remains valid;
> return to the Workbench to try again.

An internal replay failure after consume uses the existing fixed calculation-failure wording and
never returns partial replay HTML or embedded payload.

## Failure semantics

| Condition | Required behavior |
| --- | --- |
| Missing or malformed identifier | No lookup beyond bounded parsing; no replay; fixed error |
| Unknown, expired, or already consumed | No replay; record absent/removed; fixed indistinguishable error |
| Owner/session mismatch | No replay; do not reveal ownership; fixed indistinguishable error |
| Wrong purpose | No replay; remove or reject according to approved invariant; fixed error |
| Process restart/reload | Empty store; no replay; fixed unavailable error |
| Capacity full | Do not retain raw TLE; render result without active handoff plus fixed guidance |
| Concurrent duplicate consume | Exactly one obtains the record; all others fail |
| Replay failure after consume | No reinsertion, no partial result, no fallback, sanitized error |
| Internal store exception | No token/source detail, no partial result, no fallback |

Every failure drops request-local raw values as soon as the request completes. Scientific services
must never receive missing, expired, reused, mismatched, or substituted source state.

## Audit and logging

Required lifecycle event names are:

- `custom_tle_handoff.created`
- `custom_tle_handoff.consumed`
- `custom_tle_handoff.expired`
- `custom_tle_handoff.rejected`
- `custom_tle_handoff.capacity_rejected`
- `custom_tle_handoff.owner_mismatch`
- `custom_tle_handoff.malformed_identifier`

Permitted fields are event type, UTC timestamp, fixed purpose, source checksum after successful
validation, source classification `custom-tle`, bounded reason code, result status, and an existing
safe correlation identifier if one is already available. The handoff/session values must not be
used as correlation identifiers.

For the initial local implementation, lifecycle observability should be bounded and memory-only:
typed counters plus a small fixed-size event ring (proposed maximum 256 sanitized events, cleared
on shutdown). Do not write these events through the existing database-backed `AuditEvent` path
without separate approval, because that changes the no-persistence guarantee. Structured process
logging may report aggregate event name and bounded reason code only if request-body logging is
disabled and tests prove token/session/TLE absence; otherwise counters are the safer initial
default.

Never record raw TLE, raw request body, token, session cookie, authorization/cookie headers,
arbitrary labels, local paths, or user-facing stack traces. Persistent governed audit integration
is an open decision, not silently included in this design.

## Concurrency and process lifecycle

- One store instance belongs to `AppContainer`, matching the existing app-lifetime ownership
  pattern.
- Use one thread-safe lock with a very small scope around sweep, capacity checks, insert, and
  consume/pop. FastAPI routes may cross thread boundaries, so an unprotected dictionary or an
  async-only lock is insufficient.
- Never hold the lock during TLE validation, mission-window calculation, trajectory propagation,
  HTML rendering, logging, or any `await`.
- Startup creates an empty store. Shutdown clears records, session bindings, and memory-only audit
  data.
- Request-driven cleanup removes expired records. A full global cap remains effective even if no
  cleanup request arrives.

A process-local store works only for a single application process. Multiple Uvicorn workers,
horizontal replicas, or load balancing can route creation and consume to different stores and
must be rejected by configuration or considered unsupported. Development auto-reload and process
restart intentionally invalidate every handoff. No sticky-session claim repairs atomicity across
workers.

A future multi-worker design requires a separately reviewed shared atomic store, authenticated
principal binding, encryption/access policy, retention cleanup, and deployment controls. It must
not silently switch this design to PostgreSQL.

## CSRF considerations

The proposed controls are defense in depth for loopback Solo Alpha:

- host-only `SameSite=Strict` ephemeral session cookie;
- POST-only fixed route;
- opaque replay-only single-use identifier;
- existing `form-action 'self'` CSP; and
- strict configured Host and Origin validation for state-changing Workbench POSTs. An absent Origin
  may be accepted only under a separately approved same-origin browser policy; a mismatched or
  non-loopback origin must fail closed.

The handoff token is not a complete CSRF token. SameSite does not replace origin validation, and
neither provides authentication. The application currently has no complete CSRF framework.

Conservative recommendation: implementation may precede a general CSRF slice only for explicitly
loopback-bound, single-process Solo Alpha after the exact Host/Origin policy is approved and tested.
Do not enable the mechanism on a non-loopback bind. Dedicated CSRF protection, HTTPS, `Secure`
cookies, trusted-host configuration, authentication, and authorization are mandatory before any
external or multi-user review.

## Privacy and non-disclosure

The design guarantees that normal client-visible state contains only an opaque handoff identifier,
safe result metadata, and an opaque session identifier. Neither identifier encodes or permits
reconstruction of raw orbital elements.

Fail-closed guarantees are:

- missing token -> no replay;
- malformed token -> no replay;
- expired token -> no replay;
- reused token -> no replay;
- owner mismatch -> no replay;
- process restart -> no replay;
- capacity failure -> no raw-TLE exposure and no retained record;
- internal exception -> sanitized HTML with no partial scientific result;
- every failure -> no catalog/ISS fallback, provider call, persistence, or artifact write; and
- every log/audit path -> no raw TLE, token, session value, raw body, or local path.

This is confidentiality minimization, not a claim that the host process memory is encrypted or
protected from an administrator, debugger, crash dump, or compromised runtime.

## Implementation test plan

The later implementation must add tests for:

1. successful custom-TLE mission-window-to-replay handoff;
2. exact source and element checksum preservation;
3. exact observer, UTC interval, duration, and selected sample interval preservation;
4. POST-only route and absence of a GET/query handoff;
5. raw TLE absent from HTML, URL, JavaScript, cookies, browser storage, logs, errors, audit, and
   response headers;
6. identifier format, 32-byte CSPRNG generation, uniqueness, and fixed parser bounds;
7. five-minute monotonic expiry and cleanup;
8. atomic single use and failure on refresh/resubmission;
9. two simultaneous consume attempts with exactly one success;
10. session owner mismatch without an ownership oracle;
11. malformed, missing, wrong-purpose, unknown, expired, and restart-lost identifiers;
12. global and per-session capacity limits and recovery after expiry;
13. startup-empty and shutdown-clear behavior;
14. no replay reinsertion after scientific or rendering failure;
15. no catalog/ISS fallback on every failure path;
16. sanitized HTML error responses retain CSP/security headers, including missing replay asset
    behavior;
17. database table counts, artifact tree, and source-cache tree unchanged before/after success and
    failure;
18. no provider or external network call, using an active fail-on-network probe;
19. fixed-size memory audit/counters omit token, session, TLE, body, headers, and paths;
20. session cookie attributes, rotation, expiry, path, loopback HTTP behavior, and future HTTPS
    `Secure` requirement;
21. Host/Origin acceptance and rejection according to the approved local CSRF decision;
22. no JavaScript requirement for handoff, useful mobile layout, and safe no-JavaScript flow;
23. raw-TLE security probes in label/lines do not escape validation or safe error boundaries; and
24. existing catalog handoff, Workbench, replay, CSP, no-network, architecture, and scientific
    regression suites remain unchanged.

Tests must exercise the real typed store and typed replay result. They must not use an arbitrary
dictionary as scientific state. Real-browser QA must inspect page source, URL, cookies, console,
requests, and errors for raw-TLE/token leakage.

## Review gates

Before implementation:

- architecture review approval;
- security review approval;
- explicit approval of the ephemeral session-cookie name, attributes, rotation, and local HTTP
  exception;
- explicit decision on the localhost Host/Origin checks and whether this narrow mechanism may
  precede general CSRF protection;
- approval of token entropy, TTLs, capacities, body/record bounds, and cleanup behavior;
- approval that audit remains bounded and memory-only, or separate approval for any persistence;
- acceptance of total loss on restart/auto-reload;
- acceptance and enforcement of the single-process, loopback-only limitation; and
- acceptance that this is not authentication and cannot be used for public/multi-user deployment.

Before broader external review:

- implementation is separately reviewed and merged;
- adversarial and concurrency tests pass;
- real-browser desktop/mobile/no-JavaScript QA passes;
- raw-TLE non-disclosure is independently reviewed;
- expiry, single use, owner binding, restart loss, and capacity rejection are independently
  reproduced;
- database, artifact, cache, and network before/after snapshots remain unchanged;
- CSP and browser-security behavior remains intact; and
- the Solo Alpha follow-up report is updated without rewriting its historical verdict.

## Deployment limitations

This architecture is intentionally unsuitable for multiple workers, horizontal scaling,
non-loopback access, public deployment, or multiple authenticated users. It provides no durable
availability, distributed atomicity, disaster recovery, authentication, authorization, rate
limiting, or full CSRF protection.

Broader use requires a new design review covering HTTPS, secure cookies, trusted origins/hosts,
authentication and authorization, tenant isolation, distributed atomic storage, encryption and
retention, rate limiting, operational monitoring, reverse-proxy log policy, and incident response.

## Open decisions

1. Approve the cookie name, 30-minute absolute session TTL, `/workbench` path, rotation semantics,
   and loopback-only `Secure=False` exception.
2. Approve the exact Host/Origin policy and whether implementation may proceed before a general
   CSRF mechanism.
3. Approve the proposed 5-minute handoff TTL, 128 global cap, four-per-session cap, 30-second
   request-driven sweep cadence, and 2 KiB record assertion.
4. Approve the dedicated `POST /workbench/replay/custom-handoff` contract.
5. Approve bounded memory-only audit counters/event ring, or explicitly authorize a later durable
   audit design.
6. Accept that auto-reload, restart, another worker, or another process always loses the handoff.
7. Decide whether the implementation must actively reject startup with more than one worker or
   merely leave this feature disabled outside the approved single-process mode.

## Final recommendation

**APPROVE DESIGN WITH REQUIRED DECISIONS.**

The process-local bounded store is the smallest architecture that can preserve raw-TLE
non-disclosure, exact scientific source continuity, expiry, atomic single use, and local browser
binding without adding durable persistence. Safe binding does require the proposed ephemeral
session cookie; the current fixed local owner is not sufficient.

Do not implement until the session-cookie contract, Host/Origin/CSRF position, exact limits, audit
behavior, and single-process enforcement are approved. Even after implementation, keep the feature
loopback-only and Solo Alpha-only until authentication, HTTPS, full CSRF protection, rate limiting,
and a distributed-state design receive separate approval.
