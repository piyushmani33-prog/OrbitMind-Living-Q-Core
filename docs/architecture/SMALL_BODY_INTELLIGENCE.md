# Small-Body Intelligence (Phase 3A)

Asteroid/comet intelligence from official NASA/JPL Solar System Dynamics APIs, behind
the Phase 2 guarded-connector pattern. Network is **disabled by default**.

## What the system can identify
- Known **asteroids and comets** by approved identifier (designation/number/name) via
  JPL SBDB lookup → a normalized `SmallBodyRecord` (identity, heliocentric orbit,
  source-provided physical properties, classification, source hazard flags).
- **Sets** of small bodies via a constrained, allowlisted SBDB query (bounded, paginated,
  truncation-aware).
- **Close approaches** (object, date/time, nominal/min/max distance, relative velocity,
  approach body) via JPL/CNEOS CAD.

## What the system cannot observe or do (this phase)
- It does **not** observe directly — no telescope/optical/radar detection; it ingests
  catalogued solutions.
- It does **not** propagate high-fidelity ephemerides (Horizons/N-body) — deferred.
- It does **not** compute independent **impact probability** (Sentry/Scout deferred).
- It does **not** ingest the full catalogue (no bulk nightly downloads).

## Asteroid vs satellite (key differences)
| | Satellite/debris | Asteroid/comet |
|--|------------------|----------------|
| Frame | geocentric (Earth orbit) | heliocentric |
| Elements | TLE/GP | Keplerian (a, e, i, Ω, ω, M, …) |
| Propagator | **SGP4** | **never SGP4** (Phase 3A stores elements; no propagation) |
| Source | CelesTrak GP | JPL SBDB / CAD |

**SGP4 is never run on a small body** (enforced by the type system, ADR-0016).

## Source-data freshness
Freshness reflects how recently data was fetched from JPL (states `test-fixture /
current / fresh / aging / stale / expired / unavailable / invalid`). Stale/expired data
is **never** reported as live. Every result carries source, record id, data epoch, fetch
time, cache status, freshness, policy version, checksum, and limitations.

## Close approach ≠ impact
A close approach is a **source-reported** orbit-solution prediction with uncertainty.
Nominal distance is **not** a guarantee, and a close approach is **NOT** an impact. The
**hazard flags (NEO/PHA) are reported by JPL, not computed by OrbitMind** — OrbitMind
never infers "dangerous" from size or proximity.

## Epistemic status (how labels are used)
- `verified-fact`: source identity/metadata directly provided + preserved with
  provenance (subject to source limitations).
- `deterministic-calculation`: reproducible unit conversions/normalization of source data
  (the record-level status).
- `model-estimate`: source-provided estimated diameter, derived values, visualizations.
- `assumption`: OrbitMind-selected defaults. `unknown`: missing/unsupported.
- `rejected`: invalid/failed normalization. No arbitrary confidence percentages; a JPL
  prediction is never labelled guaranteed future truth.

## Why Horizons is deferred
Horizons provides high-precision ephemerides but is heavier (large state, different API
shape, stricter usage) and unnecessary for the bounded identify/close-approach slice.
It is scheduled for a later phase with explicit uncertainty handling.

## Why every stone cannot be individually tracked
Millions of small bodies exist, with heterogeneous, uncertainty-bearing solutions and
rate-limited sources. OrbitMind queries and caches **bounded** sets on demand with
provenance — it does not (and should not) mirror the entire catalogue.

## Fixture vs live mode
- **Default (offline):** all tests and default runs use bundled fixtures / cache; no
  network. A live JPL request requires **both** `ORBITMIND_NETWORK_ENABLED=true` and the
  source switch (`ORBITMIND_JPL_SBDB_ENABLED` / `ORBITMIND_JPL_CAD_ENABLED`).
- See `../operations/JPL_SOURCE_OPERATIONS.md`.

## Data-rights review status
NASA/JPL data is generally public domain, but exact redistribution/commercial terms and
rate limits are **not confirmed** here and are labelled **requires review**
(`requires_review=true`, `commercial_use_confirmed=false`). See
`DATA_RIGHTS_AND_SOURCE_POLICY.md` and the Risk Register.

## Known catalogue limitations
Orbit solutions carry uncertainty (condition code 0–9); short-arc objects are poorly
constrained; physical properties are estimates; Alpha-5/expanded designations are not
yet accepted (numeric/standard identifiers only). Validation proves only internal
consistency — **not** that an orbit is correct.
