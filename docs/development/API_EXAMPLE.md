# API Example — Orbit Propagation Mission

A complete request/response for the Phase 1 vertical slice. Captured from the
running application against the bundled ISS sample TLE (offline).

## Request

`POST /api/v1/missions/orbit-propagation`

```json
{
  "satellite_id": "ISS",
  "start_time": "2019-12-09T17:00:00Z",
  "end_time": "2019-12-09T18:00:00Z",
  "step_seconds": 600
}
```

Optional fields: `observer_latitude`, `observer_longitude`, `observer_altitude_km`,
and `output_types` (defaults to `["altitude_vs_time", "ground_track"]`).

## Response — `201 Created` (`MissionDetailResponse`, trimmed)

```json
{
  "mission_id": "ea1547ed-d71e-4114-b0d0-8db59f1771a1",
  "satellite_id": "ISS",
  "status": "completed",
  "epistemic_status": "deterministic-calculation",
  "created_at": "2026-06-19T05:08:54.327826Z",
  "completed_at": "2026-06-19T05:08:55.041807Z",
  "request": {
    "satellite_id": "ISS",
    "start_time": "2019-12-09T17:00:00Z",
    "end_time": "2019-12-09T18:00:00Z",
    "step_seconds": 600,
    "observer": null,
    "output_types": ["altitude_vs_time", "ground_track"]
  },
  "disclaimer": "Results are derived from bundled, stale sample TLE data for demonstration only. They are a deterministic calculation, NOT live satellite tracking data.",
  "source": {
    "satellite_id": "ISS",
    "name": "ISS (ZARYA)",
    "norad_cat_id": 25544,
    "source_name": "python-sgp4 reference example (Vallado test vector)",
    "epoch_utc": "2019-12-09T16:38:29Z",
    "checksum": "e20e7db3f19c0ebb5c2d2a10a425fa8440b61452773f35b4ba19c47184576214",
    "test_only": true,
    "epistemic_status": "assumption"
  },
  "units": {
    "position": "km (TEME)",
    "velocity": "km/s (TEME)",
    "latitude": "degrees (geodetic, WGS-84)",
    "longitude": "degrees (geodetic, WGS-84)",
    "altitude": "km (above WGS-84 ellipsoid)",
    "time": "UTC (timezone-aware ISO-8601)"
  },
  "summary": {
    "sample_count": 7.0,
    "ok_count": 7.0,
    "error_count": 0.0,
    "altitude_min_km": 411.45,
    "altitude_max_km": 436.08,
    "altitude_mean_km": 423.33
  },
  "sample_count": 7,
  "samples": [
    {
      "timestamp": "2019-12-09T17:00:00Z",
      "position_km": { "x": 5520.63, "y": 3920.77, "z": -634.62 },
      "velocity_kmps": { "x": -3.2115, "y": 3.5691, "z": -5.9630 },
      "latitude_deg": -5.3879,
      "longitude_deg": 62.2324,
      "altitude_km": 422.97,
      "status": "ok",
      "error": null
    }
  ],
  "findings": [
    { "check_id": "timestamps_utc", "severity": "critical", "status": "passed", "explanation": "all timestamps are timezone-aware", "values": { "naive_indices": [] } },
    { "check_id": "monotonic_times", "severity": "error", "status": "passed", "explanation": "sample times strictly increase", "values": { "count": 7 } }
  ],
  "provenance": [
    {
      "subject_ref": "scientific_result",
      "source_ref": "python-sgp4 reference example (Vallado test vector) [ISS]",
      "method": "sgp4-propagation",
      "inputs_hash": "…sha256…",
      "evidence": [
        { "kind": "tle-fixture", "locator": "data/samples/iss_zarya.tle", "description": "ISS (ZARYA) (test-only sample, sha256=e20e7db3f19c…)" }
      ]
    }
  ],
  "artifacts": [
    { "type": "altitude_vs_time", "path": "ea1547ed-…/altitude_vs_time.png", "checksum": "…", "sidecar_path": "ea1547ed-…/altitude_vs_time.json" },
    { "type": "ground_track",     "path": "ea1547ed-…/ground_track.png",     "checksum": "…", "sidecar_path": "ea1547ed-…/ground_track.json" }
  ],
  "audit": [
    { "action": "mission.submitted" },
    { "action": "mission.validated" },
    { "action": "workflow.started" },
    { "action": "propagation.completed" },
    { "action": "verification.completed" },
    { "action": "artifact.generated" },
    { "action": "artifact.generated" },
    { "action": "mission.completed" }
  ]
}
```

## Retrieve later

```
GET  /api/v1/missions/{mission_id}             # full detail (as above)
GET  /api/v1/missions                          # paginated list (?limit&offset)
GET  /api/v1/missions/{mission_id}/artifacts   # artifact metadata only
GET  /api/v1/visual-manifests/mission/{mission_id}
```

The visual manifest endpoint is an additional read-only projection, not a
replacement for `GET /api/v1/missions/{mission_id}/artifacts`. Mission visual
manifest v1 is DB-only, path-free, sidecar-free, and non-authoritative. It is
not live tracking, operational access, approval, a signed receipt,
certification, taskability, command readiness, or quantum authority.

Response shape (`MissionVisualManifestResponse`, trimmed):

```json
{
  "schema_version": "visual-manifest-v1",
  "manifest_id": "visual-manifest:mission:ea1547ed-d71e-4114-b0d0-8db59f1771a1:v1",
  "read_at": "2026-07-02T06:04:46.689473Z",
  "source_domain": "mission",
  "scope_id": "ea1547ed-d71e-4114-b0d0-8db59f1771a1",
  "items": [
    {
      "item_id": "artifact-1",
      "item_type": "altitude_vs_time",
      "media_type": "image/png",
      "artifact_handle": "mission-artifact:artifact-1",
      "checksum_handle": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "source_record_handles": [
        "mission:ea1547ed-d71e-4114-b0d0-8db59f1771a1"
      ],
      "canonical_epistemic_status": "deterministic-calculation",
      "verification_state": "mission-verification-passed",
      "source_labels": ["mission-source:sample", "test-only:true"],
      "limitations": [
        "Artifact handles and checksum handles are persisted metadata only; sidecar scientific context, artifact-byte verification, and file checksum re-authentication are deferred to a future reviewed slice."
      ],
      "disclaimers": [
        "This item is a path-free DB-backed artifact metadata projection, not artifact file authentication."
      ],
      "presentation_hints": {
        "visual_role": "mission-artifact",
        "display_label": "altitude vs time",
        "scientific_authority": "none-added"
      }
    }
  ],
  "limitations": [
    "Phase 5.4 mission v1 uses persisted database records only; it does not read sidecar JSON or image files, and it does not recompute file checksums.",
    "manifest_id is a non-authoritative discovery/index identifier, not a receipt id, attestation id, signature id, approval id, or certification id."
  ],
  "disclaimer": "This visual manifest is a read-only discovery/index projection over persisted mission and artifact metadata. It is not verification by itself, not live tracking, not operational access, not taskability, not command readiness, not approval, not a signed receipt, not certification, and not quantum authority."
}
```

## Error responses (safe, no internals)

| Situation | Status | Body |
|-----------|--------|------|
| Unsupported satellite id | 422 | `{"code":"validation_error","message":"unsupported satellite identifier"}` |
| `end_time` ≤ `start_time` | 422 | FastAPI request-validation detail |
| Unknown / malformed mission id | 404 / 422 | `{"code":"not_found", ...}` / validation detail |
