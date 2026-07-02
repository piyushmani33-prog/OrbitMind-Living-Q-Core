# Visual Manifest API Contract — OrbitMind Living Q-Core

## Purpose and status

This is a Phase 5.3 documentation-only API contract.

It specifies a future read-only visual manifest API. The future API is a
discovery and index projection over already persisted records.

This document does not implement API routes, schema classes, routers, tests,
migrations, persistence, rendering, reports, dashboards, graphs, maps, exports,
or UI.

It builds on [VISUAL_INTELLIGENCE_BOUNDARY.md](VISUAL_INTELLIGENCE_BOUNDARY.md)
and [VISUAL_MANIFEST_SPECIFICATION.md](VISUAL_MANIFEST_SPECIFICATION.md). It
prepares acceptance criteria for a later implementation slice.

Status update: two domain-specific v1 routes are now implemented:

```http
GET /api/v1/visual-manifests/mission/{mission_id}
GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}
```

These routes are read-only, path-free, sidecar-free, and domain-specific. They
do not implement generic multi-domain dispatch, reports, dashboards, maps,
graphs, rendering, exports, live data, provider behavior, or Quantum Studio.
All other visual manifest domains remain reserved and deferred.

## Contract is not implementation

No route is implemented in Phase 5.3.

No schema class is added in Phase 5.3.

No OpenAPI surface is changed in Phase 5.3.

No persisted data is queried in Phase 5.3.

No tests are added in Phase 5.3 unless markdown tooling already exists.

PostgreSQL validation is not required for Phase 5.3.

## Future route shape

Recommended future route shape for later multi-domain expansion:

```http
GET /api/v1/visual-manifests/{domain}/{scope_id}
```

This generic route is not implemented. Phase 5.4 implemented the mission-only
route and Phase 5.7 implemented the optimization-benchmark route named above
instead of a generic dispatcher.

This shape follows the existing resource-read style and treats one
`(domain, scope_id)` pair as one scoped manifest resource. Query parameters are
reserved for bounded inclusion flags only.

Composite multi-ID domains must not be forced into this shape until a reviewed
stable scope handle exists.

Rejected alternatives:

- `GET /api/v1/visual-manifests?domain=...&scope_id=...` is less preferred
  because core identity belongs in the route path.
- Domain-specific separate routes should be avoided initially because they risk
  route sprawl.

## Domain allowlist and rollout

`{domain}` must be a closed allowlist.

An invalid domain should return a typed `422`, not `404`.

A valid domain with a missing scope should return `404`.

Implemented domains:

- `mission`
- `optimization-benchmark`

`mission` was the safest first domain because it has a single UUID-style scope
handle, an existing mission artifact inventory, no owner-scoping complexity in
current mission reads, and directly demonstrates locator normalization away from
relative path conventions toward safe handles and checksums.

`optimization-benchmark` is implemented as the second domain-specific route. It
delegates to the existing benchmark read-authentication path and preserves
receipt, signing, solver-comparison, and quantum-evidence redaction. See
[OPTIMIZATION_BENCHMARK_VISUAL_MANIFEST_CONTRACT.md](OPTIMIZATION_BENCHMARK_VISUAL_MANIFEST_CONTRACT.md).

Reserved but deferred future domains:

- `observation-study`
- `integrity-summary`
- `memory-evidence`

`observation-study` and `integrity-summary` require a reviewed stable scope
handle because existing surfaces are composite.

`memory-evidence` requires graph and citation semantics review.

## Query parameters

Allowed future query parameters are bounded inclusion flags only:

- `include_related`
- `include_diagnostics`

Parameters must use an explicit allowlist only. Unknown query parameters must
be rejected with a typed `422`. Future implementation should use an
unknown-parameter rejection pattern consistent with existing strict read APIs.

Explicitly rejected query parameters include:

- `owner_id`
- `principal`
- `user_id`
- arbitrary path
- raw sidecar selector
- raw SQL/filter syntax
- raw `result_json` selector
- raw `request_json` selector
- raw `link_json` selector
- arbitrary filesystem locator
- provider fetch parameter
- live-data switch
- verbosity or format parameter that suppresses disclaimers or limitations

Owner identity must come only from trusted dependencies where the underlying
source is owner-scoped. The request must never supply owner or principal
identity.

## Response concept

Future response fields should include:

- `schema_version`
- `manifest_id`
- `read_at`
- `source_domain`
- `scope_id`
- owner scope only where applicable
- `items`

Future item fields should include:

- item id
- item type
- media type
- safe artifact handle
- checksum handle
- source record handles
- canonical epistemic status
- verification state
- integrity or record-consistency state
- source, freshness, and test-only labels
- units
- limitations
- disclaimers
- presentation hints

`manifest_id` is a non-authoritative discovery/index identifier. It is not a
receipt id, attestation id, signature id, approval id, or certification id.

`read_at` must be timezone-aware UTC.

Presentation hints do not add scientific authority.

Limitation and disclaimer text should reuse canonical domain or source wording
where possible.

## Error semantics

Future typed error behavior should be:

