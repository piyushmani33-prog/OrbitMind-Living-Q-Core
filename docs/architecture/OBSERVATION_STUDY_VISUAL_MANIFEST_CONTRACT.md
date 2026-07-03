# Observation-Study Visual Manifest Contract - OrbitMind Living Q-Core

## Purpose and status

This is a docs-only contract for a future Observation-study Visual Manifest.

It implements no API, schema, router, test, migration, persistence table,
frontend, rendering, dashboard, provider/live-data behavior, command/task
surface, recommendation engine, Quantum Studio work, or runtime behavior.

Implementation remains blocked until this contract is reviewed and merged, and
then followed by a separate implementation-planning pass.

The future observation-study visual manifest is a read-only deterministic
discovery/index envelope over an authenticated observation-study geometry and
planning chain. It is not a new evidence source, not proof by itself, not
approval, not certification, not signed receipt authority, not operational
guidance, not taskability, not command readiness, not quantum authority, and
not a claim of general quantum advantage.

## Relationship to Existing Chain Read Products and Distinct Value

Observation-study chain produces no visual artifacts.

This future manifest indexes authenticated chain records, not visual artifacts.
It is a record-index manifest, not an artifact-index manifest.

`artifact_handle` and `media_type` do not apply to this domain and must be
absent unless a later reviewed contract introduces real artifacts.

The manifest adds shape uniformity, not new data. It is not a new evidence
source.

The full chain read already contains the complete traceability data. The
integrity summary already provides pass/fail attestation. The provenance graph
already provides lineage nodes and edges.

The future observation-study visual manifest provides only a uniform
`visual-manifest-v1` discovery/index envelope for future composition across
manifest families.

If no future composition or summary consumer needs this envelope,
implementation should be deferred rather than built as a fourth duplicate-data
read product.

## No Visual Artifacts in This Domain - Record-Index Semantics

Observation-study visual manifest v1 has no PNGs, no image bytes, no
`media_type`, no `artifact_handle`, no visual artifact payloads, no render
instructions, no frontend layer definitions, no graph layout, and no graph
rendering state.

Items may index only deterministic authenticated chain records, safe labels,
checksum handles, source-domain tags, counts, status labels, limitations,
disclaimers, and reviewed identifiers.

The manifest must not fabricate visual artifacts or introduce artifact-shaped
fields for record-only chain data.

## Future route

The future route documented by this contract is:

```http
GET /api/v1/visual-manifests/observation-study/{geometry_run_id}/{provenance_link_id}
```

This route is future-only. This contract does not implement it.

Route rules for a future implementation:

- required identifiers are path segments;
- reject all query parameters;
- reject `owner_id`, `principal`, and `user_id` spoof parameters;
- no generic dispatcher;
- no mutation route;
- no query-parameter identifier style for this visual-manifest family route;
- do not use `{scope_handle}` as a direct path segment;
- derive the scope ID server-side from the two path identifiers.

Graph and study APIs address the same composite chain with query parameters,
while this visual-manifest route uses path segments to remain consistent with
the visual-manifest family and preserve blanket query rejection.

## Scope ID

This contract formally adopts this reviewed stable scope handle as the
`scope_id` for the future observation-study visual manifest:

```text
observation-study-chain:{geometry_run_id}:{provenance_link_id}
```

This handle was nominated by the
[Provenance Study Graph API Contract](PROVENANCE_STUDY_GRAPH_API_CONTRACT.md)
and is adopted only for this contract.

This contract uses `scope_id` only. It does not define a duplicate
`scope_handle` field because `scope_id` is the reviewed stable scope handle for
this domain.

## DTO pins

Future response constants are:

```text
schema_version = "visual-manifest-v1"
source_domain = "observation-study"
scope_id = "observation-study-chain:{geometry_run_id}:{provenance_link_id}"
manifest_id = "visual-manifest:observation-study:{scope_id}:v1"
```

Do not add a new top-level `manifest_type` field for this domain unless a later
reviewed contract changes the visual-manifest family shape. Existing mission
and optimization-benchmark visual manifest responses use `source_domain` as
the family discriminator.

## Future response concept

A future response should use the visual-manifest family envelope without
pretending record-index items are visual artifacts.

Expected top-level concepts:

- `schema_version`;
- `manifest_id`;
- timezone-aware UTC `read_at`;
- `source_domain`;
- `scope_id`;
- owner-scope label for the trusted owner dependency;
- record-index `items`;
- limitations;
- disclaimer.

Expected item concepts:

- deterministic item ID;
- record kind;
- safe record handle;
- checksum handle where already available from the authenticated chain;
- source-domain tag;
- safe counts;
- status labels;
- limitations;
- disclaimer.

Items must not contain `artifact_handle`, `media_type`, image locators, graph
node IDs, graph edge IDs, graph proof labels, graph layout fields, coordinate
payloads, raw intervals, raw samples, or raw persisted payloads.

## Owner scope and failure semantics

Future implementation must inherit observation-study owner scoping from the
Provenance Study Graph API and observation-study read model.

The only authoritative read path for the future implementation is:

