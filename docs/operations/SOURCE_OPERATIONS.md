# Source Operations

Operating the Phase 2 CelesTrak connector. Default is **fully offline**; live access
is explicit and opt-in.

## Enabling live access (local development)
Both switches must be true (ADR-0009):

```bash
ORBITMIND_NETWORK_ENABLED=true
ORBITMIND_CELESTRAK_ENABLED=true
```

Optional tuning (see `.env.example`): base URL, timeouts, retries, cache TTL,
minimum refresh interval, max response bytes.

> The CelesTrak endpoint/format/cadence are **verified** against official GP-data
> documentation (R-012a closed; see `../architecture/CELESTRAK_VERIFICATION.md`); the
> minimum poll interval is floored at the official 2 hours. **Commercial/redistribution
> rights remain unconfirmed** (R-012b open) — review CelesTrak's terms before such use.

## Source API endpoints
All are local-development-only (no authentication yet):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/sources` | List registered sources + enabled/network state. |
| `GET /api/v1/sources/{id}` | Describe a source. |
| `GET /api/v1/sources/{id}/policy` | Operational + rights policy (no paths/secrets). |
| `GET /api/v1/sources/{id}/health` | Health (performs no network). |
| `GET /api/v1/sources/{id}/cache` | Sanitized cache-entry metadata (no file paths). |
| `POST /api/v1/sources/{id}/refresh?satellite_id=<norad>` | Explicit refresh. |

### Refresh behavior
`POST .../refresh` requires an explicit request, respects the network configuration
and the minimum refresh interval, returns the outcome
(`fetched | cached | suppressed | failed | disabled`), and records an audit event.
It never loops or polls in the background.

## Running a CelesTrak mission
```bash
curl -s http://127.0.0.1:8000/api/v1/missions/orbit-propagation \
  -H "content-type: application/json" \
  -d '{
        "satellite_id": "25544",
        "source": "celestrak",
        "start_time": "2026-06-19T12:00:00Z",
        "end_time":   "2026-06-19T12:30:00Z",
        "step_seconds": 300
      }'
```
- `satellite_id` for CelesTrak is a **NORAD catalog number** (digits).
- The response `source_data` block reports freshness, cache status, data epoch,
  checksum, policy version, and limitations.
- **No silent fallback:** if the source is unavailable the mission fails safely
  (`source_unavailable`/`network_disabled`). To opt into the bundled sample on
  failure, set `"allow_sample_fallback": true` — the result is then explicitly
  labelled `source=sample`, `freshness=test-fixture`.

## Health states
`healthy` (last fetch ok) · `degraded` (last fetch failed) · `disabled` (network/
source off) · `unknown` (no fetches yet) · `unavailable`.

## Failure handling
Failed external missions are persisted as `failed` with `source.request_failed` /
`source.network_rejected` / `source.schema_rejected` and `mission.external_failed`
audit events, plus a source health event. Inspect via
`GET /api/v1/missions/{id}`.