- `404` for valid-domain missing resources.
- `404` for unauthorized owner-scoped resources to avoid existence disclosure.
- `422` for invalid domain.
- `422` for invalid scope ID format.
- `422` for unknown parameters.
- `422` for invalid parameter combinations.
- Sanitized `422` for checksum, tamper, or authentication mismatch where
  authentication is required.
- Existing typed domain errors should propagate in sanitized form.

Error responses must not include:

- raw exception text
- SQL
- raw paths
- sidecars
- snapshots
- receipt/signing internals
- quantum evidence internals
- provider secrets
- stack traces

## Owner isolation and trust model

Owner identity must come from trusted dependencies only.

Client-supplied owner or principal parameters are rejected.

Owner-scoped domains must not accept owner IDs from request query, path, or
body.

Cross-owner access should return `404`, not `403`, to avoid existence
disclosure.

Owner isolation applies only where the underlying source is owner-scoped.

`mission` is currently the recommended first domain partly because it avoids
owner-scoping complexity.

The first owner-scoped future domain must include an owner-isolation test
matrix.

## Non-leakage requirements

Future implementation must not expose:

- raw absolute filesystem paths
- artifacts-root value
- database URLs
- SQL
- stack traces
- environment values
- internal correlation keys
- internal idempotency keys
- provider secrets
- credentials
- raw sidecar JSON unless each field is explicitly reviewed safe
- raw `result_json`
- raw `request_json`
- raw `link_json`
- planning snapshots
- provenance snapshots
- receipt envelopes
- signing internals
- unredacted quantum evidence internals
- raw TLE lines
- raw samples by default
- raw intervals by default
- command claims
- taskability claims
- approval claims
- certification claims
- operational scheduling claims
- real-world asset-control claims

## Future API behavior constraints

Future API behavior must be:

- read-only
- no mutation
- no recomputation
- no artifact regeneration
- no provider fetch
- no live data
- no taskability
- no command readiness
- no approval
- no signed receipt
- no certification
- no quantum authority

## OpenAPI and guard-test expectations

This section is planning only.

Future implementation must include tests and guards for:

- OpenAPI route surface contains exactly the intended new `GET` route
- no `POST`, `PUT`, `PATCH`, or `DELETE` visual manifest routes
- unknown query parameters rejected
- invalid domain returns `422`
- valid-domain missing scope returns `404`
- client-supplied owner or principal parameters rejected
- no transaction ownership leak
- no forbidden imports or dependency inversion
- no raw absolute paths or artifacts-root leakage
- no raw sidecar JSON leakage
- no raw `result_json`, `request_json`, or `link_json` leakage
- no receipt, signing, or quantum evidence internals
- checksum or tamper mismatch maps to sanitized `422` where authentication is
  required
- owner-scoped future domains return `404` for cross-owner access

These are acceptance criteria for a later implementation, not tests added in
Phase 5.3.

## Implementation notes

Phase 5.4 implemented only one domain: `mission`.

Phase 5.7 implemented one additional domain: `optimization-benchmark`.

These phases did not implement all reserved domains.

These phases did not implement reports, graphs, maps, dashboards, frontend,
providers, or quantum work.

The implemented visual manifest APIs include unit/API tests and PostgreSQL
HTTP-boundary validation where persisted records are involved.

Future non-mission implementation should delegate to existing domain/query
services.

Future non-mission implementation should avoid transaction ownership mistakes.

Future non-mission implementation should return safe DTOs only.

Phase 5.4 mission v1 sources scientific context from persisted database
records only. It does not read sidecar JSON or image files. It omits
sidecar-only fields such as per-artifact units and per-artifact sidecar
verification. Per-artifact sidecar scientific context and file checksum
re-authentication are deferred to a future reviewed slice.

## Scientific-honesty boundaries

Manifest is discovery/index, not verification by itself.

Visuals interpret already persisted records.

Sample TLE data is not live satellite status.

Offline observation geometry is not live tracking.

Study-chain views are not operational access.

Integrity summaries are read-time record consistency, not real-world
authenticity.

Reports are not approval or signed receipts.

Dashboards are not command surfaces.

There is no taskability.

There is no command readiness.

There is no certification.

There is no quantum authority.

There is no general quantum advantage claim.

Generated answers are not treated as verified fact.

There are no confidence percentages on deterministic calculations.

There is no raw filesystem path leakage.

There is no SQL/internal `result_json` leakage.

There are no unredacted sidecar internals unless explicitly safe.

## Explicit exclusions for Phase 5.3

Phase 5.3 does not add:

- API route
- schema class
- router change
- migration
- persistence change
- runtime behavior change
- tests unless markdown tooling exists
- OpenAPI change
- rendering
- artifact regeneration
- report/PDF/export generator
- CesiumJS
- Leaflet
- D3
- React dashboard
- frontend
- live TLE retrieval
- live provider intake
- Space-Track
- live CelesTrak fetch
- NASA Earthdata
- operational scheduling
- command workflow
- taskability workflow
- approval workflow
- signed receipt workflow
- certification workflow
- real-world asset control
- Quantum Studio
- Qiskit implementation
- IBM Quantum
- AWS Braket
- Azure Quantum
- autonomous agents
- async workers
- batch compute
- UI/mobile work
- deployment work
- memory/consciousness layer
