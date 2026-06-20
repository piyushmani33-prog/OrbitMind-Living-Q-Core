# OrbitMind Scientific Glossary (sample memory document)

This is a small, bundled sample document for the scientific-memory slice. It is
illustrative reference material, NOT live data and NOT a verified authority.

## Two-Line Element set

A Two-Line Element set (TLE) encodes the orbital elements of an Earth-orbiting
object at a given epoch. OrbitMind propagates TLEs deterministically with the SGP4
model. SGP4 is appropriate for near-Earth satellites such as the ISS (NORAD 25544)
and is never used for heliocentric small bodies such as asteroids and comets.

## Close approach

A close approach is a source-reported event in which a small body (for example the
comet 1P/Halley) passes near a planet within a stated distance (e.g. ≈ 0.05 au). A
close approach is NOT an impact. Hazard flags are reported by the source (JPL/CNEOS)
and are not computed by OrbitMind.

## Epistemic status

Every major output carries an epistemic status label such as deterministic-calculation,
model-estimate, or assumption. Generated text is never labelled as a verified fact.
Retrieval returns source-asserted evidence; retrieval is not verification.

## Provenance

Provenance records where data came from, when it was retrieved, and under what
source policy. Sample fixtures are explicitly marked as not live data.
