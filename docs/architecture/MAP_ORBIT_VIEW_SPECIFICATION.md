# Map / Orbit View Specification - OrbitMind Living Q-Core

## Purpose and status

This is a docs-only Phase 5 map/orbit view specification.

It does not implement map rendering. It does not implement orbit rendering. It
does not implement CesiumJS, Leaflet, D3, frontend, dashboard, export, PDF
generation, report generation, graph API routes, map/orbit API routes,
map/orbit persistence tables, provider/live-data behavior, satellite/live
tracking, live orbit simulation UI, or Quantum Studio.

This specification gates future map rendering, orbit rendering, CesiumJS,
Leaflet, frontend/dashboard, API, persistence, provider/live-data behavior, and
coordinate-display DTO work. Future rendering, API, UI, provider, or
coordinate-display DTO work requires separate planning and review.

## Definition

A future map/orbit view is read-only and non-authoritative. It is a
deterministic projection over existing persisted records and authenticated read
paths, and it may reference safe visual manifests, static reports, and
provenance/study graph references.

A map/orbit view is offline/model-derived visual context only. It is not proof
by itself. It is not evidence by itself. It is not live tracking, real-time
position authority, provider/live-data behavior, observation command authority,
operational access, taskability, command readiness, approval, certification,
signed receipt authority, causal proof, complete lineage, quantum authority, a
general quantum advantage claim, or an operational recommendation.

## Current reviewed baseline

Existing static visual artifacts such as `ground_track` and
`altitude_vs_time` are the current reviewed baseline.

Future map/orbit views are a possible later evolution of already-reviewed
static outputs. Future interactive views must not be treated as new evidence
sources. Any future interactive map or orbit view requires separate
implementation planning and review.

## Deterministic projection rule

Map/orbit view content must be a deterministic projection of persisted fields
and reviewed safe projections.

A map/orbit view must not recompute scientific values, perform hidden analysis,
fetch live provider data, or present generated narrative as findings.
Model-generated claims must not be presented as evidence.

Map/orbit content must not upgrade the epistemic status of underlying records.
Appearing in a map/orbit view never makes a record live, verified, approved,
certified, operational, taskable, command-ready, or real-time authoritative.

## Withheld evidence fail-closed rule

If an underlying authenticated read fails, is missing, is unauthenticated, is
withheld, is cross-owner, or is integrity-failed, the view must reflect an
unavailable or withheld status.

The view must never fabricate, substitute, infer, interpolate, extrapolate,
summarize around, or smooth over missing evidence. Unavailable evidence must
not be replaced by generated prose.

Unavailable map/orbit geometry must not be replaced by guessed coordinates,
guessed tracks, or inferred trajectories. Raw error internals must not leak.

## Safe v1 view types

Future v1 map/orbit surfaces may use these semantic view types only after a
separate implementation review:

- `mission-ground-track-map`;
- `mission-orbit-context-view`;
- `observation-site-map`;
- `observation-visibility-summary-map`;
- `study-chain-context-map`.

These are future semantic view types only, not implemented views.

## Map-view semantics

Map views may provide 2D geospatial context over:

- persisted/offline records;
- safe persisted site labels;
- safe site coordinates only when already allowed by reviewed data surfaces;
- artifact handles;
- checksums;
- source labels;
- freshness labels;
- test-only labels;
- study-chain summaries.

Map views must not be live tracking, operational access, command surfaces,
provider-backed real-time maps, observer-private-location disclosure surfaces,
pointing-command surfaces, or operational planning authority.

## Orbit-view semantics

Orbit views may provide bounded model-derived orbit context over:

- already persisted records;
- reviewed manifest projections;
- safe source labels;
- freshness labels;
- test-only labels;
- safe handles and checksums;
- reviewed static artifacts.

Orbit views must not include live position authority, raw trajectory streams,
recomputation, raw TLE lines, raw ephemeris internals, live provider data, live
satellite state, live orbit simulation UI, or operational pointing or
observation commands.

## Safe data sources

