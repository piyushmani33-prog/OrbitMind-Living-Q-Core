# Offline Mission Workbench

## Purpose

The Offline Mission Workbench is a server-rendered browser surface for the deterministic
Mission Window Engine. It answers when a selected Earth-orbiting object is predicted to meet a
minimum elevation threshold for one fixed observer during an explicit UTC interval.

The workbench is a geometric planning aid for offline satellite observation, educational orbital
analysis, and ground-station contact-window exploration. It is not live tracking and is not
certified for command, maneuver, collision, or safety decisions.

## Browser flow

`GET /workbench` renders the bounded form. `POST /workbench/run` validates one request, invokes
`MissionWindowService`, and renders the result. There is no JSON API for this surface.

Successful bundled-catalog results include a POST-only `Replay this request` action that reuses
the same allowlisted catalog identity, observer, and interval. When the local Solo Alpha transient
handoff is explicitly enabled, successful custom-TLE results provide a separate temporary,
single-use POST action backed by bounded process memory. The browser receives only an opaque token;
raw TLE remains server-side and no catalog object is substituted. With the feature disabled,
custom results retain the honest unavailable guidance.

U4.3E is implemented behind the explicit default-off local Solo Alpha flag. Workbench HTML uses
the approved `Referrer-Policy: same-origin` compatibility scope, and enabled natural browser forms
send the canonical Origin plus `Sec-Fetch-Site: same-origin`. The handoff remains loopback-only,
single-process, non-authenticated, non-public, and non-production.

The form requires:

- exactly one offline orbital source;
- a fixed observer latitude, longitude, and altitude;
- an explicit UTC analysis start;
- a duration from 1 through 24 hours; and
- a minimum elevation from 0 degrees up to, but not including, 90 degrees.

Server local time, city lookup, browser geolocation, and network-derived defaults are not used.

## Supported offline sources

The bounded offline catalog reuses the reviewed sample registry. Catalog identifiers are selected
from its allowlist; the browser cannot submit a path, URL, or provider query.

The custom TLE mode accepts an optional safe display label and two bounded TLE lines through the
existing offline validation path. The TLE must parse and propagate. Raw TLE lines remain transient:
they are not written to a database, placed in a URL, or rendered in the result.

No CelesTrak or other provider is called. Network and provider defaults remain disabled.

## Result semantics

The useful result appears before implementation evidence. When one or more qualifying windows
exist, the first window shows:

- rise or clipped request-boundary time in UTC;
- peak and set or clipped request-boundary time in UTC;
- maximum elevation;
- duration; and
- rise, peak, and set azimuths with compact compass labels.

All additional windows are ordered in a table. The compass label is a friendly eight-sector
display derived from the exact calculated azimuth; the degree value remains authoritative.

## Empty and clipped results

A valid request with no qualifying event succeeds with an explicit empty state. It reports the
requested interval, source epoch, and threshold, and suggests changing the threshold or interval.
It is not presented as a calculation failure.

An event active at the request start uses the label `Active at analysis start`. An event continuing
past the request end uses `Continues after analysis end`. A full-interval event is labeled
`Window spans the full requested interval`. Request boundaries are not described as physical rise
or set crossings.

## Source age and limitations

Source age is calculated relative to the submitted analysis start, not the browser or server clock.
The visible accuracy panel includes the source epoch, maximum prediction offset from that epoch,
propagator and geometry identifiers, event-refinement tolerance, and coarse sample step.

Immediately beside the age value, the Workbench explains that age is the interval between the
orbital-element epoch and requested prediction, increasing age can reduce prediction fidelity,
and the value neither certifies freshness nor establishes a true current position.

The surface always states:

- predicted from the identified orbital element set using the pinned propagation and geometry
  model;
- geometric window only; optical visibility is not assessed;
- not live tracking and no guaranteed visibility;
- not certified for command, collision, or safety decisions; and
- UTC is used as a UT1 approximation, without full Earth-orientation or polar-motion corrections.

It provides no universal accuracy percentage or distance guarantee.

## Method and evidence

Checksums and method identifiers remain available in a collapsed `Method and evidence` disclosure.
It contains the deterministic input and result references, source checksum, trajectory reference,
schema and engine identifiers, observer coordinates, exact request interval, threshold, and the
complete limitation set.

The disclosure does not contain raw TLE lines, local filesystem paths, provider configuration,
secrets, database identifiers unrelated to the result, or internal exception details.

## Security and state boundary

The form body and each field are bounded. Unexpected or duplicate fields fail closed. Numeric
values must be finite and within the Mission Window Engine bounds. User-visible values are HTML
escaped, unsafe display labels are rejected, and errors use fixed safe messages without reflecting
orbital text.

Calculations are not durably persisted. The optional custom-TLE handoff uses a container-owned,
bounded, five-minute process-local record and a scoped 30-minute opaque session cookie. It is
default-off, single-process, loopback-only, and cleared at shutdown. It is not authentication,
authorization, browser storage, a process-global registry, durable audit, background job,
scheduler, network adapter, or artifact path.

## Deferred work

Public, reverse-proxied, multi-worker, durable, or authenticated custom-TLE handoff remains
deferred. Guarded fresh-source integration also remains separate and must preserve explicit
enablement, source policy, caching, attribution, freshness, and non-live safety language.

Live source search, city search, geolocation, map tiles, 3D globes, generated video, calculation
persistence, public APIs, collision analysis, agents, LLMs, and quantum behavior remain out of
scope.
