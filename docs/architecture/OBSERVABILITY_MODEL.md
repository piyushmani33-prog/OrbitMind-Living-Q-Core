# Observability Model — OrbitMind Living Q-Core

## Logging
- Structured logging via `structlog` (falls back cleanly to stdlib logging config).
- Key/value events, not free-form strings. JSON output toggled by
  `ORBITMIND_LOG_JSON`.
- Mission-scoped logs carry a `mission_id` field for correlation (NFR-10).
- Logs never contain secrets, full request bodies with sensitive data, or
  environment dumps (SR-15/17).

## Health & readiness
`GET /health` reports (NFR-12):
- `status` — ok/degraded
- `version` — app version
- `python_version`
- `database` — connectivity (SELECT 1)
- `execution_mode` — local
- `quantum` — available/unavailable (cheap import check, cached)

`GET /version` returns app + key library versions.
`GET /api/v1/system/capabilities` lists `CapabilityRecord`s (orbital propagation,
verification, visualization, persistence, quantum-adapter availability).

## Audit trail
Append-only `audit_events` capture every mission lifecycle transition (NFR-11).
Audit is a first-class governance feature, queryable per mission.

## Metrics & tracing (planned)
- OpenTelemetry traces/metrics and dashboards/alerts are a Phase 8 concern.
- For now, the deterministic step log inside `WorkflowRun.steps` provides a
  lightweight per-mission timing/trace substitute.

## Cost observability
No paid resources in Phase 0/1, so cost = $0. A `cost_event` concept is reserved
for when external/paid services are introduced (Phase 2+).
