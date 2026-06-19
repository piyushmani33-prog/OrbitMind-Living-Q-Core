# ADR-0007 — First Orbital Vertical Slice

- **Status:** Accepted (2026-06-19)

## Context
Phase 1 must deliver one end-to-end vertical slice of the first production mission
(satellite/Earth-orbit intelligence) that is fully offline, deterministic, and
testable, exercising the entire system spine.

## Decision
Implement: submit a structured orbit-propagation mission → validate → load a
**bundled deterministic sample TLE** → propagate with **SGP4** over a bounded UTC
window → compute position/velocity/lat/lon/altitude → run deterministic
verification → label epistemic status → persist (mission, inputs, samples,
findings, provenance, artifacts, audit) → generate **two** artifacts
(altitude-vs-time, ground-track) with JSON sidecars → return a typed response with
provenance → expose retrieval endpoints. All tests run offline.

### Library choice: `sgp4`
Use the lightweight **`sgp4`** library (pure propagation from TLE) rather than the
heavier **Skyfield/Astropy** stack. Rationale: smallest dependency that correctly
performs the required TEME propagation; geodetic lat/lon/alt is derived with a
small, documented WGS-84 transform in `space`. This honors the minimal-dependency
policy.

## Alternatives considered
1. **Skyfield.** Higher-level, convenient, but pulls a larger dependency surface
   than needed for propagation-only. Deferred (may revisit for precise frames).
2. **Astropy-based frames.** Powerful but heavy; explicitly discouraged for now.
   Rejected for Phase 1.
3. **Live TLE fetch (CelesTrak).** Violates the offline-test requirement. Deferred
   to Phase 2 behind a connector interface with offline fixtures.

## Consequences
- Deterministic, offline, fast slice that fully traverses the spine.
- TEME→geodetic transform is implemented locally and unit-tested against reference
  values; precise frame conversions (precession/nutation) are out of scope and
  noted as a limitation.

## Review trigger
Revisit when sub-km frame precision is required, or when Phase 2 introduces live
TLE sources.
