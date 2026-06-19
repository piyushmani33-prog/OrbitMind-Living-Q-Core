# ADR-0002 — Python Version Policy

- **Status:** Accepted (2026-06-19)

## Context
The production baseline preferred by the specification is **Python 3.12** (mature,
broad wheel availability). The local environment ships **Python 3.14.4** in
`.venv`. The spec forbids silently changing Python versions or damaging the
working environment, and requires first testing whether the minimum Phase 0/1
dependencies work on the current interpreter.

## Decision
- Set `requires-python = ">=3.12"`; pin tooling `target-version`/`python_version`
  to `3.12` for ruff/mypy (the conservative baseline the code must satisfy).
- **Develop locally on the existing Python 3.14.4 venv**, because a dry-run +
  install confirmed all Phase 0/1 dependencies resolve as native **cp314 wheels**
  (pydantic-core 2.46.4, sgp4 2.25, SQLAlchemy 2.0.51, uvicorn extras, etc.).
- **Production baseline remains Python 3.12.** Do not create a separate 3.12 venv
  unless a dependency later fails on 3.14 *and* 3.12 is installed.

## Alternatives considered
1. **Immediately rebuild on 3.12.** Safer long-term but unnecessary now (deps work)
   and risks disturbing a working environment. Deferred to "only if needed".
2. **Adopt 3.14 as the production baseline.** Premature; 3.14 wheel coverage for
   the *full future* stack (Astropy, pandas, etc.) is not yet guaranteed. Rejected.

## Consequences
- Local dev and production may differ by minor version; code is written to the
  3.12 baseline (ruff/mypy enforce it), reducing drift risk.
- A compatibility failure on 3.14 for a future dependency triggers the documented
  fallback (create a 3.12 venv), not a silent change.

## Review trigger
Revisit when adding Phase 2+ dependencies (Astropy, pandas, pgvector drivers) or if
any tool/library fails to provide a working 3.14 wheel.
