# Deployment Architecture — OrbitMind Living Q-Core

## Phase 0/1 (local)
- Single Python process: `uvicorn orbitmind.api.app:app`.
- SQLite database file (default `./data/orbitmind.db`).
- Artifacts on local filesystem under `./artifacts/<mission_id>/`.
- No Redis, no Temporal, no PostgreSQL, no cloud (by decision, ADR-0003/0004).

## Container (development convenience)
- `Dockerfile`: slim, production-oriented image running uvicorn; uses SQLite by
  default; installs only Phase 0/1 dependencies.
- `compose.yaml`: single `api` service for local convenience. It does **not** spin
  up Postgres/Redis. A commented `db` service shows how PostgreSQL is added later.
- Containers are not started automatically; only on explicit request/verification.

## Path to production (documented, not implemented)
```
Local SQLite  ─▶  PostgreSQL (managed)        # ADR-0003, Phase 8
In-proc workflow ─▶ Temporal (durable)        # ADR-0004
Local artifacts  ─▶ Object storage (versioned)# Phase 8
Single process   ─▶ Horizontally scaled API   # only if measured load requires
Static config    ─▶ Secrets manager + managed identity
Logs only        ─▶ OpenTelemetry traces/metrics + alerts
```

## Configuration surface
All deploy-time configuration flows through environment variables consumed by
`core.config.Settings` (see `.env.example`). The same image runs locally and (in a
future phase) in the cloud by swapping `ORBITMIND_DATABASE_URL` and related vars —
no code change.

## Cloud guardrail
Cloud deployment, managed databases, object storage, and secrets managers all
require **separate explicit owner approval** and are out of scope here.
