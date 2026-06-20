# Data Rights and Source Policy

How OrbitMind records source rights and governs access. The platform **never
invents legal rights** and labels unclear terms as requiring review.

## Typed model
Each source has a typed `SourcePolicy` (`sources/models.py`) embedding a
`SourceLicenseRecord`. A snapshot is persisted (`source_definitions`,
`source_policies`) on startup for auditability.

`SourcePolicy` records: source id, official name, configured base URL, data
category, attribution text, license/usage note, minimum polling interval, cache
TTL, freshness thresholds, connect/read timeouts, retry policy, allowed HTTP
methods, allowed hostnames, HTTPS-only, redirect policy, max response bytes,
allowed content types, schema format + version, failure behavior, effective
network-enabled flag, and policy version.

`SourceLicenseRecord` records: license name, attribution text, usage note,
`requires_review` (default **true**), `commercial_use_confirmed` (default
**false**), and a reference URL.

## CelesTrak rights posture (as recorded)
- **Attribution:** "Orbital data courtesy of CelesTrak (https://celestrak.org)."
- **License/usage:** marked **REQUIRES REVIEW**. The exact licensing,
  redistribution, and commercial-use terms are **not confirmed** in this repository
  and must be reviewed against the official CelesTrak terms before any
  redistribution or commercial use.
- `requires_review = true`, `commercial_use_confirmed = false`. **No commercial
  rights are claimed.**
- Endpoint/format/cadence **verified** against official GP-data docs (R-012a closed;
  `CELESTRAK_VERIFICATION.md`); min poll interval floored at the official 2 hours.
  **Legal/commercial rights remain unconfirmed (R-012b open).**

## JPL SSD/CNEOS rights posture (Phase 3A, as recorded)
- **Sources:** JPL Small-Body Database (`sbdb.api`), SBDB Query (`sbdb_query.api`),
  Close-Approach Data (`cad.api`) — host `ssd-api.jpl.nasa.gov`.
- **Attribution:** "Data courtesy NASA/JPL Solar System Dynamics (https://ssd.jpl.nasa.gov)."
- **License/usage:** marked **REQUIRES REVIEW**. NASA/JPL data is generally U.S.
  Government work, but exact redistribution, commercial-use, and **rate-limit** terms are
  **not confirmed** in this repository and must be reviewed against official JPL/CNEOS
  terms before redistribution or commercial use. `requires_review = true`,
  `commercial_use_confirmed = false`. **No commercial rights claimed.**
- **Endpoints/cadence:** verified against JPL SSD docs (inspected 2026-06-20); recorded
  in each policy's `documentation_reference`. JPL publishes no hard polling cadence →
  conservative cache (24h TTL) + 1h min refresh; rate limits remain open (R-019).

## Liveness / freshness honesty
External data is classified and **never** presented as live when it is not (see
[CACHE_AND_FRESHNESS.md](../operations/CACHE_AND_FRESHNESS.md), ADR-0010). Bundled
sample data is always `test-fixture` and labelled "not live" (SR-05).

## Adding rights for a new source
A new connector MUST supply a complete `SourcePolicy` + `SourceLicenseRecord`,
defaulting to `requires_review=true` until the owner confirms the terms. Do not set
`commercial_use_confirmed=true` unless the source explicitly confirms it.

## Enforcement & audit
- Access is gated by the network switches (ADR-0009).
- Every fetch is recorded (`source_fetches`) with outcome + checksum (no payloads).
- Audit events capture access requested, network rejected, cache hit/miss, refresh
  suppressed, request started/completed/failed, schema rejected, record normalized,
  stale record used, and external mission completed/failed — never secrets or
  oversized payloads.