Map/orbit views may use only safe references to:

- mission visual manifests;
- optimization-benchmark visual manifests only as non-geospatial context
  references, if needed;
- mission artifact handles and checksums;
- persisted mission source labels;
- observation geometry request/run summaries;
- geometry and study checksums;
- study-chain records;
- integrity-summary records;
- provenance/study graph references;
- static report references.

Persisted records and authenticated read paths remain the evidence sources.

## Safe identifiers and handles

Map/orbit views may use only:

- existing safe IDs;
- route references;
- manifest IDs;
- report IDs;
- study graph node handles;
- source record handles;
- checksum handles;
- `sha256:<checksum>` handles.

Map/orbit views must not expose raw paths or raw internal payloads.

## TLE and orbital-data wording

Pinned or sample TLE data is not live satellite status.

Orbital content must be labeled offline/model-derived. Raw TLE lines, raw
ephemeris internals, raw trajectory arrays, and raw coordinate streams must
never be exposed.

Map/orbit views must not claim real-time position authority.

Future display-specific coordinate DTOs require separate review. Any coordinate
DTO must be deterministic, bounded, rounded or redacted as needed, and tested.

## Raw samples and intervals wording

Raw samples are excluded by default. Raw intervals are excluded by default.

A future implementation requires a separate reviewed DTO before exposing any
decimated, rounded, display-specific coordinate or interval payload. Display
payloads must not expose raw samples or raw intervals directly.

Any display payload must be deterministic, bounded, redacted, and tested.
Visibility summaries are allowed as summaries only. Interval payloads require
separate review.

## Basemap and tile-source network rule

Interactive maps commonly fetch basemap tiles, terrain, imagery, or map
metadata from external services.

Such fetching is provider/live-data behavior and a hidden network call. Future
map/orbit views must not fetch external basemap, tile, terrain, imagery, or
metadata sources without separate review.

Offline or bundled tiles and explicitly persisted static assets are the default
assumption. Generated map tiles are out of scope. Cached provider payloads are
out of scope unless separately reviewed.

Any future tile, terrain, imagery, or metadata source requires separate
planning, redaction review, network-boundary review, and operator disclosure.
This applies to OpenStreetMap-style tile servers, Cesium ion-style services,
commercial map APIs, and any other external tile, terrain, imagery, or provider
service.

## Live and provider wording

Map/orbit views must not introduce:

- live tracking;
- provider fetch;
- live CelesTrak;
- Space-Track;
- NASA Earthdata;
- external orbital/provider services;
- provider credentials;
- real-time ephemeris authority;
- operational provider state;
- live satellite state;
- live orbit simulation;
- cached provider payloads unless separately reviewed.

Named providers and generic external provider services are both excluded unless
a future reviewed source boundary explicitly approves them.

## Uncertainty and freshness wording

Map/orbit views should use source labels, freshness labels, test-only labels,
limitations text, and offline/model-derived labels.

Map/orbit views must not add confidence percentages to deterministic
calculations. They must not imply freshness beyond persisted record timestamps
or source labels. They must not claim live validity, real-time orbital state,
or present stale records as current.

## Receipt and signing wording

If a map/orbit view references signed optimization or report context,
`receipt_status = "signed"` remains only a persisted record-integrity
provenance signal.

It is not approval, authorization, certification, operational clearance,
command readiness, or signed-receipt authority.

Map/orbit views must never expose:

- receipt envelopes;
- canonical receipt entries;
- signatures;
- HMACs;
- signer identity;
- signing key IDs or configuration;
- signing key internals;
- key material;
- recomputed digests.

## Quantum evidence wording

Quantum evidence should not appear directly in map/orbit views.

If quantum context is referenced indirectly through manifests or reports, it is
diagnostic only.

Map/orbit views must not imply quantum authority, a general quantum advantage
claim, or provider/live-data behavior. They must not expose raw samples,
circuits, QUBO internals, solver internals, or unredacted quantum evidence.

## Map/orbit-specific exclusions