```python
get_geometry_planning_study_chain(
    session=session,
    owner_id=trusted_owner_id,
    geometry_run_id=geometry_run_id,
    provenance_link_id=provenance_link_id,
)
```

Rules:

- use trusted owner dependency only;
- never trust client-supplied owner, principal, or user values;
- unauthorized chain returns hidden `404`;
- missing chain returns hidden `404`;
- invalid identifiers return sanitized `422`;
- integrity mismatch, tamper, or malformed authenticated chain returns
  sanitized `422`;
- emit no partial manifest body on integrity failure.

Error bodies must not leak hidden IDs, owner IDs, checksums, scope IDs, SQL,
stack traces, paths, graph concepts, or chain internals.

## Authoritative input stance

Future implementation may use only:

- authenticated observation-study chain read path;
- reviewed chain identifiers;
- deterministic labels, counts, status labels, and checksum handles from that
  authenticated chain.

It must not use as evidence:

- provenance graph responses;
- static reports;
- other visual manifests;
- raw sidecars;
- raw JSON;
- artifact paths;
- provider state;
- dashboard summaries;
- map/orbit contexts.

Visual manifests remain discovery/index projections. They are not proof and
not evidence by themselves.

## Graph boundary

The observation-study visual manifest is not a provenance graph.

It must not expose:

- graph nodes;
- graph edges;
- edge proof labels;
- graph layout concepts;
- graph rendering state;
- graph traversal output.

The future manifest may reference safe record handles and checksum handles, but
it must not become a relabeled provenance graph response.

## Forbidden inputs and outputs

The future observation-study visual manifest must exclude:

- raw coordinates;
- intervals;
- samples;
- TLEs;
- ephemeris internals;
- sidecars;
- artifact paths;
- PNG or image bytes;
- raw `request_json`;
- raw `result_json`;
- raw `link_json`;
- provider/live-data payloads;
- map/orbit coordinate payloads;
- receipt/signing internals;
- quantum evidence;
- QUBO or solver internals;
- command/task/recommendation fields;
- operational guidance;
- approval/certification fields;
- dashboard rollups;
- frontend/rendering instructions.

These exclusions apply to manifest content, item labels, limitations,
disclaimers, errors, tests, and documentation examples.

## Deterministic output

Future implementation must provide:

- timezone-aware UTC `read_at`;
- stable item ordering;
- byte-identical responses after normalizing only `read_at`;
- no recomputation;
- no provider calls;
- no graph rendering;
- no synthesized readiness, authority, or composite claims.

The manifest must not re-run geometry, eligibility, or planning. It must not
infer additional conclusions from counts, labels, or graph shape.

## PostgreSQL and migration gates

No migration is expected for future v1 implementation.

No persistence or table changes are expected. Any proposed persistence table
requires separate reviewed planning.

Future implementation must include migrated PostgreSQL validation before merge:

- no `create_all()`;
- two-owner fixture;
- hidden `404` owner-isolation test;
- sanitized `422` tests for mismatch and tamper;
- non-leakage tests;
- deterministic-output tests;
- Alembic head remains `m8b9c0d1e2f3` unless a separately reviewed migration
  changes it.

## Future implementation test gates

Before any future implementation merge, tests must verify:

- exact route exists once;
- no generic dispatcher;
- no mutation route;
- query parameters rejected;
- valid owned chain succeeds;
- cross-owner chain returns hidden `404`;
- missing chain returns `404`;
- invalid `geometry_run_id` or `provenance_link_id` returns `422`;
- integrity mismatch or tamper returns `422`;
- no partial manifest on integrity failure;
- no graph nodes, edges, proof labels, or layout concepts;
- no raw coordinates, intervals, samples, TLEs, sidecars, artifact paths, or
  image bytes;
- no provider/live-data;
- no rendering/frontend/dashboard imports;
- no command/task/recommendation fields;
- no receipt/signing fields;
- no quantum fields;
- deterministic response after normalizing `read_at`;
- PostgreSQL migrated-schema validation;
- no `create_all()`;
- Alembic head check.

Shape-distinction tests must also verify:

- manifest response shape differs from the full `ObservationStudyChainResponse`;
- manifest response shape differs from the Observation-study Provenance Graph
  response;
- manifest is not a relabeled chain response;
- manifest is not a relabeled graph response.

## Explicit exclusions

This contract does not implement or authorize:

- observation-study visual manifest API implementation;
- schema implementation;
- router implementation;
- tests;
- migrations;
- persistence tables;
- graph rendering;
- map/orbit rendering;
- coordinate payloads;
- frontend;
- dashboard UI;
- provider/live-data behavior;
- live tracking;
- command/task/recommendation surfaces;
- receipt/signing authority;
- quantum authority;
- generic visual manifest dispatcher;
- cross-domain manifest aggregation;
- dashboard/product-summary read surface.

## Final gate

The future observation-study visual manifest should proceed only if a future
composition or summary consumer needs a uniform `visual-manifest-v1`
record-index envelope. Otherwise, it should remain deferred because the chain
read, integrity summary, and provenance graph already expose the underlying
traceability surfaces.
