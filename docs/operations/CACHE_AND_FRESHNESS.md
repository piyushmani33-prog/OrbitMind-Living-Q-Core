# Cache and Freshness

How OrbitMind caches external orbital data and classifies its freshness (ADR-0010).

## Cache layout
- Raw bodies: `cache/<source_id>/<sha256(cache_key)>.json` (gitignored; path
  traversal rejected).
- Metadata: `source_cache_entries` table — cache key, URL, checksum, schema version,
  HTTP status, content-type, `fetched_at`, `expires_at`, `effective_epoch` (data
  epoch), `last_success_at`, `last_failure_at`, `failure_reason`.
- Deterministic cache key: `"<source_id>:<selector>"`, e.g. `celestrak:25544`.

## Fetch decision (per request)
1. **Valid cache hit** — entry exists and `now < expires_at` (and not a forced
   refresh) → serve from cache (`cache_status=hit`, outcome `cached`).
2. **Minimum refresh interval** — if a fetch happened within `min_refresh_seconds`,
   a refresh is **suppressed**; the cached body is served (outcome `suppressed`,
   `cache_status=suppressed`). Prevents over-polling / refresh storms.
3. **Live fetch** — otherwise, a single live fetch occurs under an in-process keyed
   lock (so concurrent requests for the same key don't stampede). On success the
   body is cached and `expires_at = now + cache_ttl_seconds`.

`GET /health` performs **no** network and no refresh.

## Freshness states (data-epoch age vs policy thresholds)
| State | Meaning |
|-------|---------|
| `test-fixture` | Bundled sample data; never live. |
| `current` | Epoch within `freshness_current_seconds` (default 6h). |
| `fresh` | Within `freshness_fresh_seconds` (default 24h). |
| `aging` | Within `freshness_aging_seconds` (default 3d). |
| `stale` | Within `freshness_stale_seconds` (default 7d). |
| `expired` | Older than the stale threshold. |
| `unavailable` | No data could be obtained. |
| `invalid` | Data failed schema/validation. |

A separate **liveness** label (`live | cached | stale | expired | fixture`) is
downgraded automatically: data classified `stale`/`expired` is never reported as
`live` or `cached`.

## What a mission reports
Every external-source mission result includes `source_data`: source id, record
identifier, data epoch, fetch timestamp, cache status, freshness state, liveness,
policy version, checksum, and a limitations note.

## Tuning (env vars)
`ORBITMIND_CELESTRAK_CACHE_TTL_SECONDS` (default 7200),
`ORBITMIND_CELESTRAK_MIN_REFRESH_SECONDS` (default 3600). Do not set the minimum
refresh below the source's published update cadence.
