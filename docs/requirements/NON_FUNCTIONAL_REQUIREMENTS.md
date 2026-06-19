# Non-Functional Requirements — OrbitMind Living Q-Core

Status: Living document · Phase 0/1 scope.

## 1. Reproducibility & determinism
- NFR-01 Orbital computation MUST be deterministic given identical inputs and the
  same `sgp4` version. No unseeded randomness in production paths.
- NFR-02 All datetimes MUST be timezone-aware UTC. The system MUST NOT depend on
  system local time.
- NFR-03 Relevant package and algorithm versions MUST be recorded in artifact
  sidecars and the `ScientificResult` (`computation_version`, `software_versions`).
- NFR-04 Sample fixtures and generated artifacts MUST carry SHA-256 checksums.

## 2. Performance (demonstration-scale targets, not SLAs)
- NFR-05 A 24h / 60s-step propagation (~1440 samples) SHOULD complete in < 2 s on
  a developer laptop.
- NFR-06 The propagation request is bounded: ≤ `MAX_PROPAGATION_HOURS`,
  step ∈ [`MIN_STEP_SECONDS`, `MAX_STEP_SECONDS`], total samples ≤ `MAX_SAMPLES`.

## 3. Reliability & recovery
- NFR-07 The repository MUST remain runnable after each phase.
- NFR-08 Failed propagation MUST be reported explicitly (status + finding), never
  silently dropped. Partial failures preserve successful samples and flag the rest.
- NFR-09 Persistence MUST be transactional per mission; a failed write MUST NOT
  leave a half-recorded mission visible as "completed".

## 4. Observability
- NFR-10 Structured logging (key/value) MUST be used; a `mission_id` correlation
  field MUST be attached to mission-scoped logs.
- NFR-11 Audit events MUST be recorded for the mission lifecycle transitions
  (submitted, validated, workflow started, propagation completed/failed,
  verification completed, artifact generated, mission completed/failed).
- NFR-12 `/health` MUST report app status, version, Python version, DB
  connectivity, execution mode, and quantum availability.

## 5. Maintainability & quality gates
- NFR-13 `ruff check`, `mypy src`, and `pytest` MUST pass before a phase is
  declared complete.
- NFR-14 Coverage MUST be measured (`--cov=orbitmind`); core domain/service code
  targets ≥ 80% line coverage.
- NFR-15 Public boundaries (API, domain, repository) MUST be typed; avoid untyped
  dicts at important boundaries.

## 6. Portability
- NFR-16 Production baseline interpreter is Python 3.12; local dev MAY run 3.14.4
  if the dependency set resolves (it does — see ADR-0002).
- NFR-17 Storage access MUST go through SQLAlchemy + repository interfaces so
  SQLite→PostgreSQL requires no domain-logic rewrite.
- NFR-18 The app MUST run from a single container using SQLite without Redis,
  Temporal, or PostgreSQL in Phase 0/1.

## 7. Cost
- NFR-19 No paid APIs, no cloud resources, no network calls in Phase 0/1.
