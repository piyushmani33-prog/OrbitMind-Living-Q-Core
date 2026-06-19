# Data Model — OrbitMind Living Q-Core (persistence)

SQLAlchemy 2.0 ORM models, SQLite locally (PostgreSQL is the production target —
ADR-0003). All timestamps stored as timezone-aware UTC. Binary images are NOT
stored in the database — only artifact metadata + filesystem paths.

## Tables (Phase 1)

```
missions
  id              TEXT(uuid)  PK
  satellite_id    TEXT
  status          TEXT        -- received|validated|running|completed|failed
  raw_request     JSON        -- preserved raw input (SR-03)
  normalized_request JSON     -- normalized/validated input
  created_at      TIMESTAMPTZ
  completed_at    TIMESTAMPTZ NULL
  epistemic_status TEXT

mission_inputs
  id              TEXT(uuid)  PK
  mission_id      TEXT  FK -> missions.id
  key             TEXT
  value           JSON

workflow_runs
  id              TEXT(uuid)  PK
  mission_id      TEXT  FK -> missions.id
  workflow_name   TEXT
  status          TEXT
  steps           JSON        -- ordered step log
  started_at      TIMESTAMPTZ
  finished_at     TIMESTAMPTZ NULL

orbital_samples
  id              TEXT(uuid)  PK
  mission_id      TEXT  FK -> missions.id
  ts              TIMESTAMPTZ
  pos_x_km        FLOAT
  pos_y_km        FLOAT
  pos_z_km        FLOAT
  vel_x_kmps      FLOAT
  vel_y_kmps      FLOAT
  vel_z_kmps      FLOAT
  lat_deg         FLOAT
  lon_deg         FLOAT
  alt_km          FLOAT
  status          TEXT        -- ok|error
  error           TEXT NULL

verification_findings
  id              TEXT(uuid)  PK
  mission_id      TEXT  FK -> missions.id
  check_id        TEXT
  severity        TEXT        -- info|warning|error|critical
  status          TEXT        -- passed|failed|skipped
  explanation     TEXT
  values          JSON

provenance_records
  id              TEXT(uuid)  PK
  mission_id      TEXT  FK -> missions.id
  subject_ref     TEXT
  source_ref      TEXT
  method          TEXT
  inputs_hash     TEXT
  generated_at    TIMESTAMPTZ

artifact_records
  id              TEXT(uuid)  PK
  mission_id      TEXT  FK -> missions.id
  type            TEXT        -- altitude_vs_time|ground_track
  path            TEXT        -- relative to artifacts dir
  sidecar_path    TEXT
  checksum        TEXT        -- sha256 of image
  created_at      TIMESTAMPTZ

audit_events
  id              TEXT(uuid)  PK
  mission_id      TEXT NULL  FK -> missions.id
  action          TEXT
  actor           TEXT
  detail          JSON
  at              TIMESTAMPTZ
```

## Indexing
- `missions.created_at`, `*_records.mission_id`, `orbital_samples(mission_id, ts)`.

## Migrations
Managed by Alembic. The initial migration creates all Phase 1 tables. Tests run
against a temporary SQLite database created from the same metadata to guarantee
parity. PostgreSQL migration adds JSONB + GIN indexes where useful (Phase 8).

## Authoritative vs derived
`missions.raw_request` is the authoritative untouched input. `orbital_samples`
are derived deterministic computations. `audit_events` are append-only and never
updated.
