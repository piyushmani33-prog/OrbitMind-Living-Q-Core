# Unified Space-Object Model

A kind-agnostic representation of space objects that preserves — rather than collapses —
the scientific differences between object classes (ADR-0013, ADR-0016).

## Object kinds (`SpaceObjectKind`)
15 kinds are modelled for future compatibility; **only `asteroid` and `comet` are
implemented** in Phase 3A (`IMPLEMENTED_KINDS`). The rest exist as types but have no
data/normalization yet and must not pretend otherwise:

`artificial-satellite` (SGP4, Phase 1/2) · `rocket-body` · `space-debris` ·
**`asteroid`** · **`comet`** · `meteoroid` · `dwarf-planet` · `planet` · `moon` ·
`star` · `exoplanet` · `galaxy` · `radio-source` · `transient-event` ·
`unknown-candidate`.

## Identity (no flat `satellite_id`)
`SpaceObject` carries a structured `SpaceObjectIdentity`:
- `kind`, `canonical_name`
- `primary_identifier` (`CatalogIdentifier`: catalog + identifier, e.g. `jpl-spk`)
- `designation`, `number` (when applicable), `aliases` (`ObjectAlias[]`)
- `classifications` (`ObjectClassification[]`, e.g. orbit class)
- optional `DiscoveryRecord`

…plus provenance (`SourceReference`), `freshness` (reused `SourceFreshnessAssessment`),
`epistemic_status`, `verification_status` (`ObjectVerificationStatus`), `limitations`,
and an internal UUID. There is deliberately **no single `satellite_id`** for every
object.

## Orbit representation is a tagged union (`OrbitRepresentation`)
Each class keeps its own representation, discriminated by `representation`:

| Representation | Class | Status |
|----------------|-------|--------|
| `EarthOrbitElements` (`earth-orbit-tle`) | satellites/debris | implemented (SGP4) |
| `SmallBodyOrbitElements` (`small-body-heliocentric`) | asteroids/comets | implemented |
| `PlanetaryEphemerisReference` | planets/moons | future |
| `FixedSkyCoordinateReference` | stars/galaxies | future |
| `SignalSourceReference` | signals | future |

`SmallBodyOrbitElements` has **no TLE fields**; `EarthOrbitElements` has **no
heliocentric fields**. Small bodies are **never** sent through SGP4 and their elements
are **never** converted to synthetic TLEs.

## Persistence
`space_objects` (+ `space_object_identifiers`, `space_object_aliases`) hold the unified
identity/provenance; small-body specifics live in `small_body_orbits`,
`small_body_physical_properties`, `small_body_classifications`. All additive and
non-destructive (ADR-0003; migration `233729f6fa57`).

## How this supports future memory/retrieval (Phase 3B)
Every object has a stable UUID + canonical identity + provenance + epistemic/verification
status — the exact entity a knowledge graph references. Phase 3B can index/link objects
without reshaping existing data.
