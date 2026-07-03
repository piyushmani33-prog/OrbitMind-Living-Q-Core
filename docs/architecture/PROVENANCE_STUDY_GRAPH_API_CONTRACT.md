# Provenance Study Graph API Contract - OrbitMind Living Q-Core

## Purpose and status

This is a docs-only Phase 5 Provenance Study Graph API Contract.

This contract narrows the broad
[provenance/study graph semantics](PROVENANCE_STUDY_GRAPH_SEMANTICS.md)
specification to the first future graph API surface before any implementation
work begins.

Implementation remains blocked until this contract is reviewed and merged.

## Contract-not-implementation statement

This contract is a docs-only planning artifact. It authorizes no API, schema,
router, persistence, rendering, frontend, dashboard, provider/live-data,
command/task, recommendation, Quantum Studio, or runtime implementation work.

This contract does not add graph API routes, graph rendering, D3, frontend,
dashboard UI, map/orbit rendering, provider/live-data behavior, PDF/export,
graph persistence tables, migrations, a generic dispatcher, Quantum Studio, or
quantum implementation work.

## Future route shape

The first future route idea is:

```text
GET /api/v1/provenance-graphs/observation-study/geometry-planning-chain?geometry_run_id={geometry_run_id}&provenance_link_id={provenance_link_id}
```

This route is not implemented by this contract.

Future implementation rules:

- domain-specific route only;
- JSON-only;
- generated on demand;
- no graph persistence;
- no generic dispatcher;
- no graph rendering;
- no frontend;
- no D3;
- no dashboard;
- no provider/live-data behavior.

## Composite query parameter contract

The future route requires exactly these query parameters:

- `geometry_run_id`;
- `provenance_link_id`.

Future implementation should reuse observation-study router conventions:

- allowlist query rejection;
- clean identifier checks;
- trusted owner dependency.

The future route must reject all unknown query parameters, including:

- `owner_id`;
- `principal`;
- `user_id`;
- raw payload selectors;
- rendering options;
- provider/live switches.

The route must use the trusted owner dependency only. It must never use a
client-supplied owner value.

This future route intentionally differs from visual-manifest and static-report
routes that blanket-reject all query parameters, because this graph scope is a
composite read over two required identifiers.

## Observation-study-only first scope

The first future graph scope is:

```text
observation-study geometry-planning-chain
```

This scope is selected first because:

- it is already owner-scoped;
- an authenticated read model already exists;
- recorded relationships and checksums can support edge derivation;
- it avoids receipt, quantum, solver-comparison, and non-owner-scoped
  cross-domain complexity;
- it avoids treating static reports or visual manifests as evidence.

Deferred graph scopes:

- cross-domain graphs;
- mission-only graphs;
- optimization-only graphs;
- static-report-family graphs;
- memory/evidence graph expansion.

## Scope handle

The future graph scope handle is:

```text
observation-study-chain:{geometry_run_id}:{provenance_link_id}
```

This contract treats
`observation-study-chain:{geometry_run_id}:{provenance_link_id}` as a candidate
reviewed stable scope handle for future observation-study visual manifest
planning. It does not implement or authorize that manifest domain. A future
observation-study manifest slice may adopt or revise this handle only through
separate reviewed planning.

## Node identity

Future node IDs use this deterministic format:

```text
study-graph-node:{node_type}:{record_id}
```

Node IDs are:

- deterministic;
- stable for the same persisted record;
- not user supplied;
- not globally meaningful outside this graph contract;
- not evidence by themselves;
- not authority, approval, certification, taskability, or command readiness;
- not a claim of complete lineage.

## Node schema concept

Future graph nodes should be JSON objects containing only safe graph projection
metadata, such as:

- deterministic node ID;
- allowed node type;
- safe source record handle;
- safe checksum handle, when already exposed by the authenticated read model;
- owner-consistent scope handle;
- canonical status labels;
- limitations;
- disclaimers.

Nodes must not expose raw persisted payloads, raw column values, paths,
sidecars, or hidden owner information.

## Edge schema concept

Future graph edges should be JSON objects containing only safe relationship
projection metadata, such as:

