# Adding a Source Connector

The Phase 2 pattern for adding a real data source. The CelesTrak connector
(`sources/celestrak/`) is the reference implementation.

## Principles
- Implement behind the generic `OrbitalSource` interface (`sources/interface.py`).
  The orchestrator depends on `SourceResolver`, never on a concrete connector.
- **Keep source-specific response models inside the connector package.** They must
  not leak into domain/API models. Normalize to `OrbitalElementRecord`.
- Default to **offline**: network disabled by default; ship offline fixtures and
  mock all HTTP in tests (no live calls).
- Record complete **rights** (`SourcePolicy` + `SourceLicenseRecord`), defaulting to
  `requires_review=true`. Never invent legal rights.

## Steps
1. **Policy** — add a `SourceDefinition` + `SourcePolicy` in `sources/policies.py`
   (official name, configurable base URL, data category, attribution, license/usage
   note, min refresh, cache TTL, freshness thresholds, timeouts, retries, allowed
   methods/hostnames, HTTPS-only, redirect policy, max bytes, content types, schema
   format/version, failure behavior, effective network switch, policy version).
2. **Config** — add a per-source enable switch + tunables to `core/config.py` and
   `.env.example`. The effective network switch is `network_enabled AND <source>_enabled`.
3. **Response model** — a typed, validated model under `sources/<name>/models.py`
   with a `to_*` normalizer. Reject unknown/invalid records.
4. **Normalization** — convert to canonical inputs for the existing deterministic
   path. For orbital sources, produce TLE lines via `space/elements.py` so the
   verified SGP4 path is reused unchanged.
5. **Connector** — implement `OrbitalSource` (`sources/<name>/connector.py`):
   cache-first read, min-refresh enforcement, in-process keyed lock, safe HTTP via
   `SafeHttpFetcher`, schema validation, normalization, freshness assessment,
   provenance, health. Use the passed `SourceRepository` for cache/fetch persistence.
6. **Resolver** — extend `orchestration/source_resolver.py` to map the new
   `MissionSource` to the connector. Preserve **no silent fallback**.
7. **Persistence** — reuse the `source_*` tables; add a migration only if new
   columns/tables are needed. Never destructively modify existing mission data.
8. **Audit** — emit the standard source audit actions (no secrets/payloads).
9. **API** — the source endpoints are generic; ensure the new source appears in the
   catalog. Add a refresh path only if justified (explicit, min-interval-respecting).
10. **Tests** — unit (policy/allowlist/HTTPS/timeouts/retries/size/content-type/
    schema/normalization/freshness/cache/min-refresh/invalid-record/network-disabled/
    no-fallback/provenance) and integration with **mocked HTTP** (success, cache hit,
    suppression, timeout, HTTP failure, malformed, wrong content-type, oversized,
    stale/expired cache, mission execution). Keep the no-real-network guard intact.
11. **Docs** — update `SOURCE_OPERATIONS.md`, `DATA_RIGHTS_AND_SOURCE_POLICY.md`, the
    README, and add an ADR for the connector.

## Quality gates
`ruff check .`, `ruff format --check .`, `mypy src`, and
`pytest --cov=orbitmind` must all pass; maintain meaningful coverage for the new
modules. Do not lower quality settings to pass.
