# ADR-0012 — Phase 3 Small-Body Priority (re-sequencing)

- **Status:** Accepted (2026-06-20)
- **Owner decision:** Pre-approved in the Phase 3A build specification.

## Context
The prior roadmap (and the reference documents) place **scientific memory +
PostgreSQL** as the natural next phase (Phase 3). The owner has chosen to prioritize
**natural-space-object intelligence** (asteroids/comets via JPL) first, splitting
Phase 3 into **3A (this phase)** and **3B (memory + PostgreSQL)**.

## Decision
- Implement **Phase 3A — unified space-object model + JPL small-body intelligence**
  before broad scientific memory.
- Defer **Phase 3B — scientific memory + PostgreSQL** (not cancelled, just resequenced).
- Keep **SQLite** for Phase 3A (additive tables, repository interfaces unchanged).

### Why small-body first
- It directly extends the **first production mission** (Earth-and-space intelligence):
  the same user who asks about satellites asks about near-Earth asteroids and close
  approaches. It is a coherent, bounded, high-value increment.
- It is achievable against **official machine-readable JPL APIs** with the same
  guarded-connector pattern already proven in Phase 2 (network-off-by-default,
  cache/freshness/rights), so risk is low.
- It forces the **unified object model** early — the right time to establish that
  satellites, asteroids, planets, stars, and signals use **different** representations,
  which is exactly the foundation a future memory/knowledge graph needs.

### Why SQLite remains acceptable here
- Phase 3A is a bounded, **local, single-user, offline-by-default** slice with modest
  data volumes (per-object records + bounded query/CAD result sets; no bulk catalogue
  ingestion). SQLite via SQLAlchemy + repository interfaces is sufficient (ADR-0003).
- No concurrent-writer, full-text, or vector-search requirement exists yet — those
  are the triggers for PostgreSQL/pgvector, and they belong to Phase 3B.

### Why PostgreSQL + scientific memory remain planned
- The references are explicit that Postgres + pgvector + a concept/claim/evidence
  schema are required for memory/retrieval at scale. That decision (ADR-0003) is
  unchanged; only its **timing** moves to Phase 3B.

### How the object model supports future memory/retrieval
- `SpaceObject`/`SpaceObjectIdentity` give every object a stable internal UUID,
  canonical name, catalogue identifiers, aliases, classifications, provenance,
  freshness, and epistemic/verification status — the exact entity shape a knowledge
  graph will reference. Small-body records attach typed orbit/physical/classification
  data behind that identity, so Phase 3B can index and link them without reshaping.

## Consequences
- The roadmap is updated **transparently** (not erased): Phase 3A → Phase 3B → later.
- A second SQLite→PostgreSQL migration surface is added (more tables to port in 3B),
  but the repository-interface design keeps that change mechanical.

## Review trigger
Revisit at the start of Phase 3B, or if data volume / concurrency / retrieval needs
arrive earlier than expected.
