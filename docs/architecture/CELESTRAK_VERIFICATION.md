# CelesTrak Source Policy Verification

Verification of the implemented CelesTrak connector/policy against official CelesTrak
GP-data documentation, **as cited by the reference documents** (both
`OrbitMind Living Q-Core.docx` and the Feasibility Brief cite
`https://www.celestrak.org/NORAD/documentation/gp-data-formats.php`).

> **No live requests were made.** Verification is documentary. The technical
> endpoint/format/cadence is supported by official documentation; **commercial/
> redistribution rights are NOT verified** (see R-012b).

| Item | Official guidance (as cited) | Implementation | Status |
|------|------------------------------|----------------|--------|
| **Hostname** | `celestrak.org` (GP data + documentation). | Base URL configurable; hostname **allowlisted** from the configured URL (`celestrak.org`); HTTPS-only. | ✅ matches |
| **Machine-readable format** | GP data via `gp.php` in TLE/2LE/XML(OMM)/**JSON(OMM)**/CSV/KVN. | `FORMAT=json` → OMM JSON array (structured GP; **no scraping**). | ✅ matches |
| **OMM/JSON fields** | Standard OMM keys: `OBJECT_NAME/OBJECT_ID/EPOCH/MEAN_MOTION/ECCENTRICITY/INCLINATION/RA_OF_ASC_NODE/ARG_OF_PERICENTER/MEAN_ANOMALY/EPHEMERIS_TYPE/CLASSIFICATION_TYPE/NORAD_CAT_ID/ELEMENT_SET_NO/REV_AT_EPOCH/BSTAR/MEAN_MOTION_DOT/MEAN_MOTION_DDOT`. | `CelestrakGpRecord` validates these (uppercase aliases); normalized to a Satrec via `sgp4.omm.initialize` (round-trip verified < 1e-5 km). | ✅ matches |
| **Query pattern** | `gp.php?CATNR=<n>&FORMAT=json` (single object); also `GROUP=`, `NAME=`, `INTDES=`. | Single-object `CATNR=<norad>&FORMAT=json`. | ✅ matches |
| **Update guidance / cadence** | CelesTrak checks for new GP only **every 2 hours**; "no reason to poll more often." | Cache TTL 7200s; **minimum refresh floored at 7200s** (`CELESTRAK_OFFICIAL_MIN_REFRESH_SECONDS`) regardless of config. | ✅ matches (corrected — was 3600s) |
| **Minimum polling interval** | ≥ 2 hours. | Policy floors `min_refresh_seconds = max(config, 7200)`. | ✅ no shorter than official |
| **Response behavior** | JSON array of OMM objects; HTTPS; `application/json`. | Content-type validated; non-200 → unavailable; redirects rejected; size-capped; empty/missing array → schema error (no false "data"). | ✅ matches |
| **Catalogue numbers (5-digit / expanded / Alpha-5)** | NORAD numbers are migrating beyond 5 digits; Alpha-5 (alphanumeric 5-char) encodes > 99,999 in TLE line 1. | `CATNR` accepts `^\d{1,9}$` (covers expanded **numeric** ids). **Alpha-5 alphanumeric designators are not yet accepted** (a documented limitation; `sgp4.alpha5` exists for a future enhancement). | ⚠️ partial — numeric only |
| **Schema assumptions** | OMM/GP JSON object set. | First array element validated; unknown keys ignored; core elements required; normalization failure → `SourceSchemaError`. | ✅ documented |
| **Attribution** | Attribution to CelesTrak expected. | Policy records attribution "Orbital data courtesy of CelesTrak (https://celestrak.org)." | ✅ recorded |

## Outcome
- **Technical endpoint/format/cadence verification:** supported → **R-012a closed
  (mitigated)**. The minimum polling interval was corrected to honor the official
  2-hour guidance.
- **Legal/commercial-use rights:** **NOT** established by the official GP-data
  documentation reviewed here → **R-012b remains open**; the policy keeps
  `requires_review=true`, `commercial_use_confirmed=false`.
- **Known limitation:** Alpha-5 / alphanumeric catalogue designators are not yet
  supported by the request validation (numeric ids only). Tracked as a future,
  non-blocking enhancement; not in Phase 2 scope.

Network remains **disabled by default** (ADR-0009); no behavior here enables it.
