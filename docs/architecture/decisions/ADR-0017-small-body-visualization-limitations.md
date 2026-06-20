# ADR-0017 — Small-Body Visualization Limitations

- **Status:** Accepted (2026-06-20)

## Context
Phase 3A produces small-body visuals. These must NOT imply high-fidelity ephemeris
propagation (Horizons/N-body) or precision prediction.

## Decision
- Implement bounded artifacts (`visualization/smallbody_charts.py`):
  1. **close-approach distance vs date** (scatter of source-reported nominal distances),
  2. **orbital-parameter summary** (bar chart of source elements),
  3. *(optional)* a **2-D Keplerian orbit illustration** from `a, e`.
- Every artifact is labelled **`model-estimate`** and its sidecar + title state: it is
  **NOT Horizons ephemeris output**, perturbations and uncertainty are **not
  represented**, and it is **not a precision prediction**.
- The 2-D illustration documents its **coordinate assumptions** (heliocentric orbital
  plane; Sun at a focus; perihelion along +x; no inclination/node rotation; no
  perturbations). It is only drawn for closed elliptical orbits (`0 ≤ e < 1`, `a > 0`).
- Sidecars record source, object id, timestamps, data epoch, fetch time, freshness,
  algorithm version, epistemic status, verification summary, checksum, and limitations.
  Artifacts are written under `artifacts/<scope-id>/` (path-traversal guarded).

## Alternatives considered
1. **Render a propagated ephemeris track.** Would imply precision we do not compute and
   risks being mistaken for a prediction. Rejected (Horizons deferred).

## Consequences
- Useful, honest visuals with no overclaiming; binary images never stored in the DB.

## Review trigger
Revisit when Horizons ephemerides are added (a later phase), enabling true propagated
tracks with explicit uncertainty.
