# Development Guide — OrbitMind Living Q-Core

## 1. Virtual environment

The repo ships with a `.venv` (Python 3.14.4 locally; production baseline 3.12).
To recreate it:

```bash
py -3.12 -m venv .venv          # or your interpreter; 3.12+ required
.venv\Scripts\python -m pip install --upgrade pip
```

## 2. Install dependencies

```bash
.venv\Scripts\python -m pip install -e ".[dev]"      # runtime + dev tooling
.venv\Scripts\python -m pip install -e ".[quantum]"  # optional Qiskit adapter
```

Only Phase 0/1 dependencies are declared in `pyproject.toml`. Do not add the full
future stack (Redis, Temporal, pgvector, pandas, Astropy, …) without an ADR.

## 3. Configuration

```bash
cp .env.example .env
```

`.env` is gitignored. Settings are read only by `orbitmind.core.config.Settings`
(env prefix `ORBITMIND_`). No secrets in `.env.example`.

## 4. Database migrations

SQLite locally; PostgreSQL is the production target (ADR-0003).

```bash
.venv\Scripts\alembic upgrade head                       # apply migrations
.venv\Scripts\alembic revision --autogenerate -m "msg"   # after model changes
```

For custom column types (e.g., `UTCDateTime`) ensure the generated migration
imports `orbitmind.persistence.database`.

## 5. Run the API

```bash
.venv\Scripts\python -m uvicorn orbitmind.api.app:app --reload --port 8000
# http://127.0.0.1:8000/docs
```

The app also runs `create_all()` on startup as a dev convenience, so it works even
before you run Alembic.

## 6. Run tests

```bash
.venv\Scripts\python -m pytest --cov=orbitmind --cov-report=term-missing
.venv\Scripts\python -m pytest -m "not quantum"   # skip the optional Qiskit test
```

Tests are offline, deterministic, and use temp dirs/DBs.

## 7. Code-quality checks

```bash
.venv\Scripts\python -m ruff check .      # lint (and `--fix` to auto-fix)
.venv\Scripts\python -m ruff format .     # formatting
.venv\Scripts\python -m mypy src          # strict type checking
.venv\Scripts\pre-commit run --all-files  # all hooks
```

All three gates (ruff, mypy, pytest) must pass before a phase is "done".

## 8. Adding a new module

1. Create `src/orbitmind/<name>/` with typed public interfaces.
2. Respect the dependency rule: `api → orchestration → domain → persistence → core`.
   Domain modules must not import `api`; the orbital slice must not import `quantum`.
3. Document it in `docs/architecture/MODULE_BOUNDARIES.md`.
4. Wire dependencies via `orbitmind/api/container.py`.
5. Add unit tests; keep coverage up.

## 9. Adding a new source connector (Phase 2 pattern)

Implement behind a `sources` interface. Each connector must ship:
source policy, licensing note, rate limits, cache policy, freshness policy, schema
versioning, failure behavior, and **offline test fixtures**. Live calls must never
be required for tests.

## 10. Adding a new verification check

Add a `@staticmethod` to `VerificationService` in
`orbitmind/verification/checks.py` returning a `VerificationFinding`
(`check_id`, `severity`, `status`, `explanation`, `values`). It must **never raise**
on bad data — record a failed finding instead (SR-08). Register it in `verify()`.

## 11. Adding a new artifact type

1. Add a value to `OutputType` (`orbitmind/mission/models.py`).
2. Add a render method in `orbitmind/visualization/charts.py` and dispatch to it.
3. Emit a JSON sidecar with the standard metadata + checksum.
4. Keep all writes inside the artifacts root (the path guard enforces this).

## 12. Conventions
- `StrEnum` for string enums; full type annotations (mypy strict).
- `pathlib` over `os.path`; UTC tz-aware datetimes; explicit units.
- Structured logging via `structlog`; attach `mission_id` for mission-scoped logs.
- Record significant decisions as ADRs in `docs/architecture/decisions/`.
