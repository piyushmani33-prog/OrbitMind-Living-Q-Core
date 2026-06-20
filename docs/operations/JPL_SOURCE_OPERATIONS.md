# JPL Source Operations

Operating the Phase 3A JPL small-body connectors (SBDB lookup, SBDB query, CAD).
Default is **fully offline**; live access is explicit and opt-in.

## Enabling live access (local development)
A live JPL request requires the global switch AND the applicable source switch:

```bash
ORBITMIND_NETWORK_ENABLED=true
ORBITMIND_JPL_SBDB_ENABLED=true   # governs SBDB lookup AND constrained query
ORBITMIND_JPL_CAD_ENABLED=true    # governs Close-Approach Data
```

Optional tuning (see `.env.example`): base URLs, timeouts, cache TTL (default 24h),
minimum refresh (default 1h), max results (default 200), max CAD span (default 366 days).

> Endpoints verified against JPL SSD/CNEOS docs (inspected 2026-06-20):
> `https://ssd-api.jpl.nasa.gov/sbdb.api`, `/sbdb_query.api`, `/cad.api`. JPL publishes
> no hard polling cadence — conservative defaults are used and rate limits are marked
> **requires review**.

## Endpoints (local-development-only; no auth yet)
| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/small-bodies/lookup` | Resolve one asteroid/comet by identifier. |
| `POST /api/v1/small-bodies/query` | Constrained SBDB query (allowlisted, bounded). |
| `POST /api/v1/small-bodies/close-approaches` | Close-approach data (source-reported). |
| `GET  /api/v1/small-bodies/{id}` | Stored small body. |
| `GET  /api/v1/small-bodies/{id}/close-approaches` | Stored approaches (by designation). |
| `GET  /api/v1/space-objects` / `/{id}` | Unified, kind-agnostic objects. |

## Example (lookup)
```bash
curl -s http://127.0.0.1:8000/api/v1/small-bodies/lookup \
  -H "content-type: application/json" -d '{"identifier": "433"}'
```
Identifiers are approved formats only (number/name/designation; e.g. `433`, `Eros`,
`2021 AB`, `1P/Halley`). Alpha-5/alphanumeric expanded designations are **not yet
supported**.

## Errors (safe; no internals)
`network_disabled` (409) · `object_not_found` (404) · `ambiguous_identifier` (409) ·
`source_schema_error` (502) · `source_unavailable` (503) · invalid query (422) ·
result-limit exceeded (422). **No silent fallback to a different object.**

## Failure handling & audit
Failures are audited (`smallbody.jpl_request_failed`, `smallbody.record_rejected`) and
never expose payloads/paths/secrets. Stale records are labelled stale, never live.

## Data-rights
NASA/JPL terms are **requires review**; attribution recorded; no commercial rights
claimed. See `../architecture/DATA_RIGHTS_AND_SOURCE_POLICY.md`.
