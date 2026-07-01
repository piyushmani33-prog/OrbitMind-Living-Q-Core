# Observation Study API Flow

## Purpose

This guide explains the existing API flow for reading an authenticated observation
study chain:

1. derive geometry-derived eligibility from an already persisted geometry run;
2. execute provenance-anchored planning from the returned eligibility set;
3. retrieve read-only study-chain traceability for the geometry and planning records.

The flow is designed for scientific traceability. It does not create operational
tasking authority, command readiness, approval, or a signed receipt.

## Step 0: Start from an already persisted offline geometry run

This flow starts from an already persisted offline geometry run.

There is no public geometry-compute or create-run HTTP endpoint. Geometry runs are
produced by the internal offline application/service path from pinned inputs, not
by posting raw TLEs to a public API.

Do not use or document any public geometry compute, geometry run creation, or raw
TLE-to-geometry-run HTTP flow. Those capabilities are not part of the current API
surface.

## API sequence overview

The existing sequence uses three public routes:

1. `POST /api/v1/observation-geometry/runs/{run_id}/derive-eligibility`
2. `POST /api/v1/observation-planning/provenance-anchored-executions`
3. `GET /api/v1/observation-studies/geometry-planning-chain?geometry_run_id=...&provenance_link_id=...`

The ID flow is:

1. Start with an existing `geometry_run_id`.
2. Derive eligibility. The response returns `eligibility_set_id`.
3. Execute provenance-anchored planning with that `eligibility_set_id`.
4. Anchored execution returns planning metadata, including `link_id`.
5. Retrieve the study chain with the original `geometry_run_id` and the returned
   `link_id` passed as `provenance_link_id`.

## Step 1: Derive geometry-derived eligibility

Use an already persisted geometry run:

```http
POST /api/v1/observation-geometry/runs/{run_id}/derive-eligibility
```

Example body:

```json
{
  "requested_by": "analyst"
}
```

Optional fields supported by this API are:

- `requested_by`: attribution only; it does not control owner authority.
- `derivation_label`: bounded label for a distinct derivation identity.
- `minimum_peak_elevation_deg`: deterministic filter for visibility intervals.

The response includes safe derivation metadata, including `eligibility_set_id`.
It does not expose raw geometry `result_json`, raw samples, raw intervals, TLE
lines, provider state, SQL metadata, local paths, or stack traces.

Existing response disclaimer:

> Geometry-derived eligibility is deterministic model-derived visibility eligibility
> from pinned/offline observation-geometry computation. It is not live tracking, not
> operational access, not taskability, not command readiness, not approval, not a
> signed receipt, and not quantum-authoritative.

## Step 2: Execute provenance-anchored planning

Use the `eligibility_set_id` from Step 1:

```http
POST /api/v1/observation-planning/provenance-anchored-executions
```

Example body:

```json
{
  "requested_by": "analyst",
  "eligibility_set_id": "returned-eligibility-set-id"
}
```

The request must provide exactly one eligibility-set lookup:

- `eligibility_set_id`, or
- `eligibility_set_checksum`.

Clients must not send `owner_id`. Owner authority comes from the trusted local
owner dependency. Clients also must not send raw geometry payloads, raw samples,
raw intervals, TLE lines, or raw eligibility windows.

The response includes planning request/run/plan metadata and the provenance-planning
`link_id`. That `link_id` is the value to pass as `provenance_link_id` in Step 3.

Existing response disclaimer:

> Provenance-anchored bounded observation planning over authenticated fixture-backed,
> user-declared, or geometry-derived eligibility windows. Geometry-derived eligibility
> comes from pinned/offline deterministic model output; eligibility windows do not
> prove live tracking, orbital visibility, operational access, taskability, approval,
> command readiness, or signed receipt status. Planning remains classically authoritative;
> quantum execution is not authoritative.

## Step 3: Retrieve the observation study chain

Use the original `geometry_run_id` and the Step 2 `link_id`:

```http
GET /api/v1/observation-studies/geometry-planning-chain?geometry_run_id={geometry_run_id}&provenance_link_id={link_id}
```

