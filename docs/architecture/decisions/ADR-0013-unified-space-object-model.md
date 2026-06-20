# ADR-0013 — Unified Space-Object Model

- **Status:** Accepted (2026-06-20)

## Context
OrbitMind must represent many object classes (satellites, debris, asteroids, comets,
planets, moons, stars, galaxies, signals). Forcing them into one propagation format
(e.g. TLE/SGP4) would be scientifically wrong: asteroids are not satellites.

## Decision
- Introduce a **kind-agnostic `SpaceObject`** (`objects/models.py`) carrying identity,
  provenance, freshness, epistemic + verification status, and limitations — but **no
  flat `satellite_id`**. Identity is structured (`SpaceObjectIdentity`,
  `CatalogIdentifier`, aliases, classifications).
- `SpaceObjectKind` enumerates **15** classes; only **asteroid** and **comet** are
  implemented this phase (`IMPLEMENTED_KINDS`). Other kinds are modelled for future
  compatibility and must not pretend to be implemented.
- Per-class orbit/position data is a **tagged union** (ADR-0016), not shared fields.

## Alternatives considered
1. **One "orbit" table with nullable TLE + Keplerian columns.** Collapses scientific
   differences and invites SGP4-on-asteroid mistakes. Rejected.
2. **Separate top-level models per kind with no unifying identity.** Loses the shared
   identity/provenance surface a future knowledge graph needs. Rejected.

## Consequences
- A stable identity/provenance shape that Phase 3B memory/retrieval can index.
- Slightly more types up front; future kinds slot in without reshaping existing data.
- The existing satellite (SGP4) path is untouched and keeps working.

## Review trigger
Revisit when adding a third object kind (e.g. planets/moons) or when Phase 3B
introduces the knowledge graph.
