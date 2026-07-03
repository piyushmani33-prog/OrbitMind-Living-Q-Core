# Static Report Specification - OrbitMind Living Q-Core

## Purpose and status

This is a docs-only Phase 5 static report specification.

It does not implement report generation. It does not implement PDF generation,
export, rendering, charts, maps, graphs, dashboards, frontend work,
provider/live-data behavior, or Quantum Studio.

This specification gates a future reviewed report-generator slice. A future
generator requires separate planning and review before any API, CLI,
persistence, rendering, export, or runtime behavior is implemented.

## Definition

A future static report is a read-only, non-authoritative deterministic
projection over already persisted records and safe visual manifest projections.
It is a summary and index artifact only.

A static report is not proof by itself. It is not approval, certification,
taskability, command readiness, an operational recommendation,
signed-receipt authority, a quantum authority signal, or a general quantum
advantage claim.

Reports may reference mission and optimization-benchmark visual manifest IDs or
items, but persisted records and authenticated read paths remain the evidence
sources. Visual manifests are discovery/index layers, not proof. Reports are
summaries over summaries and evidence sources; they are not new evidence.

## Deterministic projection rule

Report content must be a deterministic projection of persisted fields and
reviewed manifest projections.

A report must not recompute scientific values, perform hidden analysis, or
present generated narrative as findings. Model-generated claims must not be
presented as evidence.

Report content must not upgrade the epistemic status of underlying records.
Appearing in a report never makes a record verified, approved, certified,
operational, taskable, or command-ready.

## Withheld evidence fail-closed rule

If an underlying authenticated read fails, is missing, is unauthenticated, is
withheld, or is integrity-failed, the report must reflect unavailable or
withheld status.

The report must never fabricate, substitute, infer, summarize around, or smooth
over missing evidence. Unavailable evidence must not be replaced by generated
prose.

Report consumers must be able to tell that evidence was unavailable or
withheld. Error or withheld sections must remain sanitized and must not leak raw
internal details.

## Safe v1 report sections

Future v1 static reports may include these sections only after a separate
implementation review.

### Report identity and status

Allowed content:

- schema or report status;
- report id;
- generated/read timestamp;
- source domains;
- scope references.

### Inputs and provenance

Allowed content:

- safe source record handles;
- visual manifest references;
- checksums;
- freshness and test-only labels.

### Mission summary

Allowed content:

- mission ID;
- epistemic status;
- source and freshness labels;
- artifact handles and checksum handles;
- limitations.

### Optimization benchmark summary

Allowed content:

- benchmark ID;
- `verified`;
- `integrity_failed`;
- `receipt_status`;
- `comparison_conclusion`;
- artifact handles and checksum handles;
- limitations.

### Evidence and limitations

Allowed content:

- canonical disclaimers;
- scientific-honesty boundaries;
- missing or withheld evidence behavior.

### Appendix-style safe references

Allowed content:

- API routes;
- manifest IDs;
- source handles.

Appendices must not expose raw internals.

## Report identity and timestamps

`report_id`, or any future report identity field, is non-authoritative. It is
not a certificate id, attestation id, approval id, receipt id, signature id, or
operational clearance.

All report timestamps must be timezone-aware UTC.

## Receipt and signing wording

`receipt_status = "signed"` may be described only as a persisted
record-integrity provenance signal.

It is not approval, authorization, certification, operational clearance,
command readiness, or signed-receipt authority for the report consumer.

Reports must never expose:

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

Quantum-related report content is diagnostic only and bounded to persisted,
authenticated labels.

Reports must not imply quantum authority, a general quantum advantage claim,
live provider access, or provider state.

Reports must not expose raw samples, circuits, QUBO internals, unredacted
quantum evidence, or quantum execution internals.

Absence of quantum artifacts or samples can be normal. Absence must not be
treated as an automatic integrity failure.

## Solver-comparison wording

Reports may show recorded comparison labels only.

Reports must not re-derive solver comparison conclusions, reinterpret solver
comparison conclusions, summarize beyond stored labels, expose thresholds as
client-selectable, expose solver internals, expose QUBO internals, or present
outputs as operational recommendations.

Reports must preserve classical-baseline-authoritative framing.

## Relationship to visual manifests

Reports may reference safe mission visual manifest projections and safe
optimization-benchmark visual manifest projections.

Visual manifests remain discovery/index layers. They are not proof, and reports
do not add authority to them.

Persisted records and authenticated read paths remain the evidence sources.
Additional visual manifest domains remain deferred and require separate
planning and review.

Future graph references are governed by the
[provenance/study graph semantics](PROVENANCE_STUDY_GRAPH_SEMANTICS.md)
specification.

Future map/orbit view references are governed by the
[map/orbit view specification](MAP_ORBIT_VIEW_SPECIFICATION.md).

Future dashboard references are governed by the
[dashboard view specification](DASHBOARD_VIEW_SPECIFICATION.md).

## Excluded fields and internals

Static reports must not expose:

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

These exclusions apply to report content, withheld or unavailable sections,
errors, examples, tests, and documentation examples.

## Out of scope

This specification does not add:

- report generation;
- PDF generation;
- export;
- rendering;
- charts;
- graphs;
- maps;
- D3;
- Leaflet;
- CesiumJS;
- dashboards or frontend;
- provider/live-data behavior;
- Quantum Studio;
- generated operational recommendations;
- new API routes;
- new visual manifest domains;
- generic visual manifest dispatcher;
- migrations.

## Future gates

Future report generation requires separate reviewed planning for:

- generator API or CLI, if any;
- data source selection;
- artifact persistence strategy, if any;
- redaction tests;
- deterministic-output tests;
- PostgreSQL validation if persisted records are read;
- no PDF, export, or rendering until separately approved.
- provenance/study graph references only under
  [PROVENANCE_STUDY_GRAPH_SEMANTICS.md](PROVENANCE_STUDY_GRAPH_SEMANTICS.md).
