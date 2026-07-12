# Browser Security Baseline

OrbitMind's browser surfaces in this phase are server-rendered HTML pages for the
reviewer sandbox and offline Mission Workbench. They are not a public production
deployment boundary. They are designed to avoid accidental script execution,
external browser fetches, raw orbital-data exposure, and broad static-file serving
while preserving the existing offline scientific workflows.

## Content Security Policy

HTML responses receive this CSP:

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

Directive rationale:

- `default-src 'none'` starts from a deny-by-default browser policy.
- `script-src 'self'` allows only the packaged same-origin replay controller.
- Executable script does not use `unsafe-inline`, and `unsafe-eval` is not
  allowed.
- `style-src 'unsafe-inline'` is a temporary compatibility allowance for the
  current server-rendered inline CSS. Removing inline CSS is future hardening.
- `img-src 'self' data:` permits same-origin artifact images and small inline
  SVG/data imagery already used by the server-rendered pages.
- `font-src 'none'` prevents remote or local web-font loading.
- `connect-src 'none'` prevents browser-side fetch, XHR, WebSocket, EventSource,
  beacon, and similar network calls.
- `object-src 'none'`, `worker-src 'none'`, `media-src 'none'`, and
  `manifest-src 'none'` block browser features that are not needed here.
- `base-uri 'none'` prevents injected base URL rewriting.
- `frame-ancestors 'none'` prevents embedding the pages in another site.
- `form-action 'self'` keeps form submissions on the same origin.

## Replay Controller Asset

The animated trajectory replay controller is served from the explicit allowlisted
route:

```text
GET /assets/trajectory-replay.js
```

This is not a generic static mount. It returns only the reviewed replay asset,
does not accept a user-controlled path, does not list directories, and does not
expose filesystem paths. The asset is loaded with `importlib.resources` from the
installed `orbitmind.api.assets` package data so installed-package behavior does
not depend on the current working directory.

The asset response uses:

- `Content-Type: application/javascript; charset=utf-8`
- `X-Content-Type-Options: nosniff`
- `Cache-Control: no-store`

If the packaged asset is unavailable, the route returns a fixed sanitized server
error without local paths or tracebacks.

## Inert Replay Payload

Replay data is embedded as inert display data inside:

```html
<template id="trajectory-replay-data">...</template>
```

The browser controller parses the template text and only moves the marker between
server-generated samples. It does not propagate orbits, calculate frames,
geodetic coordinates, look angles, source age, or scientific values.

The payload serializer escapes at least:

- `<`
- `>`
- `&`
- U+2028
- U+2029

This prevents values such as `</template><script>...` from closing the inert data
container and becoming executable markup. The payload and asset do not include
raw TLE lines, raw provider content, local filesystem paths, secrets, environment
values, or internal exceptions.

## Browser Security Headers

HTML responses also receive:

- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`
- `X-Frame-Options: DENY`
- `Permissions-Policy` disabling geolocation, microphone, camera, payment, USB,
  magnetometer, gyroscope, and accelerometer.

HSTS is intentionally not enabled for local HTTP development. It should be
introduced only at the HTTPS termination layer for a reviewed private or public
deployment.

COOP and COEP are deferred. OrbitMind is not using cross-origin isolation,
SharedArrayBuffer, external subresources, or browser-side compute that requires
those headers in this phase. They should be revisited with deployment and
third-party resource decisions.

No external script, font, CDN, map-tile, telemetry, or analytics access is
allowed by this baseline.

### U4.3F Workbench compatibility decision

U4.3F is documentation-only. The currently implemented header remains
`Referrer-Policy: no-referrer` on this branch. A resumed U4.3E implementation must
apply this narrowly scoped exception:

- HTML responses for the exact `/workbench` path and the `/workbench/` subtree,
  including safe HTML errors, use `Referrer-Policy: same-origin`;
- reviewer and other HTML surfaces retain `Referrer-Policy: no-referrer`; and
- JSON, the allowlisted JavaScript asset, artifacts, binary downloads, and other
  non-HTML responses remain outside the HTML Referrer-Policy middleware scope.

Chrome `150.0.7871.114` on Windows 10 was tested with identical top-level
same-origin POST forms. With `no-referrer`, Chrome sent `Origin: null` and no
`Referer`. With `same-origin`, it sent the exact canonical Origin and the full
same-origin page URL as `Referer`. The result was the same with JavaScript
disabled. The controlled matrix also tested the browser default,
`strict-origin`, `strict-origin-when-cross-origin`, `origin`, and
`origin-when-cross-origin`; all except `no-referrer` retained the canonical
Origin in this same-origin case.

This is expected Fetch behavior rather than evidence of an opaque production
document. For a non-CORS POST, the Fetch Standard sets serialized Origin to
`null` under `no-referrer`; `same-origin` retains it when the initiator and target
origins match. See the WHATWG
[Fetch Standard](https://fetch.spec.whatwg.org/#origin-header) and the
[Referrer Policy specification](https://w3c.github.io/webappsec-referrer-policy/).

`same-origin` is selected instead of `strict-origin` because it sends no Referer
on cross-origin requests. It does disclose the full Workbench page URL to the
same OrbitMind origin. That is accepted for local Solo Alpha because Workbench
URLs contain no raw TLE, handoff token, session identifier, credential, or other
sensitive state; the handoff token remains only in a bounded POST body. Any
future proposal to place sensitive state in a Workbench URL reopens this decision.

The exception does not permit an external form action, script, font, map, fetch,
or redirect. CSP remains unchanged, including `form-action 'self'`,
`connect-src 'none'`, and `frame-ancestors 'none'`. It does not weaken exact Host,
Origin, Fetch-Metadata, cookie, token, single-use, or owner-binding checks. It
does not make OrbitMind production-ready.

## Production Readiness Boundary

This browser-security baseline is defense-in-depth for local and private review
surfaces. It does not make OrbitMind production-ready.

Before any public or external VM deployment, OrbitMind still needs reviewed:

- HTTPS termination
- trusted host and origin configuration
- authentication and authorization
- CSRF strategy
- rate limiting and abuse controls
- operational logging and alerting
- dependency and security scanning
- deployment review and rollback procedure

Those controls are not implemented by U4.2C1.
