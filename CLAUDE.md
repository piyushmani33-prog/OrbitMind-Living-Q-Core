# CLAUDE.md — Working guide for OrbitMind Living Q-Core

Guidance for AI/code assistants and contributors working in this repository.

## What this project is
A modular-monolith scientific intelligence platform. Phase 0/1 implements a
deterministic satellite/Earth-orbit vertical slice. Read `README.md` and
`docs/architecture/SYSTEM_ARCHITECTURE.md` before changing anything.

## Non-negotiable invariants
1. **System spine** (every feature connects to it):
   `Mission → Intake/Validation → Prime Orchestrator → Domain Workflow →
   Data/Tools/Sim/Quantum → Verification & Evidence → Structured & Visual Output →
   Memory Update → Evaluation → Human Approval (when required) → Improvement Proposal`.
2. **Deterministic tools do calculations; never an LLM** (SR-01).
3. **Epistemic labeling** on every major output (`governance.epistemic`). Never
   label generated text as `verified-fact`. No confidence % on deterministic calc.
4. **Provenance** preserved; sample TLE data is **not** live data (SR-05).
5. **UTC, timezone-aware** datetimes only; explicit units (`core.units`).
6. **Quantum is bounded** (ADR-0005): simulator-only, off the mission path, classical
   baseline required. The orbital slice must not import `orbitmind.quantum`.
7. **Generated code is untrusted**: no execution, no auto-promotion/-deploy.
8. **No secrets** in code/logs/VCS; **no hidden network calls**; artifacts stay
   under the artifacts root (path-traversal rejected).

## Module dependency rule
`api → orchestration → domain (mission/space/verification/visualization/governance)
→ persistence/sources → core`. `core` imports nothing internal. Domain modules must
not import `api`. See `docs/architecture/MODULE_BOUNDARIES.md`.

## Layer separation
- **API schemas** (`api/schemas.py`) ≠ **domain models** (Pydantic in each module)
  ≠ **ORM models** (`persistence/models.py`). Keep them separate; avoid untyped
  dicts at boundaries.
- Persistence goes through repository interfaces (`persistence/repositories.py`),
  so SQLite→PostgreSQL needs no domain change.

## Quality gates (must pass before declaring a step done)
```bash
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy src        # strict
.venv\Scripts\python -m pytest --cov=orbitmind --cov-report=term-missing
```
Never claim a test passed unless it actually ran; report exact results.

## Conventions
- Python 3.12 baseline (`ruff`/`mypy` target 3.12); dev runs on 3.14.4.
- `StrEnum` for string enums. Full type annotations (mypy strict).
- `pathlib` over `os.path`; structured logging via `structlog`.
- Tests are **offline**, deterministic, use temp dirs/DBs and fixed inputs.

## How to extend (pointers — see docs/development/DEVELOPMENT.md)
- **New module**: add under `src/orbitmind/<name>`, document boundary, respect the
  dependency rule, wire via `api/container.py`.
- **New source connector** (Phase 2): implement behind a `sources` interface with a
  source policy, license note, rate/cache/freshness policy, and **offline fixtures**.
- **New verification check**: add a method to `verification/checks.py` returning a
  `VerificationFinding`; never raise on bad data.
- **New artifact type**: add an `OutputType`, a render method in
  `visualization/charts.py`, and a sidecar; keep writes inside the artifacts root.

## Decision records
Significant decisions are ADRs in `docs/architecture/decisions/`. Add one (status,
context, decision, alternatives, consequences, review trigger) for any material
architectural change. Do not silently change an ADR's decision.

## Reference documents
The product vision docs are expected under `docs/reference/` but are currently
**absent** (tracked as risk R-001). This `CLAUDE.md` + the build spec are the
working source of truth until they arrive; reconcile against them when added.