- deterministic edge ID, if edge IDs are used;
- allowed edge type;
- deterministic source node ID or scope handle;
- deterministic target node ID or scope handle;
- proof/source label;
- limitations;
- disclaimers.

Edges must be projections of recorded relationships only. Edges must not be
inferred from apparent semantic relatedness, generated prose, model reasoning,
or report/manifest convenience.

## Allowed node types

The first future surface may use only these node types:

- `geometry-run`;
- `eligibility-provenance`;
- `eligibility-set`;
- `planning-request`;
- `planning-run`;
- `observation-plan`, only when present;
- `provenance-link`;
- `integrity-summary`, success-only.

The first future surface must not use:

- mission nodes;
- optimization benchmark nodes;
- static report nodes;
- visual manifest nodes;
- memory graph nodes;
- quantum nodes;
- provider nodes;
- command/task nodes;
- inferred lineage nodes.

## Allowed edge types

The first future surface may use only these recorded relationship projections:

1. `eligibility-provenance derived-from geometry-run`
2. `eligibility-set uses eligibility-provenance`
3. `provenance-link links eligibility-provenance`
4. `provenance-link links eligibility-set`
5. `provenance-link links planning-request`
6. `provenance-link links planning-run`
7. `planning-run produced observation-plan`, only when present
8. `integrity-summary checks observation-study-chain scope handle`

The `checks` edge target is exactly the
`observation-study-chain:{geometry_run_id}:{provenance_link_id}` scope handle.

## Edge proof/source requirements

Every edge must include a proof/source label naming the recorded relationship
kind it projects.

Allowed proof/source label examples:

- `recorded-provenance:derived-from-geometry`;
- `recorded-fk:eligibility-set-to-provenance`;
- `recorded-link:provenance-link-to-planning-run`;
- `recorded-summary:chain-integrity`.

Proof/source labels must name relationship kinds only. They must never expose:

- raw column values;
- SQL;
- snapshots;
- `request_json`;
- `result_json`;
- `link_json`;
- checksums beyond allowed safe checksum handles;
- internal paths;
- stack traces.

## Owner isolation

The first graph surface is owner-scoped.

Future implementation rules:

- use trusted owner dependency only;
- never accept owner, principal, or user query parameters;
- cross-owner nodes must not appear;
- cross-owner edges must not appear;
- cross-owner access returns `404`;
- `404` responses must not leak IDs, checksums, node counts, edge counts, or
  scope handles;
- cross-domain graphs remain deferred until owner semantics are defined for
  every node domain.

## Owner-isolation test matrix

Future implementation tests must include:

- owner A can read owner A chain;
- owner B cannot read owner A chain;
- cross-owner request returns `404`;
- error body leaks no IDs, checksums, node counts, edge counts, or scope
  handles;
- `owner_id` query parameter is rejected;
- `principal` query parameter is rejected;
- `user_id` query parameter is rejected;
- two-owner PostgreSQL fixture is required;
- no client-supplied owner value is trusted;
- graph nodes and edges are all owner-consistent.

## Fail-closed integrity behavior

Future implementation must fail closed:

- hidden or missing owner-scoped records return `404`;
- tamper returns sanitized `422`;
- mismatch returns sanitized `422`;
- malformed persisted relationship returns sanitized `422`;
- missing authenticated records return sanitized `422` or `404` according to
  existing observation-study behavior;
- no partial graph body is returned on error;
- no failed `integrity-summary` node is synthesized;
- `integrity-summary` appears only for a successful graph response;
- graph existence implies chain consistency.

## Error semantics

Error responses must use the existing typed API error style.

Error responses must be sanitized and must not expose hidden owner data, raw
persisted payloads, stack traces, SQL, internal paths, or graph-shaped partial
content.

## Graph-existence-implies-consistency rule

A served graph means the underlying owner-scoped study-chain read and integrity
checks succeeded.

It does not mean the graph is proof of scientific correctness, complete
lineage, operational readiness, approval, certification, command readiness, or
taskability.

## No graph-shape-in-errors rule

Error responses must not contain graph-shaped fields, including:

- `graph_id`;
- `scope_handle`;
- `nodes`;
- `edges`;
- `node_count`;
- `edge_count`;
- `integrity_summary`;
- status labels derived from hidden records;
- checksums or IDs from hidden records.

