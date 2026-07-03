# Map/Orbit DTO Contract - OrbitMind Living Q-Core

## Purpose and status

This began as a docs-only contract. The contract itself authorized no API,
schema, router, persistence, rendering, frontend, Leaflet, CesiumJS, D3,
dashboard UI, provider/live-data, live tracking, command/task, recommendation,
Quantum Studio, or runtime implementation work.

Status update: Mission Map/Orbit Context v1 is implemented as a
domain-specific, coordinate-free, on-demand JSON route:

```text
GET /api/v1/map-orbit-contexts/mission/{mission_id}
```

This does not implement Map/Orbit Contexts generally. Coordinate payloads,
rendering, Leaflet, CesiumJS, D3, frontend, dashboard UI, provider/live-data,
live tracking, map/orbit persistence, generic dispatch, observation-study
map/orbit contexts, optimization-benchmark map/orbit contexts, cross-domain
contexts, Quantum Studio, and quantum implementation remain deferred.

Additional implementation remains blocked until separately planned, reviewed,
and merged.

This contract defines bounded read-only Map/Orbit Context semantics before any
map/orbit implementation. It narrows the broader
[Map / Orbit View Specification](MAP_ORBIT_VIEW_SPECIFICATION.md) for the first
future context surface.

## Map/Orbit Context v1 purpose

Map/Orbit Context v1 is a coordinate-free envelope and gate.

It defines safe mission map/orbit context metadata, references, artifact
handles, labels, limitations, and explicit coordinate-display boundaries before
any coordinate payload, renderer, frontend layer, basemap, tile provider, or
live tracking feature is introduced.

Coordinate-display DTOs require separate reviewed planning.

## Contract-not-implementation statement

This contract did not itself implement map/orbit APIs, DTOs, context schemas,
routes, rendering, frontend behavior, provider/live-data behavior, persistence
tables, or migrations. The later Mission Map/Orbit Context v1 implementation is
limited to the single domain-specific route named above.

It does not authorize map rendering, orbit rendering, Leaflet, CesiumJS, D3,
dashboard UI, PDF/export, live tracking, real-time position authority,
command/task surfaces, operational recommendation engines, approval workflows,
certification, signed receipt authority, Quantum Studio, quantum implementation
work, or general quantum advantage claims.

## First future scope

The first future implementation scope is mission-only map/orbit context.

The future context may include:

- `mission-ground-track-context`;
- `mission-orbit-context`.

Map/Orbit Context v1 uses one combined response:

```text
context_type = "mission-map-orbit-context"
```

The response may contain both `map_context` and `orbit_context`. V1 does not
define separate response types for map context and orbit context. V1 does not
add a path segment or query parameter for choosing context type.

Observation-study map/orbit contexts, optimization-benchmark map/orbit
contexts, and cross-domain map/orbit contexts remain deferred.

## Implemented mission route

The implemented Mission Map/Orbit Context v1 route is:

```text
GET /api/v1/map-orbit-contexts/mission/{mission_id}
```

No other map/orbit context route is implemented by this status update.

Route rules:

- domain-specific mission route only;
- JSON-only;
- generated on demand;
- no persistence;
- no generic dispatcher;
- no query parameters;
- reject all query parameters;
- reject `owner_id`, `principal`, and `user_id`;
- reject render options;
- reject provider switches;
- reject tile options;
- reject live-data switches;
- invalid or path-like `mission_id` returns a typed sanitized `422`;
- missing mission returns `404`.

The route uses product-noun naming. Wire values use
`Map/Orbit Context`, `map-orbit-context-v1`, and `map-orbit-contexts` wording
instead of exposing DTO implementation jargon on the wire.

## Schema and version naming

The schema version is:

```text
map-orbit-context-v1
```

Top-level fields are:

- `schema_version`;
- `context_id`;
- `read_at`;
- `source_domain`;
- `scope_id`;
- `context_type`;
- `inputs_and_provenance`;
- `map_context`;
- `orbit_context`;
- `evidence_status`;
- `limitations`;
- `disclaimer`.

Pinned values:

```text
schema_version = "map-orbit-context-v1"
source_domain = "mission"
scope_id = "mission:{mission_id}"
context_type = "mission-map-orbit-context"
context_id = "map-orbit-context:mission:{mission_id}:v1"
```

`read_at` must be timezone-aware UTC.

## Safe content

Safe future context content may include:

- existing safe IDs and handles;
- mission visual manifest ID or reference;
- static artifact handles and checksum handles for reviewed artifacts such as
  `ground_track` and `altitude_vs_time`;
- source labels;
- freshness labels;
- test-only labels;
- limitations;
- coordinate payload status marker.

