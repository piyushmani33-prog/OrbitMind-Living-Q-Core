# Dashboard View Specification - OrbitMind Living Q-Core

## Purpose and status

This is a docs-only Phase 5 dashboard view specification.

No dashboard artifact exists today. Dashboards are purely future.

This specification does not implement dashboard UI, frontend, charts, widgets,
D3, rendering, report generation, export, PDF generation, graph rendering,
map/orbit rendering, dashboard API routes, dashboard persistence tables,
provider/live-data behavior, live tracking, command/task surfaces, operational
recommendation engines, or Quantum Studio.

This specification gates future dashboard UI, frontend, charts, widgets,
rendering, APIs, persistence, live/provider behavior, action/task surfaces, and
recommendation behavior. Future dashboard UI, API, rendering, frontend, or
persistence work requires separate planning and review.

## Definition

Future dashboards are read-only and non-authoritative deterministic
projections over existing persisted records and authenticated read paths. They
may reference reviewed visual manifest, static report, provenance graph, and
map/orbit references.

A dashboard is a summary/status view only. It is not proof by itself. It is not
evidence by itself. It is not live monitoring, live tracking, provider/live-data
behavior, an operational command center, taskability, command readiness,
approval, certification, signed receipt authority, an operational
recommendation, autonomous decision-making, causal proof, complete lineage,
quantum authority, or a general quantum advantage claim.

## Deterministic projection rule

Dashboard panel/card content must be a deterministic projection of persisted
fields and reviewed safe projections.

Dashboards must not recompute scientific values, perform hidden analysis, fetch
live provider data, or present generated narrative as findings. Model-generated
claims must not be presented as evidence.

Dashboard content must not upgrade the epistemic status of underlying records.
Appearing in a dashboard never makes a record live, verified, approved,
certified, operational, taskable, command-ready, or current-state
authoritative.

## Aggregation and rollup rule

Dashboards must not synthesize composite claims that exist in no persisted
record.

Dashboards must not introduce aggregate scores, cross-domain rollup statuses,
overall system health, overall evidence health, operational readiness scores,
or green/yellow/red operational readiness indicators.

Counts must not be presented as conclusions. No panel may turn multiple
records into a new conclusion unless that conclusion exists as a reviewed
persisted value.

Every panel value must be a deterministic projection of persisted fields or
reviewed projections. Any future composite indicator requires its own reviewed
definition. Composite indicators must not be introduced casually as dashboard
convenience features.

## Withheld evidence fail-closed rule

Unavailable, unauthenticated, cross-owner, missing, or integrity-failed inputs
must appear as unavailable or withheld status.

Dashboards must not fabricate, infer, summarize around, hide, smooth over, or
visually downplay missing evidence. Unavailable panels or cards must not be
replaced by generated prose.

Withheld state is not a failure diagnosis unless the underlying record
explicitly says so. Raw error internals must not leak.

## Meaning of status

In dashboard panel names, `status` means persisted read-outcome state.

Examples may include `verified`, `integrity_failed`, `receipt_status`,
withheld, unavailable, missing, or freshness/source labels when those values
are already persisted or reviewed.

`status` does not mean operational health. It does not mean system readiness.
It does not mean approval state. It does not mean action priority.

## Safe v1 dashboard panels and cards

Future v1 dashboards may use these semantic panel/card types only after a
separate implementation review:

- `mission-visual-manifest-summary`;
- `optimization-benchmark-manifest-summary`;
- `artifact-inventory-summary`;
- `evidence-integrity-status`;
- `freshness-and-source-labels`;
- `withheld-evidence-status`;
- `static-report-reference`;
- `provenance-graph-reference`;
- `map-orbit-view-reference`.

These are future semantic panel/card types only, not implemented dashboard UI.

## Safe data sources

Dashboards may use only safe references to:

- existing mission visual manifests;
- existing optimization-benchmark visual manifests;
- static report references;
- provenance/study graph references;
- map/orbit view references;
- study-chain records;
- integrity-summary records;
- safe source labels;
- freshness labels;
- test-only labels;
- checksums;
- authenticated persisted read paths.

Persisted records and authenticated read paths remain the evidence sources.

## Safe identifiers and handles

Dashboards may use only:

- existing safe IDs;
- route references;
- manifest IDs;
- report IDs;
- graph node handles;
- map/orbit view semantic handles;
- source record handles;
- checksum handles;
- `sha256:<checksum>` handles.

Dashboards must not expose raw paths or raw internal payloads.

## Freshness wording

Dashboards may show source labels, freshness labels, test-only labels, and
persisted read timestamps.

Dashboards must not imply live monitoring, current orbital truth, real-time
state, or freshness beyond persisted records.

