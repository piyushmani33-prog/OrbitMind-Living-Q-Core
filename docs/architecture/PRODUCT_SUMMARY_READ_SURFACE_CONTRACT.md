# Product Summary Read Surface Contract - OrbitMind Living Q-Core

## Purpose and status

This began as a docs-only contract for a Product Summary / Read-Product
Catalog surface.

Status update: Product Summary Read Surface v1 is implemented only as Surface
A, the static JSON read-product capability catalog:

```http
GET /api/v1/product-summaries/read-products
```

This status update implements no Surface B per-scope composition, persisted
domain data reads, owner-scoped data reads, dashboard UI, frontend, rendering,
charts, graph drawing, map drawing, provider/live-data behavior, command/task
surface, recommendation engine, export/PDF behavior, Quantum Studio work, or
runtime behavior beyond the single static catalog route.

Additional implementation remains blocked until separately planned and
reviewed.

## Implemented route

The implemented Surface A route documented by this contract is:

```http
GET /api/v1/product-summaries/read-products
```

No other product-summary route is implemented by this status update.

Route rules:

- product-summary and read-product-catalog language, not dashboard UI language;
- path-based;
- global and static;
- no scope parameter;
- reject all query parameters;
- reject `owner_id`, `principal`, and `user_id` spoof parameters;
- reject render, provider, live, export, chart, map, and dashboard parameters;
- no generic dispatcher;
- no mutation route.

## Surface A - Static Read-Product Capability Catalog

This contract defines only Surface A.

Surface A is a static global capability catalog. It is JSON-only and reads no
persisted domain data.

Surface A is not owner-scoped. It does not call existing API routes. It does
not HTTP self-call. It does not call shared read or projection services for
domain data.

Surface A does not read mission records, optimization records,
observation-study chains, manifests, reports, graphs, or map/orbit context
payloads.

Surface A is a catalog of reviewed capability metadata.

## Surface B - Per-Scope Composition Surface Deferred

Per-scope data composition is deferred.

Surface B would require separate reviewed planning. It may require owner
scoping, hidden `404`, PostgreSQL data validation, and per-domain fail-closed
semantics.

Surface B is the kind of surface that could become a genuine envelope consumer
for an observation-study visual manifest. Surface A does not consume that
envelope.

## Distinct value

The catalog's value is:

- discoverability;
- roadmap transparency;
- deterministic declaration of implemented, deferred, and unsupported
  read-product surfaces;
- route, schema, and contract reference discovery.

The catalog is not:

- data summary;
- evidence;
- proof;
- readiness assessment;
- quality assessment;
- dashboard UI.

## Relationship to Observation-study Visual Manifest Final Gate

Observation-study visual manifest remains deferred.

This catalog may list observation-study visual manifest as deferred with a
contract reference. This catalog establishes a place for that manifest.

This catalog does not consume the observation-study visual manifest envelope.
It does not satisfy the observation-study visual manifest final gate. It does
not authorize observation-study visual manifest implementation.

Genuine envelope-consumer need requires a later Surface B per-scope composition
contract.

## DTO pins

Response constants are:

```text
schema_version = "product-summary-v1"
summary_type = "read-product-catalog"
scope_id = "orbitmind-read-products"
read_at = timezone-aware UTC
```

Use `summary_type` as the discriminator. Do not add `surface_type`.

Top-level sections are:

- `implemented_read_products`;
- `deferred_read_products`;
- `unsupported_read_products`;
- `limitations`;
- `disclaimer`.

## Status labels

Per-entry status labels are factual only:

- `implemented`;
- `deferred`;
- `unsupported`.

The catalog must not include:

- `overall_status`;
- `validation_status` as an overall verdict;
- health score;
- readiness score;
- quality score;
- rank;
- composite authority score;
- recommendation;
- task;
- command;
- approval;
- certification.

If a future validation fact is included, it must be per-entry factual metadata,
such as `has_postgres_integration_test = true`. It must never be a score,
verdict, or badge.

## Counts

Counts are optional and should be avoided unless they are clearly redundant.

If counts are included in a later reviewed implementation:

- counts may only be self-evident tallies of enumerated catalog entries;
- counts must never be data-derived aggregates;
- counts must never be presented as conclusions;
- counts must never be the primary signal.

## No Scores, Rollups, or Synthesized Authority

This contract inherits the Dashboard View Specification aggregation rule.

The catalog must not introduce aggregate health or readiness scores,
cross-domain rollup status, overall system health, overall evidence health,
operational readiness scores, green/yellow/red readiness indicators, or any
other composite authority signal.

Counts must not be presented as conclusions. Every value must be deterministic
static capability metadata only.

The catalog must not synthesize authority, synthesize readiness, recommend
next actions, create tasks, or imply command readiness.

## Input authority

Authoritative input for Surface A is only a static reviewed capability
declaration of:

- implemented routes;
- schema versions;
- reviewed contracts;
- deferred surfaces;
- unsupported surfaces.

The catalog must not use as evidence or data:

- manifests;
- static reports;
- provenance graphs;
- map/orbit contexts;
- observation-study visual manifest;
- dashboard summaries;
- raw sidecars;
- raw JSON;
- artifact paths;
- image bytes;
- provider/live-data;
- mission records;
- optimization records;
- study records.