Map/Orbit Context v1 is not a coordinate payload. It is not a renderer input
format for map layers, orbit tracks, basemap tiles, or frontend drawing.

## Coordinate payload marker

Coordinates are absent in v1 by policy, not because evidence is missing.

Use this marker:

```text
coordinate_payloads = "excluded-by-design-in-v1"
```

Do not use `withheld` for coordinates excluded by v1 design. Reserve
`withheld`, `unavailable`, and `integrity-failed` for genuine evidence states.

Missing coordinates must not be replaced with inferred coordinates,
interpolated tracks, generated prose, model-created trajectories, or guessed
map/orbit geometry.

## Unsafe content

Map/orbit contexts must exclude:

- raw coordinate arrays;
- raw trajectory arrays;
- raw sample arrays;
- raw interval arrays;
- raw TLE lines;
- ephemeris internals;
- artifact paths;
- artifact file contents;
- PNG or image bytes;
- sidecar paths;
- sidecar JSON;
- provider state;
- cached provider payloads;
- external tile or provider URLs;
- frontend layer specifications;
- render instructions.

## Authoritative inputs

Authoritative inputs remain:

- persisted records;
- authenticated read paths.

For the first future mission context:

- mission visual manifest projection may be used as a safe discovery/index
  input;
- persisted mission metadata and source labels may be used where already safely
  exposed;
- visual manifests remain discovery/index projections, not proof;
- static reports are references only, never evidence;
- provenance graphs are references only, never evidence.

Persisted records and authenticated read paths remain the evidence sources.

## Forbidden inputs

Map/orbit contexts must never read or treat as authoritative:

- raw sidecars;
- raw TLEs;
- raw samples;
- raw intervals;
- raw coordinate streams;
- raw `request_json`;
- raw `result_json`;
- raw `link_json`;
- PNG or image bytes;
- artifact filesystem paths;
- provider state;
- cached provider payloads;
- external basemap services;
- external tile services;
- external terrain services;
- external imagery services;
- external metadata services;
- static reports as evidence;
- provenance graphs as evidence.

## Owner-scoping plan

Mission records are not currently owner-scoped.

Future mission map/orbit context v1 should inherit the current mission read
model. It must reject `owner_id`, `principal`, and `user_id` query parameters.
It must not claim owner isolation that does not exist.

Owner-scoped observation-study map/orbit contexts remain deferred until owner
semantics, scope handles, and coordinate/interval DTO rules are separately
reviewed.

Cross-domain map/orbit contexts remain deferred.

## Withheld and evidence-state vocabulary

Reserve these labels for genuine evidence states:

- `withheld`;
- `unavailable`;
- `integrity-failed`.

Do not use `withheld` for coordinate payloads excluded by v1 design.

Missing evidence must be represented as unavailable or withheld, never guessed.
Unavailable evidence must not be replaced by inferred coordinates,
interpolated tracks, generated prose, or model-created trajectories.

## Failure-semantics inheritance rule

Each future map/orbit context inherits the failure semantics of its parent read
product or domain.

Examples:

- mission v1 is tolerant like the mission visual manifest when optional
  sidecar/PNG artifacts are absent, if the context only references safe
  DB-backed handles and labels;
- future optimization context must fail closed like the optimization manifest
  and report when authenticated evidence fails;
- future owner-scoped observation-study context must use study-family hidden
  `404` behavior for cross-owner records.

No partial context body should be emitted on integrity failure unless the
governing domain contract explicitly allows a withheld-only section.

## Real-time and live-tracking exclusions

Map/orbit contexts must not introduce or imply:

- live tracking;
- real-time position authority;
- current orbital truth;
- live satellite state;
- operational ephemeris authority;
- live orbit simulation;
- live polling;
- live refresh behavior.

Pinned or sample TLE-derived content, if referenced in a later reviewed slice,
must be labeled offline/model-derived and not live.

## Provider and live-data exclusions

Map/orbit contexts must exclude:

- provider fetches;
- CelesTrak;
- Space-Track;
- NASA Earthdata;
- commercial map/orbit providers;
- external orbital services;
- provider credentials;
- cached provider payloads unless separately reviewed;
- external basemap calls;
- external tile calls;
- external terrain calls;
- external imagery calls;
- external metadata calls.

The default assumption is offline, persisted, or bundled references only.

## Operational exclusions

Map/orbit contexts must never imply:

- operational access;
- observation command authority;
- taskability;
- command readiness;
- approval;
- certification;
- operational recommendation;
- autonomous decision-making;
- precise pointing commands.

No command, task, or recommendation fields should exist.

## Receipt and signing plan

Mission map/orbit context v1 should not include receipt or signing fields.

