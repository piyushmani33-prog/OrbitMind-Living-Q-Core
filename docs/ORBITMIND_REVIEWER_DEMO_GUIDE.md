# OrbitMind Reviewer Demo Guide

This guide is the handoff path for a private OrbitMind reviewer demo. It is a
local, bounded review flow for the validated browser reviewer sandbox:

- `GET /review`
- `POST /review/run`
- `GET /review/artifacts/{mission_id}/{filename}`

It is not production deployment, not public alpha, not live tracking, not
provider/live-data validation, not command readiness, not approval or
certification, and not a quantum-advantage claim.

## Demo Scope

The reviewer demo shows one deterministic bundled offline sample:

- sample id: `iss`
- source: bundled stale sample/test-only ISS TLE
- execution mode: local API server
- output: generated evidence bundle with PNG artifacts, JSON sidecars,
  `static_report.json`, `static_report.md`, and checksums

The demo does not accept arbitrary orbital input, TLE files, URLs, uploads, live
provider data, or additional sample missions.

## Preconditions

- Project dependencies are installed in the local `.venv`.
- The working tree is clean or contains only the reviewed handoff changes.
- Alembic head is expected to be `n9c0d1e2f3g4`.
- No secrets, DB URLs, credentials, or stack traces should be pasted into public
  feedback.

## Start The Local API

From the repository root:

```bat
.venv\Scripts\python.exe -m alembic heads
.venv\Scripts\python.exe -m uvicorn orbitmind.api.app:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000/review
```

## Reviewer Flow

1. Confirm the entry page title is `OrbitMind Reviewer Sandbox`.
2. Confirm the subtitle says `Evidence-backed offline orbital sample`.
3. Confirm the sample info card lists sample id `iss`.
4. Confirm the safety boundary is visible before running anything.
5. Click `Run bundled ISS sample`.
6. Confirm the result page title is `OrbitMind Reviewer Sandbox Result`.
7. Confirm status badges show:
   - `completed`
   - `deterministic-calculation`
   - `test-only source: true`
8. Confirm the mission summary includes:
   - `mission_id`
   - `status`
   - `epistemic_status`
   - `sample_count`
   - `first_sample`
   - `last_sample`
9. Confirm the evidence/hash card includes:
   - `source_checksum`
   - `inputs_hash`
10. Confirm image previews load for:
    - `ground_track.png`
    - `altitude_vs_time.png`
11. Confirm report links open:
    - `static_report.md`
    - `static_report.json`
12. Confirm sidecar JSON links open:
    - `ground_track.json`
    - `altitude_vs_time.json`
13. Confirm the artifact checksum table is present.
14. Confirm the safety boundary remains visible on the result page.

## Expected Safety Boundary

The demo must clearly state:

- bundled stale sample/test-only data only
- not live tracking
- no provider fetch
- no command readiness, approval, or certification
- no quantum advantage claim
- not production/public-alpha workflow

## Artifact Serving Boundary

The reviewer sandbox serves only these exact artifact filenames through the
guarded route:

- `altitude_vs_time.png`
- `altitude_vs_time.json`
- `ground_track.png`
- `ground_track.json`
- `static_report.json`
- `static_report.md`

It does not expose directories, arbitrary filenames, arbitrary paths, uploads,
or the full artifacts tree.

## Stop Conditions

Stop the demo and report privately if any of these appear:

- unexpected HTTP 500
- traceback or stack detail in a browser response
- absolute local filesystem path in the page
- arbitrary file access or directory listing
- live tracking/provider-data claim
- command-readiness, approval, certification, or production-readiness claim
- quantum-authority or quantum-advantage claim
- missing safety boundary
- missing image previews or report links

## Reviewer Feedback

Useful feedback:

- Can the reviewer understand what was computed?
- Can the reviewer find the generated evidence bundle?
- Are the safety boundaries obvious?
- Is the result page credible as an evidence-first scientific workflow surface?
- Is anything confusing within the first five minutes?

Defer feedback about:

- public alpha
- dashboard expansion
- arbitrary mission input
- live provider integration
- upload/file/URL input
- frontend framework work
- export/PDF generation
- quantum/optimization expansion

## Final Demo Verdict

The current reviewer demo handoff verdict is:

**Ready for reviewer demo.**
