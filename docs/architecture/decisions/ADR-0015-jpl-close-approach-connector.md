# ADR-0015 — JPL Close-Approach Data Connector

- **Status:** Accepted (2026-06-20)

## Context
Phase 3A adds close-approach intelligence using JPL/CNEOS Close-Approach Data
(`cad.api`), an official JSON API returning column `fields` + row-major `data`.

## Decision
- Implement guarded `CadConnector` reusing the same safe-HTTP + cache pattern, gated by
  `jpl_cad_enabled` + the global switch.
- Expose an **OrbitMind-owned `CadQueryFilter`**: UTC-aware `date_min`/`date_max`,
  allowlisted approach `body`, optional `max_distance_au` (au only, bounded), NEO-only /
  PHA-only flags, bounded `limit`. The connector additionally enforces a **maximum date
  span** (`jpl_max_query_span_days`).
- Normalize to typed `CloseApproachRecord` (body, distance nominal/min/max, relative/
  infinity velocity, time, magnitude, source provenance, freshness).
- **Epistemic discipline (binding):** every result states it is **source-reported orbit
  solution data**, that uncertainty may exist, that **nominal distance is not a
  guarantee**, that a **close approach is NOT an impact**, and that hazard flags are
  **source-reported, not computed**. Stale records are never described as live.
- **No independent collision-probability calculation** is performed in this phase
  (Sentry/Scout/Sentry-II are explicitly deferred).

## Alternatives considered
1. **Compute our own impact probability.** Out of scope, scientifically hazardous to do
   naively, and explicitly excluded. Rejected.
2. **Return raw CAD rows.** Leaks upstream structure and lacks typing/provenance.
   Rejected.

## Consequences
- A bounded, honest close-approach capability with strong epistemic labelling.
- Close approaches persist (`close_approaches` + `small_body_query_runs`) and join to a
  stored object by designation.

## Review trigger
Revisit when adding Sentry/impact-risk data (a later phase) or when CAD's schema/units
change.
