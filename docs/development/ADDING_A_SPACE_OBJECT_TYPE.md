# Adding a Space-Object Type

How to add a new `SpaceObjectKind` (e.g. planet, star) without collapsing scientific
differences (ADR-0013/0016). Asteroid/comet is the reference implementation.

## Principles
- A new kind keeps its **own orbit/position representation** — do not reuse TLE/GP for
  non-Earth-orbit objects, and never run SGP4 on a non-satellite.
- Reuse the unified `SpaceObject`/`SpaceObjectIdentity` for identity + provenance.
- Implemented kinds go in `IMPLEMENTED_KINDS`; unimplemented kinds stay modelled-only.

## Steps
1. **Kind:** confirm the value exists in `SpaceObjectKind` (`objects/models.py`); add it
   to `IMPLEMENTED_KINDS` only once data + normalization exist.
2. **Representation:** add a typed variant to `OrbitRepresentation`
   (`objects/orbits.py`) with a unique `representation` discriminator and explicit units;
   missing values are `None`, never `0`. Do not add fields from other representations.
3. **Domain model:** add a `<Kind>Record` (like `SmallBodyRecord`) embedding the
   identity + the new representation + source-specific structured data + provenance +
   epistemic/verification status + limitations.
4. **Source + normalization:** add a guarded connector (see
   `ADDING_A_JPL_CONNECTOR.md`) producing the new representation; keep source response
   models isolated.
5. **Verification:** add deterministic checks (category structure/mathematics/
   provenance/policy) returning `VerificationFinding`s; never raise on bad data.
6. **Persistence:** add additive tables + a migration (no destructive renames); preserve
   provenance, freshness, checksum, schema/normalization version, epistemic + verification
   status.
7. **API:** expose narrow endpoints; return normalized/stored views (never raw source
   structures, URLs, paths, or stack traces).
8. **Visualization (optional):** label model-estimate outputs and document assumptions
   (ADR-0017).
9. **Docs + ADR + Risk Register + tests** (offline, mocked HTTP, no real network).

## Quality gates
`ruff check .`, `ruff format --check .`, `mypy src`, `pytest --cov=orbitmind` must pass;
maintain meaningful coverage. Do not lower strictness.
