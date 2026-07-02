# Optimization Benchmark Visual Manifest Contract -- OrbitMind Living Q-Core

## Purpose and status

This is a Phase 5.6 documentation-only contract for a future
`optimization-benchmark` visual manifest domain.

No optimization-benchmark visual manifest route is implemented in Phase 5.6.
This document does not add API routes, schemas, routers, persistence, runtime
behavior, rendering, reports, exports, frontend work, provider/live-data
behavior, or Quantum Studio work.

The future route idea is:

```http
GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}
```

That route is only a future domain-specific proposal. A future implementation
must not create a generic visual manifest dispatcher. Future visual manifest
implementation must remain domain-specific unless separately reviewed and
approved.

Optimization benchmark manifests need this contract before implementation
because they touch receipt, signing, quantum evidence, and solver-comparison
boundaries.

Phase 5.7 implementation clarification: the visual manifest response remains
path-free and sidecar-free. The route may delegate to the existing benchmark
read-authentication path, which can use existing sidecar authentication
internally, but the route and response schema must not directly parse, expose,
or repackage sidecar JSON.
Deleting artifact files or required authentication sidecars can make delegated
re-authentication fail. That failure must fail closed with a sanitized `422`
and artifacts/evidence withheld wording. This differs intentionally from the
mission visual manifest file-absence tolerance.

## Safe v1 top-level shape

A future v1 response should mirror the mission visual manifest shape, but it is
not implemented yet. Safe top-level concepts are:

- `schema_version`
- `manifest_id`
- `read_at`
- `source_domain = "optimization-benchmark"`
- `scope_id`
- `items`
- `limitations`
- `disclaimer`

`manifest_id` is a non-authoritative discovery/index identifier. It is not a
receipt id, attestation id, signature id, approval id, certification id, or
operational clearance.

`read_at` should be a timezone-aware UTC timestamp if this route is later
implemented.

## Safe item concepts

Future item projections may include only path-free, safe artifact identity and
label fields:

- item id
- item type
- media type
- path-free artifact handle
- checksum handle
- source record handles
- canonical epistemic status
- source/freshness labels
- limitations
- disclaimers
- non-authoritative presentation hints

`ArtifactView` is the current projection baseline for optimization artifact
metadata. It exposes safe artifact metadata and deliberately does not expose
on-disk paths. A future optimization benchmark visual manifest must preserve
that boundary: on-disk paths are never exposed.

Presentation hints are layout or grouping suggestions only. They do not add
scientific authority, verification, approval, certification, command readiness,
or operational meaning.

## Read-time evidence state

A future manifest may project only the existing read-time authentication state
already exposed by authenticated benchmark reads:

- `verified`
- `integrity_failed`
- `receipt_status`

Allowed `receipt_status` values are:

- `signed`
- `none`
- `integrity-failed`

The manifest may project these states only as already exposed by the
authenticated benchmark read path. It must never recompute verification,
re-authenticate independently, re-sign anything, issue a new receipt, upgrade
evidence status, reinterpret receipt status, or expose receipt internals.

If a future implementation needs authenticated artifact metadata, it should
delegate to the existing benchmark read/authentication path rather than
duplicating authentication logic.

## Receipt and signing boundary

`receipt_status = "signed"` is a persisted record-integrity provenance signal
only. It is not:

- approval
- authorization
- certification
- signed-receipt authority conferred on the consumer
- operational clearance
- command readiness

A future optimization benchmark manifest must never expose:

- receipt envelopes
- canonical receipt entries
- HMACs
- signatures
- signer identity
- signer internals
- signing key identifiers
- signing key configuration
- key material
- digests being recomputed

The manifest must not let users infer signing keys, receipt payloads, or
receipt validation internals from the response shape.

## Quantum evidence boundary

Quantum-related visual manifest items may appear only as artifact identity
metadata and labels sourced from authenticated reads.

Future responses must never expose:

- unredacted `quantum_evidence`
- raw quantum samples
- circuit definitions
- QUBO internals
- provider state
- live provider access
- quantum execution internals

Quantum items are non-authoritative diagnostics. No general quantum advantage
is claimed. No quantum authority is granted.

Absence of quantum artifacts is normal when no persisted quantum samples exist.
A completed benchmark with no persisted quantum samples legitimately may have
no quantum visual items. Absence of quantum visual items is not automatically
an error or integrity failure.

## Solver-comparison boundary

The manifest may project persisted comparison labels only as recorded. It must
preserve classical-baseline-authoritative framing.

A future manifest must not:

- re-derive solver comparison conclusions
- reinterpret comparison conclusions
- summarize beyond recorded enum/status labels
- say "quantum outperformed" unless that exact supported conclusion is already
  recorded
- expose raw solver internals
- expose QUBO internals
- expose thresholds as if client-selectable
- present optimization outputs as operational recommendations

Optimization artifacts are visual/discovery records for bounded benchmark
evidence. They are not operational schedules, approvals, command surfaces, or
claims of general quantum advantage.

## Excluded fields and internals

A future optimization benchmark manifest must explicitly prohibit exposure of:

- artifact `path`
- `sidecar_path`
- raw sidecar JSON
- artifacts-root value
- DB URLs
- environment values
- internal correlation IDs
- idempotency keys
- SQL
- stack traces
- secrets
- provider state
- receipt envelopes
- signing internals
- signatures
- signing key identifiers or configuration
- unredacted quantum evidence
- raw samples
- circuits
- QUBO internals
- solver internals

These exclusions apply to success responses, error responses, OpenAPI examples,
tests, and documentation examples.

## Scientific-honesty boundaries

A future optimization benchmark manifest must remain:

- read-only
- DB-only
- path-free
- sidecar-free
- non-authoritative

It is not:

- live tracking
- operational access
- approval
- signed receipt
- certification
- taskability
- command readiness
- quantum authority
- general quantum advantage

The manifest is a discovery/index projection over already persisted records. It
does not verify truth by itself and must not upgrade the scientific meaning of
the underlying benchmark, artifacts, receipts, or solver comparisons.

## Future acceptance criteria

Any future implementation must include guard tests for:

- clean benchmark id validation
- unknown benchmark returning `404`
- path-free response
- no `sidecar_path`
- no raw paths
- no raw sidecar JSON
- no receipt envelope, signature, or signing internals
- no unredacted quantum evidence
- no raw samples, circuits, or QUBO internals
- deterministic output for the same persisted benchmark
- no provider or live-data calls
- no rendering, report, export, or frontend work
- PostgreSQL HTTP-boundary validation

Guard tests should also confirm that the route remains domain-specific and does
not introduce a generic visual manifest dispatcher.

## Owner scope and trust model

Optimization reads are currently not owner-scoped, matching the current
persisted benchmark read behavior.

Future owner isolation must be designed separately before changing `404` or
isolation semantics for optimization benchmark manifests. Client-supplied owner
or principal parameters must not be accepted by default.

## Explicit exclusions for Phase 5.6

Phase 5.6 does not add:

- code
- tests
- migrations
- API routes
- schemas
- generic dispatcher
- optimization visual manifest implementation
- reports
- PDF
- export
- rendering
- D3
- Leaflet
- CesiumJS
- dashboard or frontend work
- provider or live-data behavior
- Quantum Studio
- quantum implementation work