Map/orbit views must not expose:

- raw trajectory arrays;
- raw coordinate streams;
- precise operational pointing commands;
- observation command payloads;
- live satellite state;
- real-time ephemeris payloads;
- provider credentials;
- observer private location values beyond safe persisted site labels;
- generated map tiles;
- cached provider payloads unless separately reviewed;
- external basemap, tile, terrain, or imagery payloads unless separately
  reviewed.

## General exclusions

Map/orbit views must not expose:

- artifact paths;
- sidecar paths;
- raw sidecar JSON;
- artifacts-root value;
- DB URLs;
- environment values;
- SQL;
- stack traces;
- secrets;
- credentials;
- internal correlation IDs;
- idempotency keys;
- receipt envelopes;
- canonical receipt entries;
- signatures;
- HMACs;
- signer identity;
- signing key IDs or configuration;
- signing key internals;
- key material;
- recomputed digests;
- unredacted quantum evidence;
- raw samples;
- raw intervals;
- raw TLE lines;
- raw ephemeris internals;
- raw `result_json`;
- raw `request_json`;
- raw `link_json`;
- raw planning snapshots;
- raw provenance snapshots;
- solver internals;
- QUBO internals;
- provider state;
- operational recommendations.

These exclusions apply to view content, map labels, orbit labels,
popups/tooltips, legends, hover states, withheld or unavailable states, errors,
examples, tests, and documentation examples.

## Relationship to visual manifests

Map/orbit views may reference mission and optimization-benchmark visual
manifests as discovery/index inputs.

Visual manifests are not proof. Visual manifests are not live map/orbit
sources.

Additional visual manifest domains remain deferred and require separate review.

## Relationship to static reports

Static reports may be referenced as summary/index artifacts.

Reports are not evidence or authority. Reports do not make map/orbit views
operational. Map/orbit views do not make reports operational.

## Relationship to provenance/study graphs

Graph nodes and edges may provide bounded lineage context.

Map/orbit views must not claim complete lineage. Map/orbit views must not claim
causal proof.

Graph references must follow the edge-projection and owner-scoping semantics
from the provenance/study graph semantics specification. Graph references are
not proof by themselves.

## Relationship to dashboards

Future dashboards may reference map/orbit view summaries or withheld states.

Dashboards must follow the
[dashboard view specification](DASHBOARD_VIEW_SPECIFICATION.md). Dashboard
references do not add operational authority, live tracking, provider data, or
map/orbit rendering.

## Out of scope

This specification does not add:

- map rendering;
- orbit rendering;
- CesiumJS;
- Leaflet;
- D3;
- frontend/dashboard;
- export;
- PDF;
- report generation;
- graph API routes;
- map/orbit API routes;
- map/orbit persistence tables;
- migrations;
- new visual manifest domains;
- generic dispatcher;
- provider/live-data behavior;
- satellite/live tracking;
- live orbit simulation;
- Quantum Studio;
- quantum implementation work;
- operational recommendations;
- causal inference;
- complete lineage claims;
- observation command payloads;
- precise operational pointing commands;
- external basemap, tile, terrain, or imagery fetching.

## Future gates

Future map/orbit implementation requires separate reviewed planning for:

- map/orbit API or CLI, if any;
- selected scope handles;
- owner-scoping and cross-domain isolation;
- coordinate-display DTOs;
- interval-display DTOs;
- map/orbit materialization strategy, if any;
- deterministic-output tests;
- redaction tests;
- network-boundary review;
- tile, terrain, or imagery source review;
- operator disclosure for any external source;
- PostgreSQL validation if persisted records are read;
- dashboard references only under
  [DASHBOARD_VIEW_SPECIFICATION.md](DASHBOARD_VIEW_SPECIFICATION.md);
- rendering, CesiumJS, Leaflet, or frontend only after separate approval;
- the [Phase 5 visual-planning closure audit](PHASE_5_VISUAL_PLANNING_CLOSURE_AUDIT.md),
  which closes planning only and authorizes no implementation.
