# Adding a JPL Connector

The Phase 3A pattern for a new JPL SSD/CNEOS service (e.g. Horizons, Sentry — both
deferred). The SBDB/CAD connectors under `src/orbitmind/sources/jpl/` are the reference.

## Principles
- **Verify against official JPL docs first**; record the inspection date in the source
  policy (`documentation_reference`). Use official machine-readable JSON only — **no
  scraping**.
- Network **off by default**; a live request needs the global switch AND a source switch.
- Keep JPL response models isolated; only normalized domain models leave the package.
- Reuse the shared cache-first fetcher (`sources/fetching.CachedSourceFetcher`) and the
  Phase 2 source repository (`source_fetches` / `source_cache_entries`).

## Steps
1. **Config:** add `ORBITMIND_JPL_<SERVICE>_ENABLED` + a configurable base URL +
   conservative timeouts/cache/limits in `core/config.py` and `.env.example`.
2. **Policy:** add a `SourceDefinition`/`SourcePolicy` in `sources/jpl/policies.py`
   (host `ssd-api.jpl.nasa.gov` allowlisted, HTTPS-only, GET-only, size cap,
   `application/json`, `requires_review=true`, `commercial_use_confirmed=false`). Register
   it in `SourceCatalog`.
3. **Response models:** typed models in `sources/jpl/<service>_models.py` (numbers may be
   strings; validate structure). Detect not-found/ambiguous/empty.
4. **Normalization:** deterministic `sources/jpl/normalization.py` functions →
   domain models (missing ⇒ `None`, never `0`; explicit units).
5. **Connector:** `sources/jpl/<service>_connector.py` — typed allowlisted filter (no raw
   params/SQL/arbitrary fields), bounded results, deterministic sort, truncation +
   provenance, schema validation, cache key canonicalization, in-process keyed lock.
6. **Service + API:** thread fetch → verify → persist → audit → (optional) artifacts;
   expose narrow endpoints; clear errors (network/source disabled, not found, ambiguous,
   invalid query, unavailable, schema changed, rejected, stale/expired, limit exceeded).
   No silent fallback to a different object.
7. **Persistence + migration** (additive), **audit events**, **docs/ADR/Risk Register**,
   and **offline tests** (mocked HTTP; keep the no-real-network guard intact).

## Quality gates
ruff, ruff-format, mypy, pytest must pass; meaningful coverage for new modules.
