# Small-Body Cache and Freshness (JPL)

Reuses the Phase 2 source-cache architecture (ADR-0010) with **JPL-specific policies**.
No Redis, no distributed locking.

## Cache
- Raw JPL bodies cached under `cache/jpl-sbdb/`, `cache/jpl-sbdb-query/`, `cache/jpl-cad/`
  (gitignored; path-traversal rejected). Metadata in `source_cache_entries`.
- **Deterministic cache key:** `"<source_id>:" + sorted("k=v"&…)` over canonicalized
  query parameters (`sources/jpl/common.canonical_cache_key`).
- Recorded per entry: source URL, checksum, schema version, HTTP status, content type,
  fetched timestamp, expiry, last success/failure, failure reason, policy version.

## Fetch discipline (per request)
1. **Valid cache hit** (within TTL, default 24h) → serve from cache.
2. **Minimum refresh interval** (default 1h) → a refresh within the window is
   **suppressed**; the cached body is served.
3. **Live fetch** otherwise, under an **in-process keyed lock** so concurrent identical
   queries do not stampede the source.

`GET /health` performs **no** network and no refresh.

## Freshness
Freshness reflects how recently data was obtained from JPL (data age vs policy
thresholds): `test-fixture / current / fresh / aging / stale / expired / unavailable /
invalid`. A separate liveness label (`live / cached / stale / expired / fixture`) is
auto-downgraded so stale/expired data is **never** reported as live. Every result reports
source, record id, data epoch, fetch time, cache status, freshness, policy version,
checksum, and limitations.

## Tuning (env)
`ORBITMIND_JPL_CACHE_TTL_SECONDS` (86400), `ORBITMIND_JPL_MIN_REFRESH_SECONDS` (3600),
`ORBITMIND_JPL_MAX_RESULTS` (200). Small-body solutions change slowly, so caching is
aggressive by design. Do not set the minimum refresh below JPL's (informal) guidance.
