# Provenance / Study Graph Semantics - OrbitMind Living Q-Core

## Purpose and status

This is a docs-only Phase 5 graph semantics specification.

It does not implement graph rendering. It does not implement D3, frontend,
dashboard, export, PDF generation, report generation, graph API routes, graph
persistence tables, provider/live-data behavior, or Quantum Studio.

This specification gates future graph API, rendering, D3, dashboard, or other UI
work. Any future graph implementation requires separate planning and review.

## Definition

A future provenance/study graph is a read-only, non-authoritative visual
semantics layer only. It is a deterministic projection over existing persisted
records and authenticated read paths, and it may reference visual manifests and
static reports.

A provenance/study graph is not proof by itself. It is not evidence by itself.
It is not causal proof unless explicitly supported by persisted relationships.
It is not complete lineage unless explicitly bounded and proven.

A provenance/study graph is not approval, certification, signed receipt
authority, taskability, command readiness, an operational recommendation,
quantum authority, or a general quantum advantage claim.

## Edge projection rule

Every graph edge must be a projection of a persisted or recorded relationship.

Allowed edge sources include:

- foreign keys;
- checksum-anchored links;
- persisted provenance links;
- recorded comparisons;
- documented authenticated-read relationships;
- explicitly recorded evidence links.

The graph must not create inferred edges, heuristic edges, model-generated
edges, or plausible-looking edges only because records seem related.

Appearing in a graph edge never upgrades evidence status.

`supports` must mean a recorded evidence link only. `supports` is not proof and
must not be inferred from semantic similarity or model reasoning.

## Owner-scoping semantics

Observation-study records are owner-scoped.

Mission reads are currently not owner-scoped.

Optimization-benchmark reads are currently not owner-scoped.

Future cross-domain graph surfaces must resolve owner scoping per node domain.
They must never leak cross-owner nodes or edges. Unavailable cross-owner nodes
or edges should be absent or withheld, not exposed.

Owner isolation and `404` or withheld semantics must be designed before any
graph API is implemented. This specification does not change owner-scoping
behavior.

## Safe v1 node types

Future v1 graph surfaces may use these node types only after a separate
implementation review.

### Mission

- `mission`;
- `mission-artifact`;
- `mission-source-record`.

### Observation study

- `geometry-run`;
- `eligibility-provenance`;
- `eligibility-set`;
- `planning-request`;
- `planning-run`;
- `observation-plan`;
- `provenance-link`;
- `integrity-summary`.

`integrity-summary` nodes are success-only and fail-closed. Do not synthesize
failed integrity-summary nodes. Failure should appear as withheld, unavailable,
or read-outcome state, not as a fabricated graph node.

This specification does not resolve the deferred observation-study visual
manifest domain scope-handle question.

### Optimization benchmark

- `optimization-benchmark`;
- `optimization-problem`;
- `solver-run`;
- `benchmark-comparison`;
- `optimization-artifact`;
- `quantum-experiment-diagnostic`.

### Visual and report references

- `visual-manifest`;
- `static-report`.

### Memory and evidence

Memory/evidence graph nodes remain deferred.

Safe citation or source handles already exposed by existing memory APIs may be
referenced only as handles.

This specification does not open arbitrary memory graph traversal in the study
graph semantics.

## Safe v1 edge types

Future v1 graph surfaces may use these edge types only when each edge is backed
by a persisted or recorded relationship:

- `derived-from`;
- `uses`;
- `produced`;
- `summarizes`;
- `checks`;
- `links`;
- `supports`;
- `compared-against`;
- `references`.

`withheld` and `integrity-failed` should be status labels on nodes, edges, or
read results unless a future contract precisely defines their endpoints and
direction as graph edges.

## Direction and acyclicity

The graph is directed.

Study/provenance lineage edges should form a bounded directed acyclic graph for
one selected scope.

Cross-reference edges may point to related manifests, reports, or artifacts, but
they must not imply complete lineage.

The graph may be incomplete by design. It must not claim complete lineage unless
the boundary is explicit, bounded, and proven.

The graph must not claim causal proof unless causality is explicitly supported
by persisted relationships.

## Relationship to memory graph

The existing scientific-memory graph traversal is related but distinct.