Dashboards must not present stale records as current. They must not use
green/yellow/red operational readiness labels unless separately reviewed.

## Live and provider wording

Dashboards must not introduce:

- live monitoring;
- live tracking;
- live polling;
- live refresh;
- provider fetches;
- live CelesTrak;
- Space-Track;
- NASA Earthdata;
- external provider state;
- external orbital/provider services;
- cached provider payloads;
- provider credentials;
- real-time ephemeris authority;
- operational provider state;
- live satellite state.

Named providers and generic external provider services are both excluded unless
a future reviewed source boundary explicitly approves them.

## Dashboard-specific exclusions

Dashboards must not include:

- generated action items;
- task queues;
- alerting rules;
- escalation states;
- operational recommendations;
- autonomous decisions;
- live health monitoring;
- live provider refresh indicators;
- live polling intervals;
- interactive command controls;
- approve/reject controls;
- command/task surfaces;
- operational recommendation engines.

## Receipt and signing wording

`receipt_status = "signed"` may appear only as a persisted record-integrity
provenance signal.

It is not approval, authorization, certification, operational clearance,
command readiness, or signed-receipt authority.

Dashboards must never expose:

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

Quantum evidence should not appear directly in dashboards.

Indirect references through manifests or reports remain diagnostic only.

Dashboards must not imply quantum authority, a general quantum advantage claim,
or provider/live-data behavior. They must not expose raw samples, circuits, QUBO
internals, solver internals, or unredacted quantum evidence.

## Solver-comparison wording

Dashboards may show recorded comparison labels only.

Dashboards must not re-derive solver comparison conclusions, reinterpret solver
comparison conclusions, summarize beyond stored labels, expose thresholds as
client-selectable, expose solver internals, expose QUBO internals, or present
outputs as operational recommendations.

Dashboards must preserve classical-baseline-authoritative framing.

## General exclusions

Dashboards must not expose:

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
- raw trajectory arrays;
- raw coordinate streams;
- raw `result_json`;
- raw `request_json`;
- raw `link_json`;
- raw planning snapshots;
- raw provenance snapshots;
- solver internals;
- QUBO internals;
- provider state;
- cached provider payloads;
- operational commands;
- precise pointing commands;
- operational recommendations.

These exclusions apply to dashboard content, panel titles, cards, badges,
labels, legends, tooltips, empty states, withheld states, unavailable states,
errors, examples, tests, and documentation examples.

## Relationship to visual manifests

Dashboards may summarize mission and optimization-benchmark visual manifest
projections.

Visual manifests remain discovery/index inputs. They are not proof. They are
not evidence by themselves. They are not live status sources.

Additional visual manifest domains remain deferred.

## Relationship to static reports

Dashboards may reference static reports as summary/index artifacts.

Reports do not add authority to dashboards. Dashboards do not make reports
operational.

Dashboards must not imply report generation exists unless separately
implemented.

## Relationship to provenance/study graphs

Dashboards may reference graph nodes or edges as bounded lineage context.

Dashboards must not claim complete lineage. Dashboards must not claim causal
proof.

Graph references must follow graph edge-projection and owner-scoping semantics.
Dashboards must not imply graph rendering exists.

## Relationship to map/orbit views

Dashboards may reference future map/orbit view summaries or withheld states.

Dashboards must not embed rendering semantics. They must not expose coordinate
payloads. They must not imply live tracking, basemap fetching, provider data,
or that map/orbit rendering exists.

## Out of scope

This specification does not add:

- dashboard UI;
- frontend;
- charts;
- widgets;
- D3;
- rendering;
- report generation;
- export;
- PDF;
- graph rendering;
- map/orbit rendering;
- dashboard API routes;
- dashboard persistence tables;
- migrations;
- provider/live-data behavior;
- live tracking;
- command/task surfaces;
- operational recommendation engines;
- new visual manifest domains;
- generic dispatcher;
- Quantum Studio;
- quantum implementation work;
- operational command center behavior;
- autonomous decision-making;
- operational readiness scoring;
- green/yellow/red readiness indicators;
- alerting/escalation systems;
- approve/reject controls.

## Future gates

Future dashboard implementation requires separate reviewed planning for:

- dashboard API or CLI, if any;
- selected scope handles;
- panel definitions;
- aggregation/rollup definitions;
- owner-scoping and cross-domain isolation;
- deterministic-output tests;
- redaction tests;
- status-label semantics;
- live/provider exclusion tests;
- PostgreSQL validation if persisted records are read;
- UI, frontend, charts, or widgets only after separate approval;
- no action, task, or recommendation panels unless separately approved;
- Phase 5 visual-planning closure audit after this specification merges.
