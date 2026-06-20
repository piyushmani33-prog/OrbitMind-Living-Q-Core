# ADR-0014 — JPL SBDB Connector (lookup + constrained query)

- **Status:** Accepted (2026-06-20)

## Context
Phase 3A needs authoritative asteroid/comet data. JPL's Small-Body Database (SBDB)
provides object lookup (`sbdb.api`) and a query service (`sbdb_query.api`) as official
machine-readable JSON APIs.

## Decision
- Implement guarded `SbdbConnector` (lookup) and `SbdbQueryConnector` (query) reusing
  the Phase 2 source pattern: network-off-by-default (`jpl_sbdb_enabled` + global
  switch), HTTPS-only, host `ssd-api.jpl.nasa.gov` allowlisted, no redirects, timeouts,
  bounded retries, size cap, content-type + JSON-schema validation, cache + minimum
  refresh, in-process keyed lock, full audit.
- **Lookup** accepts only approved identifiers (designation/number/name; regex-guarded;
  no arbitrary query fragments) via `sstr=`; returns a normalized `SmallBodyRecord`.
  Detects **not-found** and **ambiguous** responses and raises typed errors.
- **Query** exposes an **OrbitMind-owned `SbdbQueryFilter`** (allowlisted orbit class,
  sort field, output fields; bounded limit/offset) — never raw upstream params, filter
  languages, or arbitrary field names. Results carry truncation + pagination metadata
  and provenance. Sorting is deterministic (applied to the returned page).
- JPL response models are isolated under `sources/jpl/`; only normalized domain models
  leave the package. **No HTML scraping.**
- Verified against JPL SSD docs (inspected 2026-06-20); recorded in the source policy
  (`documentation_reference`). Conservative cache (24h TTL, 1h min refresh) since JPL
  publishes no hard cadence; rate limits + reuse rights marked **requires review**.

## Alternatives considered
1. **An external JPL SDK.** Unnecessary for simple HTTPS JSON GETs; violates minimal
   dependency policy. Rejected (only `httpx`, already present, is used).
2. **Pass-through query params.** Unsafe (injection, unbounded downloads). Rejected in
   favour of an allowlisted typed filter.

## Consequences
- A safe, offline-testable connector; bulk catalogue ingestion is explicitly excluded.
- Source lookup success is **not** treated as scientific verification of the orbit.

## Review trigger
Revisit when JPL changes the SBDB schema, when Alpha-5/expanded designations are needed
broadly, or when licensing terms are confirmed (see Risk Register).
