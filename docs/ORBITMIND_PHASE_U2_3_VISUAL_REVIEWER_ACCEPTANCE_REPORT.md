# OrbitMind Phase U2.3 — Visual Reviewer Acceptance & Handoff QA

Acceptance QA for the Phase U2.2 visual reviewer surface (`/review`,
`/review/run`, `/review/artifacts/...`). This is a QA/handoff record, not a
feature phase. It makes no production, public-alpha, live-tracking, or
quantum-advantage claim.

## Environment

- Repo root: project root; local `.venv`, fully offline.
- Branch: `phase/u2-2-visual-reviewer-surface`. The U2.2 visual surface is in the
  working tree (uncommitted `M`) on top of the merged U2.1 sandbox
  (base = PR #68 merge, `64165c7`).
- Alembic head: `m8b9c0d1e2f3` (unchanged — no migration).
- App booted in-process via `TestClient(create_app(container))` with a disposable
  temp SQLite DB and temp artifacts dir; provider/network/quantum disabled in the
  sample settings.

## Files reviewed

- `src/orbitmind/api/routers/review.py` (U2.2 visual surface; artifact route)
- `tests/test_reviewer_sandbox.py`
- `src/orbitmind/api/app.py` (router registration — minimal, unchanged from U2.1)
- `README.md` — "Browser reviewer sandbox" section (unchanged from U2.1)

## Commands run

```text
python -m ruff check .
python -m ruff format --check .
python -m mypy src --show-error-codes --no-incremental
python -m pytest tests/test_sample_runner.py tests/test_architecture_boundaries.py \
    tests/test_reviewer_sandbox.py
python -m alembic heads
git diff --check
# plus an in-process acceptance harness (TestClient) exercising the routes,
# path-traversal/unknown/invalid-id attacks, and two-run determinism.
```

## /review result

- `GET /review` → **200**. Server-rendered HTML with **inline CSS only** — no
  `<script>`, no JavaScript, no external/CDN resources, no build step, no new
  dependency.
- Contains the "OrbitMind Reviewer Sandbox" title, the "Run bundled ISS sample"
  button, the available sample id `iss`, and the full safety boundary
  (sample/test-only, not live tracking, no provider fetch, no command
  readiness/approval/certification, no quantum advantage, not production/
  public-alpha).
- No absolute filesystem path appears in the HTML.

## /review/run result

- `POST /review/run` → **200**. Takes **no request body or parameters**; it runs
  the fixed bundled offline `iss` sample through the existing `run_sample(...)`
  (no orbital logic duplicated, backend/CLI unchanged).
- Renders: `mission_id`, `status = completed`, `epistemic_status =
  deterministic-calculation`, `sample_count`, `source.test_only`,
  `source_checksum`, `inputs_hash`, first/last geodetic samples, artifact links
  with checksums, two inline PNG previews, and the safety boundary.
- No `<script>`, no absolute filesystem path.

## Artifact link results

- The six whitelisted files each serve **200**:
  `altitude_vs_time.png/.json`, `ground_track.png/.json`,
  `static_report.json`, `static_report.md`.
- The two inline `<img>` previews point at
  `/review/artifacts/<mission_id>/<name>` (relative, same-origin, through the
  guarded route) and load **200** — no external image host.

## Safety tests

Route: `GET /review/artifacts/{mission_id}/{filename:path}`. Guards: mission_id
must be a valid UUID, filename must be an exact member of a 6-name whitelist,
resolved path must be contained under the artifacts root (`relative_to`), and the
target must be an existing file.

| Attack / case | Result |
| --- | --- |
| `../../README.md` (raw traversal) | **404**, README content absent |
| `%2e%2e%2f%2e%2e%2fREADME.md` (URL-encoded traversal) | **404**, content absent |
| `..%2f..%2fpyproject.toml` (mixed-encoding traversal) | **404**, content absent |
| Unknown filename `secrets.txt` | **404** |
| Invalid mission id (non-UUID) | **422** |
| Missing mission (valid UUID, no dir) | **404** |
| Directory listing `/.../<id>/` and `/.../<id>` | **404** (no listing) |
| Traceback / internal detail in failure bodies | none (sanitized `{code,message}`) |
| Absolute filesystem path in any HTML | none |
| User-controlled arbitrary file fetch | not possible (UUID + exact whitelist + containment + is_file) |
| Arbitrary sample/user input on `POST /review/run` | not possible (no params; `iss` hardcoded) |

## Determinism check

Two consecutive `run_sample(settings, sample_id="iss")` on identical settings:

- `sample_count`: **identical** (31)
- first/last geodetic samples (lat/lon): **identical**
- `source_checksum`: **identical**
- provenance `inputs_hash`: **identical**
- `mission_id` / `report_id` / artifact-link paths: **differ per run** (fresh
  UUID) — expected, and consistent with the documented reproducibility scope
  (same logical result + structured JSON/provenance; mission identity is
  per-run, artifact PNG bytes are not part of the reproducibility contract).
- No live API/provider dependency: network, CelesTrak, and JPL are disabled in
  the sample settings; the run is fully offline on the bundled stale sample TLE.

**Interpretation:** the *computation and provenance* are deterministic and
byte-stable across runs; the *mission identity* (UUID) is intentionally fresh per
run because each run persists a distinct mission. This is correct behavior, not a
determinism defect.

## Reviewer usefulness

A first-time reviewer can understand, from the browser surface alone:

- **What was computed:** a deterministic SGP4 propagation of the bundled ISS
  sample (31 samples; first/last geodetic positions shown).
- **What evidence was produced:** two PNGs (`altitude_vs_time`, `ground_track`),
  their JSON sidecars, `static_report.json`, and `static_report.md`, each with a
  checksum, plus `source_checksum` and `inputs_hash`.
- **Which values are deterministic:** `sample_count`, geodetic samples,
  `source_checksum`, and `inputs_hash` are stable across runs.
- **What safety boundary exists:** sample/test-only, not live tracking, no
  provider fetch, no command-readiness/approval/certification, no
  quantum-advantage, not production/public-alpha.
- **What is intentionally not supported yet:** arbitrary/user orbital input, live
  provider data, file/URL upload, user accounts, a broad dashboard/map UI, or
  additional samples beyond `iss`.

## Regression results

- `ruff check .` → passed
- `ruff format --check .` → 328 files already formatted
- `mypy src --show-error-codes --no-incremental` → Success, 185 source files
- `pytest` (sample runner + architecture boundaries + reviewer sandbox) → **15 passed**
- `alembic heads` → `m8b9c0d1e2f3`
- `git diff --check` → clean

## Issues found

No acceptance blockers. Informational notes only:

1. **Determinism framing (not a defect):** `mission_id`/`report_id`/artifact
   paths are per-run UUIDs; the computed result and provenance hashes are
   byte-stable. Matches the documented reproducibility contract.
2. **Process (not code):** the U2.2 changes are uncommitted working-tree edits on
   top of the U2.1 merge; commit/merge them before reviewer handoff. Re-running
   this acceptance after merge yields the same result.

## Final verdict

**Ready for reviewer demo.** The visual reviewer surface is safe (traversal-proof
whitelisted artifact serving, no arbitrary input, no absolute-path or traceback
leakage), understandable (clear evidence bundle + safety boundary + explicit
"not supported yet"), and deterministic at the computation/provenance level, with
all regression gates green and no backend/CLI/schema/dependency changes. No
acceptance blockers were found; it is also clear to proceed to the next
usefulness phase.
