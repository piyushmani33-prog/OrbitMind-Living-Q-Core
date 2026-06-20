# ADR-0016 — Small-Body Orbit Representation

- **Status:** Accepted (2026-06-20)

## Context
Asteroids and comets are described by **heliocentric Keplerian elements**, not TLE/GP
sets. SGP4 is an Earth-orbit (geocentric, near-Earth) propagator and must never be
applied to small bodies.

## Decision
- Model orbit/position data as a **discriminated union** (`objects/orbits.py`,
  `OrbitRepresentation`) keyed by a `representation` field:
  - `EarthOrbitElements` (`earth-orbit-tle`) — satellites/debris (SGP4 path).
  - `SmallBodyOrbitElements` (`small-body-heliocentric`) — asteroids/comets.
  - `PlanetaryEphemerisReference`, `FixedSkyCoordinateReference`,
    `SignalSourceReference` — future kinds (modelled, not implemented).
- `SmallBodyOrbitElements` carries `epoch_jd, e, a, q, ad, i, om, w, ma, per, n, tp`
  with **explicit units** and **optional** fields (missing ⇒ `None`, never `0`). It has
  **no TLE fields**; `EarthOrbitElements` has **no heliocentric fields**.
- Small-body elements are **never** converted into synthetic TLEs, and the SGP4
  service is never called for small bodies.

## Alternatives considered
1. **Reuse the satellite TLE model with extra columns.** Invites SGP4-on-asteroid
   errors and conflates frames. Rejected.
2. **Synthesize TLEs from Keplerian elements.** Misrepresents heliocentric orbits as
   geocentric; scientifically wrong. Rejected.

## Consequences
- A type system that makes "run SGP4 on an asteroid" impossible by construction.
- The existing CelesTrak/sample-TLE workflows are untouched.

## Review trigger
Revisit when implementing planetary ephemerides (Horizons/SPICE) or fixed-sky catalogues.
