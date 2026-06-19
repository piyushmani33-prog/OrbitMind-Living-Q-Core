# ADR-0010 — Source Cache and Freshness

- **Status:** Accepted (2026-06-19)

## Context
External orbital data must be cached (to respect the source's update cadence and
avoid over-polling), and its age must be classified so that stale/expired data is
never presented as live. Redis and distributed locking are out of scope for Phase 2.

## Decision
- **Cache design:** raw response bodies are written under a controlled cache
  directory (`cache/<source_id>/<hash>.json`, path-traversal rejected); **metadata**
  (cache key, URL, checksum, schema version, HTTP status, content-type, fetched/
  expiry/effective-epoch timestamps, last success/failure) is stored in the database
  (`source_cache_entries`). Large raw payloads are not duplicated in the DB.
- **Cache discipline:** deterministic cache key `"<source_id>:<selector>"`; serve a
  valid entry within `cache_ttl_seconds`; enforce `min_refresh_seconds` between live
  fetches (prevents refresh storms / over-polling); an **in-process keyed lock**
  serializes concurrent refreshes for the same key (no distributed locking).
- **Freshness states:** `test-fixture | current | fresh | aging | stale | expired |
  unavailable | invalid`, computed from policy thresholds + the data epoch + cache
  state. A separate `liveness` (`live | cached | stale | expired | fixture`) is
  **downgraded** automatically so stale/expired data is never labelled live.
- Every mission using external data reports source, record id, data epoch, fetch
  timestamp, cache status, freshness status, policy version, checksum, and
  limitations (`MissionSourceData`).

## Alternatives considered
1. **Store raw payloads in the DB.** Simpler but duplicates/bloats large blobs; the
   prompt prefers controlled file storage + DB metadata. Rejected.
2. **Redis cache + distributed lock.** Out of scope for Phase 2; unjustified ops.
   Rejected.
3. **Single freshness flag.** Conflates data-age with cache-TTL and live/cached
   liveness. Rejected in favor of explicit states + liveness.

## Consequences
- Auditable, offline-testable caching with no extra infrastructure.
- File-cache writes are not transactional with the DB metadata; on rollback an
  orphan body file may remain (harmless; overwritten on next fetch).
- Single-process locking only; multi-process refresh coordination is a future
  (Phase 8) concern.

## Review trigger
Revisit when multiple processes/instances share a cache, when a source needs
conditional requests (ETag/If-Modified-Since), or when moving to object storage.