## Receipt/signing exclusions

Receipt and signing state is not applicable to observation-study graph v1.

The first future surface must not include `receipt_status`.

The graph must preserve no signed receipt authority.

## Quantum exclusions

The first future surface must not include:

- quantum nodes;
- quantum diagnostics;
- QUBO;
- solver internals;
- quantum evidence;
- provider state.

The graph must preserve no quantum authority and no general quantum advantage.

## Non-leakage rules

These rules apply to graph content, node labels, edge labels, proof labels,
errors, examples, tests, and documentation examples.

Future graph surfaces must never expose:

- raw paths;
- artifact root;
- artifacts-root value;
- sidecars;
- raw sidecar JSON;
- raw `result_json`;
- raw `request_json`;
- raw `link_json`;
- raw samples;
- raw intervals;
- raw TLEs;
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
- operational commands;
- operational recommendations;
- hidden owner IDs;
- cross-owner checksums;
- raw column values in proof labels.

## Deterministic output rules

Future output must be:

- JSON-only;
- generated on demand;
- deterministic for the same persisted records;
- stable in node ordering;
- stable in edge ordering;
- deterministic in scope handle;
- deterministic in node IDs;
- deterministic in edge IDs, if edge IDs are used.

A timezone-aware UTC `read_at` should be included for read-product consistency.
Byte-level determinism must be tested after normalizing only `read_at`.

Node ordering should follow chain order:

1. `geometry-run`
2. `eligibility-provenance`
3. `eligibility-set`
4. `planning-request`
5. `planning-run`
6. `observation-plan`, only when present
7. `provenance-link`
8. `integrity-summary`

Edges should be ordered lexicographically by:

```text
(edge_type, source, target)
```

## PostgreSQL validation gates

Future implementation must include:

- migrated PostgreSQL validation;
- no `create_all()`;
- two-owner fixture;
- owner isolation tests;
- `404` hidden-owner behavior;
- sanitized `422` tamper and mismatch behavior;
- deterministic-output tests;
- non-leakage tests;
- edge proof/source tests;
- no recompute tests;
- OpenAPI route inventory tests;
- router import and transaction guard tests.

## Future implementation gates

Future implementation requires separate reviewed planning for:

- graph route registration;
- graph response schemas;
- selected scope handle behavior;
- owner-scoping and cross-domain isolation;
- node materialization strategy, if any;
- edge derivation rules;
- status-label semantics;
- deterministic-output tests;
- redaction tests;
- PostgreSQL validation.

Rendering, D3, frontend, dashboard, map/orbit rendering, provider/live-data
behavior, command/task surfaces, and recommendations require separate approval.

## Explicit exclusions

This contract does not implement or authorize:

- graph API implementation;
- graph rendering;
- D3;
- frontend;
- dashboard UI;
- map/orbit rendering;
- Leaflet;
- CesiumJS;
- PDF/export;
- provider/live-data behavior;
- live tracking;
- command/task surfaces;
- operational recommendation engines;
- approval workflow;
- certification;
- signed receipt authority;
- graph persistence tables;
- migrations;
- generic dispatcher;
- Quantum Studio;
- quantum implementation work;
- general quantum advantage claims.

## Relationship to deferred observation-study manifest scope handle

The scope handle in this contract is a candidate reviewed stable handle for a
future observation-study visual manifest domain.

This contract does not implement that manifest domain. It does not resolve the
observation-study visual manifest response shape. A future observation-study
manifest slice may adopt or revise this handle only through separate reviewed
planning.

## Relationship to existing memory/evidence graph surfaces

Existing memory graph and optimization evidence graph routes are related but
distinct.

This contract does not reuse memory graph semantics as provenance/study lineage
semantics.

Existing routes are not modified by this contract.

## Scientific-honesty boundaries

Future graph surfaces must preserve:

- no live tracking;
- no real-time position authority;
- no operational access;
- no taskability;
- no command readiness;
- no approval;
- no certification;
- no signed receipt authority;
- no operational recommendation;
- no autonomous decision-making;
- no causal proof;
- no complete lineage;
- no quantum authority;
- no general quantum advantage.