## Allowed content

Surface A may include only static deterministic capability metadata:

- labels;
- route references;
- schema versions;
- source domains;
- implemented, deferred, and unsupported status labels;
- reviewed contract references;
- limitations;
- disclaimers;
- static capability counts only if redundant and not conclusions.

## Forbidden inputs and outputs

The catalog must exclude:

- raw evidence;
- raw sidecars;
- raw JSON;
- artifact paths;
- image bytes;
- coordinates;
- intervals;
- samples;
- TLEs;
- graph nodes;
- graph edges;
- graph layout;
- graph rendering;
- chart data;
- map/orbit drawing data;
- frontend layout;
- dashboard UI;
- provider/live data;
- hidden owner IDs;
- SQL;
- stack traces;
- secrets;
- credentials;
- quantum claims;
- QUBO or solver internals;
- commands;
- tasks;
- recommendations;
- approvals;
- certification;
- exports or PDFs.

These exclusions apply to catalog content, labels, limitations, disclaimers,
errors, tests, and documentation examples.

## Determinism and non-leakage

The implementation must provide:

- stable entry ordering;
- timezone-aware UTC `read_at`;
- byte-identical responses after normalizing only `read_at`;
- no hidden IDs;
- no owner IDs;
- no raw internals;
- no data-derived aggregates;
- no synthesized claims.

Error responses must not expose internal paths, stack traces, secrets, DB URLs,
owner IDs, or hidden scope IDs.

## PostgreSQL and migration gates

No migration is expected for Surface A.

No persistence or table changes are expected.

No data-reading PostgreSQL validation is required for Surface A because it
does not read persisted domain data. An optional migrated-schema `200` smoke
test is acceptable but not mandatory.

Alembic head remains `m8b9c0d1e2f3` unless a separate reviewed migration
changes it.

## Implementation test gates

Implementation tests must verify:

- exact route exists once;
- no generic dispatcher;
- no mutation route;
- all query parameters rejected;
- `owner_id`, `principal`, and `user_id` rejected;
- render, provider, live, export, chart, map, and dashboard parameters
  rejected;
- deterministic output after normalizing `read_at`;
- catalog lists the current implemented read products correctly;
- deferred entries include observation-study visual manifest as deferred and
  contracted;
- no health, readiness, composite, rank, or score fields;
- no recommendation, task, or command fields;
- no chart, render, map, frontend, or dashboard fields;
- response shape differs from each individual read product;
- non-leakage over content and errors;
- no migration;
- no persistence.

## Catalog and OpenAPI consistency gate

Implementation must include a bidirectional catalog and OpenAPI
consistency test:

- every catalog entry marked `implemented` must have its route present in
  OpenAPI;
- every registered read-product route in OpenAPI must appear in the catalog.

Prefixes to check include:

- `/api/v1/visual-manifests`;
- `/api/v1/static-reports`;
- `/api/v1/provenance-graphs`;
- `/api/v1/map-orbit-contexts`;
- `/api/v1/product-summaries`.

This prevents the catalog from becoming stale.

Adding or removing any read-product route requires updating this catalog in
the same implementation slice. The implementation is incomplete if OpenAPI and
the catalog diverge.

## Implemented read products to catalog

Current implemented read products listed as `implemented` in the Surface A
response are:

- Mission visual manifest API:
  `GET /api/v1/visual-manifests/mission/{mission_id}`;
- Optimization-benchmark visual manifest API:
  `GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}`;
- Mission Static Report v1:
  `GET /api/v1/static-reports/mission/{mission_id}`;
- Optimization Benchmark Static Report v1:
  `GET /api/v1/static-reports/optimization-benchmark/{benchmark_id}`;
- Observation-study Provenance Graph API v1:
  `GET /api/v1/provenance-graphs/observation-study/geometry-planning-chain`;
- Mission Map/Orbit Context v1:
  `GET /api/v1/map-orbit-contexts/mission/{mission_id}`.

## Deferred and unsupported entries to catalog

Surface A includes these deferred or unsupported entries:

- Observation-study visual manifest:
  `GET /api/v1/visual-manifests/observation-study/{geometry_run_id}/{provenance_link_id}`;
  status `deferred`; note that the catalog lists it with a contract reference
  but does not authorize implementation and does not satisfy its final gate.
- Dashboard UI: status `deferred`; note that this contract is a JSON read
  surface only, not UI.
- Per-scope composition Surface B: status `deferred`; note that it requires a
  separate reviewed contract.
- Rendering, frontend, provider/live-data, exports, graph drawing, and map
  drawing: status `unsupported`; note that no implementation is authorized.

## Explicit exclusions

Beyond the single implemented Surface A static catalog route, this contract
does not implement or authorize:

- additional product summary API implementation;
- additional read-product catalog schema implementation;
- additional router implementation;
- migrations;
- persistence tables;
- persisted domain data reads;
- owner-scoped data reads;
- dashboard UI;
- frontend;
- rendering;
- charts;
- graph drawing;
- map drawing;
- provider/live-data behavior;
- live tracking;
- command/task/recommendation surfaces;
- evidence authority;
- synthesis;
- exports or PDFs;
- Quantum Studio;
- quantum implementation work.