This route returns read-only authenticated traceability across:

- geometry request and run identity;
- geometry-derived eligibility provenance;
- eligibility set and selected windows;
- provenance preparation identity;
- anchored planning request, run, optional plan, and link;
- chain checks and limitations.

Existing response disclaimer:

> This is read-only authenticated traceability over pinned/offline geometry-derived
> eligibility and classical planning records. It does not prove live tracking,
> operational access, taskability, command readiness, approval, signed receipt status,
> or quantum authority.

## Optional: Retrieve a compact integrity summary

When a compact consistency view is enough, use the same `geometry_run_id` and
`provenance_link_id` with the optional integrity-summary route:

```http
GET /api/v1/observation-studies/geometry-planning-chain/integrity-summary?geometry_run_id={geometry_run_id}&provenance_link_id={link_id}
```

This route is a read-only record-integrity summary over the same persisted records
used by the full study-chain route. A successful response returns status exactly
`chain-checks-consistent` and summarizes read-time checksum and stored-record
consistency for pinned/offline geometry-derived eligibility and classical planning
records.

The integrity-summary route is success-only and fail-closed. If the underlying
chain fails authentication, mismatch, owner-isolation, or tamper checks, the API
returns typed errors such as `404` or sanitized `422`. It does not return a
failed-summary wire shape.

This route does not replace the full study-chain route. Use the full study-chain
route when detailed geometry, eligibility, and planning traceability is needed. Use
the integrity-summary route when the compact consistency summary is enough.

The integrity summary is not real-world authenticity, live tracking, operational
access, taskability, command readiness, approval, a signed receipt, or
quantum-authoritative.

## Replay and idempotency behavior

The first successful provenance-anchored execution may return `201 Created`.
An exact replay may return `200 OK`.

Replay means persisted planning request, planning run, plan, and provenance link
records were reused when the authenticated scientific identity matches. Replay does
not mean operational execution, real asset scheduling, command readiness, approval,
or any real-world tasking action.

## Owner isolation and trust model

Owner identity comes from the trusted local owner dependency. Do not send `owner_id`
in request bodies or query parameters.

The backend owner-scopes geometry runs, eligibility sets, planning records, and study
chain reads. A missing or cross-owner record is returned as not found without exposing
another owner's IDs, checksums, or internal state.

This local trusted-owner model is not a claim of full external multi-tenant
authentication.

## Tamper and error behavior

Expected public error categories:

- malformed IDs or invalid request shape: `422`;
- missing or cross-owner geometry run, eligibility set, or provenance link: `404`;
- geometry/link mismatch: `422`;
- tampered geometry, provenance, eligibility, link, or planning record: sanitized `422`.

Raw internal snapshots, SQL details, database URLs, local paths, stack traces, and raw
exception text should not be exposed.

## Response safety and non-leakage

The study-chain API exposes safe summaries only, such as:

- IDs and checksums;
- source identity checksum;
- counts;
- planning and link metadata;
- chain checks;
- limitations and disclaimers.

It must not expose:

- raw `result_json`;
- raw `request_json`;
- raw `link_json`;
- raw provenance snapshots;
- raw planning snapshots;
- TLE lines;
- raw samples;
- raw intervals;
- SQL metadata;
- local paths;
- stack traces;
- provider state.

## Scientific-honesty limits

This flow is deterministic model-derived work from pinned/offline inputs. It provides
candidate visibility windows and authenticated classical planning records. It is not:

- live tracking;
- operational access;
- taskability;
- command readiness;
- approval;
- a signed receipt;
- quantum-authoritative.

## What this flow does not do

This flow does not:

- compute geometry through a public HTTP endpoint;
- retrieve live TLEs;
- call Space-Track or live CelesTrak;
- use provider credentials;
- schedule or command real assets;
- verify taskability;
- approve operations;
- sign receipts;
- execute quantum computation.

## Future follow-up: executable contract examples

A later documentation or test-only slice may add executable contract examples for
the three-route sequence. Those examples should stay aligned with the existing API
schemas and keep the same scientific-honesty boundaries.
