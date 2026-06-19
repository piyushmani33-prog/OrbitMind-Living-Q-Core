# Domain Model — OrbitMind Living Q-Core

Typed domain entities (Pydantic models in `core`/`mission`/`space`/`verification`/
`governance`). API models, domain models, and DB models are kept separate; this
document describes the **domain** layer.

## Core entities (Phase 1)

| Entity | Key fields | Notes |
|--------|-----------|-------|
| `MissionRequest` | satellite_id, start/end (UTC), step_seconds, observer lat/lon/alt?, output_types[] | Validated; carries `raw` + normalized form. |
| `Mission` | id (UUID), request, status, created_at, completed_at? | Aggregate root. |
| `MissionStatus` | enum: received, validated, running, completed, failed | Lifecycle. |
| `WorkflowRun` | id, mission_id, workflow_name, steps[], status, started/finished | Deterministic step log. |
| `OrbitalSourceRecord` | name, identifier, origin, fetched_at, license_note, checksum, test_only | Provenance of TLE fixture. |
| `OrbitalStateSample` | timestamp(UTC), position_km(x,y,z TEME), velocity_kmps, lat_deg, lon_deg, alt_km, status, units | One propagated step. |
| `ScientificResult` | mission_id, samples[], computation_version, software_versions, summary, epistemic_status | Result aggregate. |
| `VerificationFinding` | check_id, severity, status, explanation, values{} | One deterministic check. |
| `ProvenanceRecord` | subject_ref, source_ref, method, generated_at, inputs_hash | Claim-level provenance. |
| `EvidenceReference` | kind, locator, description | Pointer to supporting evidence/fixture. |
| `ArtifactRecord` | id, mission_id, type, path, checksum, sidecar_path, created_at | Visual artifact metadata (binary NOT in DB). |
| `AuditEvent` | id, mission_id?, action, actor, at(UTC), detail{} | Append-only audit. |
| `CapabilityRecord` | name, available, detail | For `/system/capabilities`. |
| `QuantumExperimentRecord` | id, name, backend, shots, classical_baseline_ref, result_summary | Modeled; not produced by the slice. |
| `ApprovalRecord` | id, subject_ref, requested_by, status, decided_by?, decided_at? | Human-approval boundary (modeled). |

## Epistemic status (ADR-0006)
`verified-fact | deterministic-calculation | model-estimate | hypothesis |
assumption | unknown | rejected`.

Orbital positions from SGP4 are **deterministic-calculation** (a model estimate of
reality, but a deterministic computation given the TLE). The underlying TLE is an
**assumption/model-estimate** input (it is sample data, not live truth).

## Separation of authoritative facts vs interpretations
- *Authoritative input*: the bundled TLE fixture and its `OrbitalSourceRecord`.
- *Deterministic computation*: `OrbitalStateSample` values (reproducible from TLE).
- *Interpretation*: any natural-language summary — labeled, never "verified-fact".