If a later optimization context is referenced, `receipt_status = "signed"` may
only mean persisted record-integrity provenance.

It must never mean:

- approval;
- authorization;
- certification;
- operational clearance;
- command readiness;
- signed receipt authority.

Map/orbit contexts must never expose:

- receipt envelopes;
- signatures;
- HMACs;
- signer identity;
- key IDs or configuration;
- key material;
- recomputed digests.

## Quantum plan

Quantum evidence should not appear directly in map/orbit contexts.

If quantum context is indirectly referenced later, it remains diagnostic only.

Map/orbit contexts preserve:

- no quantum authority;
- no general quantum advantage.

Map/orbit contexts must never expose:

- raw quantum samples;
- circuits;
- QUBO internals;
- solver internals;
- provider state.

## Non-leakage plan

Non-leakage rules apply to:

- context content;
- labels;
- evidence states;
- errors;
- examples;
- tests;
- documentation examples.

Map/orbit contexts must never expose:

- artifact paths;
- sidecar paths;
- raw sidecar JSON;
- artifact root values;
- raw TLE lines;
- samples;
- intervals;
- trajectory arrays;
- coordinate streams;
- ephemeris internals;
- raw `request_json`;
- raw `result_json`;
- raw `link_json`;
- SQL;
- stack traces;
- DB URLs;
- environment values;
- secrets;
- credentials;
- internal correlation IDs;
- idempotency keys;
- receipt internals;
- quantum evidence;
- QUBO;
- solver internals;
- provider state;
- cached provider payloads;
- operational commands;
- operational recommendations.

## Deterministic-output rules

Future implementation must require:

- deterministic context IDs;
- timezone-aware UTC `read_at`;
- stable field sets;
- stable ordering for arrays;
- no recomputation;
- no hidden analysis;
- no generated narrative presented as findings;
- byte-identical responses after normalizing only `read_at`.

## PostgreSQL and migration gates

No PostgreSQL validation is needed for this docs-only contract.

Any future implementation that reads persisted records must include migrated
PostgreSQL validation with:

- no `create_all()`;
- success and missing-record paths;
- non-leakage checks;
- deterministic-output checks;
- provider/network exclusion checks;
- Alembic head verification remains `m8b9c0d1e2f3`;
- zero skips when the database is configured for final review.

No migration is expected for a future v1 implementation. Map/orbit persistence
tables are out of scope.

Any proposed map/orbit persistence table requires separate reviewed planning.

## Future implementation test gates

Future implementation tests should include:

- success context for a persisted mission;
- exact top-level and section field sets;
- query parameter rejection;
- owner/principal/user rejection;
- render/provider/tile/live query rejection;
- invalid or path-like `mission_id` returning `422`;
- missing mission returning `404`;
- deterministic output after normalizing `read_at`;
- manifest consistency for safe artifact handles and checksums;
- `coordinate_payloads = "excluded-by-design-in-v1"`;
- no raw coordinates;
- no raw TLEs;
- no samples;
- no intervals;
- no paths;
- no sidecars;
- no SQL, stack traces, or secrets;
- no provider state;
- no receipt internals;
- no quantum fields;
- no QUBO or solver internals;
- no recompute, regeneration, or provider fetches;
- no rendering, frontend, D3, Leaflet, or CesiumJS imports;
- no mutation routes;
- no generic dispatcher;
- PostgreSQL validation if persisted records are read.

## Explicit exclusions

This contract does not implement or authorize:

- map/orbit API implementation;
- map/orbit DTO implementation;
- map/orbit context schema implementation;
- map/orbit route implementation;
- rendering;
- D3;
- Leaflet;
- CesiumJS;
- frontend;
- dashboard UI;
- PDF/export;
- provider/live-data behavior;
- live tracking;
- real-time position authority;
- command/task surfaces;
- operational recommendation engines;
- approval workflow;
- certification;
- signed receipt authority;
- map/orbit persistence tables;
- migrations;
- generic dispatcher;
- cross-domain context expansion;
- observation-study map/orbit context;
- optimization-benchmark map/orbit context;
- Quantum Studio;
- quantum implementation;
- general quantum advantage claims.

## Future gates

Future implementation requires separate reviewed planning for:

- route and schema implementation, if any;
- selected source-domain read path;
- source-domain failure semantics;
- owner-scoping caveats or isolation;
- coordinate-display DTOs, if any;
- interval-display DTOs, if any;
- deterministic-output tests;
- redaction and non-leakage tests;
- provider/network exclusion tests;
- PostgreSQL validation if persisted records are read;
- rendering, Leaflet, CesiumJS, D3, or frontend only after separate approval.