Memory graph traversal may be broader, associative, cycle-safe, and bounded.
Provenance/study graph semantics are narrower and focus on persisted lineage,
authenticated read relationships, and reviewed cross-domain references.

Future study graph work should not inherit arbitrary memory traversal semantics.
Do not merge memory graph semantics into study lineage semantics without
separate review.

## Safe identifiers and handles

Future graph surfaces may use only:

- existing safe IDs;
- route references;
- manifest IDs;
- report IDs;
- source record handles;
- checksum handles;
- `sha256:<checksum>` handles.

Future graph surfaces must not expose raw paths, sidecar paths, artifacts-root
values, raw JSON snapshots, raw TLEs, raw samples, raw intervals, receipt
internals, quantum evidence internals, or solver internals.

## Receipt and signing wording

`receipt_status = "signed"` may appear only as persisted record-integrity
provenance state.

It is not approval, authorization, certification, operational clearance,
command readiness, or signed-receipt authority.

Graph surfaces must never expose:

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

Quantum graph nodes are diagnostic labels only.

Quantum content must be sourced from authenticated persisted records.

Graph surfaces must not imply quantum authority, a general quantum advantage
claim, provider state, or live provider access.

Graph surfaces must not expose raw samples, circuits, QUBO internals, or
unredacted quantum evidence.

Missing quantum artifacts or samples are not automatically integrity failures.

## Solver-comparison wording

Graph surfaces may show recorded comparison labels only.

They must not re-derive solver comparison conclusions, reinterpret solver
comparison conclusions, summarize beyond stored labels, expose thresholds as
client-selectable, expose solver internals, expose QUBO internals, or present
outputs as operational recommendations.

Graph surfaces must preserve classical-baseline-authoritative framing.

## Relationship to visual manifests and static reports

Visual manifests may be referenced as discovery/index nodes. Visual manifests
are not proof.

Static reports may be referenced as summary/index nodes. Static reports are not
evidence or authority.

Reports do not add authority to graphs. Graphs do not add authority to reports.

Persisted records and authenticated read paths remain the evidence sources.
Additional visual manifest domains remain deferred and require separate review.

Future map/orbit views that reference graph context are governed by the
[map/orbit view specification](MAP_ORBIT_VIEW_SPECIFICATION.md).

Future dashboards that reference graph context are governed by the
[dashboard view specification](DASHBOARD_VIEW_SPECIFICATION.md).

## Excluded fields and internals

Provenance/study graphs must not expose:

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
- circuits;
- QUBO internals;
- solver internals;
- provider state;
- operational recommendations;
- raw `result_json`;
- raw `request_json`;
- raw `link_json`;
- raw TLE lines;
- raw orbital samples;
- raw orbital intervals;
- raw planning snapshots;
- raw provenance snapshots.

These exclusions apply to graph content, node labels, edge labels, withheld or
unavailable states, errors, examples, tests, and documentation examples.

## Out of scope

This specification does not add:

- graph rendering;
- D3;
- frontend or dashboard;
- export;
- PDF;
- report generation;
- graph API routes;
- graph persistence tables;
- migrations;
- new visual manifest domains;
- generic dispatcher;
- provider/live-data behavior;
- Quantum Studio;
- quantum implementation work;
- operational recommendations;
- causal inference;
- complete lineage claims.

## Future gates

Future graph implementation requires separate reviewed planning for:

- graph API or CLI, if any;
- selected scope handles;
- owner-scoping and cross-domain isolation;
- node materialization strategy, if any;
- edge derivation rules;
- status-label semantics;
- deterministic-output tests;
- redaction tests;
- PostgreSQL validation if persisted records are read;
- map/orbit view references only under
  [MAP_ORBIT_VIEW_SPECIFICATION.md](MAP_ORBIT_VIEW_SPECIFICATION.md);
- dashboard references only under
  [DASHBOARD_VIEW_SPECIFICATION.md](DASHBOARD_VIEW_SPECIFICATION.md);
- rendering, D3, or frontend only after separate approval;
- the [Phase 5 visual-planning closure audit](PHASE_5_VISUAL_PLANNING_CLOSURE_AUDIT.md),
  which closes planning only and authorizes no implementation.
