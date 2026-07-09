# OrbitMind Phase U1 Sample Runner Report

## Starting usefulness gap

Before Phase U1, a technical reviewer had to install the project, migrate the
database, start `uvicorn`, send API requests, and inspect large JSON responses to
see the deterministic orbital workflow do something useful.

That flow was accurate, but too much ceremony for a first look. The missing
product affordance was a one-command offline path that reused the real mission
workflow without requiring the API server.

## Files changed

- `src/orbitmind/sample.py`
- `tests/test_sample_runner.py`
- `README.md`

This closeout report adds:

- `docs/ORBITMIND_PHASE_U1_SAMPLE_RUNNER_REPORT.md`

## CLI behavior

The reviewer command is:

```bash
python -m orbitmind.sample
```

When run from the project environment, the command:

- uses the bundled ISS/ZARYA sample fixture
- runs the existing deterministic orbit-propagation workflow
- uses local SQLite
- writes local artifacts under `artifacts/<mission_id>/`
- prints a concise reviewer-readable summary
- does not start the API server
- does not fetch live/provider data
- does not add command readiness, approval, certification, or quantum claims

## Stdout summary

The command prints:

- mission id
- mission status
- epistemic status
- sample count
- sample/test-only source marker
- source checksum
- inputs hash
- first and last geodetic samples
- local image and sidecar paths for generated artifacts
- artifact checksums
- static report schema version and report id
- static report JSON path and checksum
- static report Markdown path and checksum
- safety boundary text

Example static report block:

```text
Static report
  schema_version: static-report-v1
  report_id: static-report:mission:<mission_id>:v1
  generated_on_demand: true
  local file: artifacts\<mission_id>\static_report.json
  checksum: <json_sha256>
  local markdown: artifacts\<mission_id>\static_report.md
  markdown_checksum: <markdown_sha256>
```

## Output artifacts

For each sample mission run, the runner writes under:

```text
artifacts/<mission_id>/
```

Current outputs:

- `altitude_vs_time.png`
- `altitude_vs_time.json`
- `ground_track.png`
- `ground_track.json`
- `static_report.json`
- `static_report.md`

The static report JSON is serialized from the existing
`MissionStaticReportResponse` with deterministic formatting where practical.

The static report Markdown is a short human-readable rendering of the already
computed report and mission detail. It contains only bounded sample/report facts
and safety-boundary language.

## Implementation notes

- The runner lives at `src/orbitmind/sample.py`.
- The command remains `python -m orbitmind.sample`.
- The module is a CLI composition root for reviewer flow only.
- It reuses the existing app container, orchestrator, repository, mission detail
  projection, visual manifest projection, and static report projection.
- It writes report artifacts under the configured artifacts root.
- CLI output uses relative/local artifact paths rather than absolute paths.
- Broad CLI errors are bounded and do not print tracebacks by default.
- Network/source refresh behavior is disabled in the sample settings.
- Quantum behavior is disabled in the sample settings.

## Services reused

The runner reuses existing OrbitMind services instead of creating a parallel
sample implementation:

- `AppContainer`
- `PrimeOrchestrator` via the container
- existing orbit-propagation request/domain conversion
- `SqlAlchemyMissionRepository`
- `SqlAlchemySourceRepository`
- mission detail response projection
- mission visual manifest projection
- mission static report projection
- existing artifact generation and checksum behavior

## Tests added

`tests/test_sample_runner.py` covers:

- successful offline sample execution
- completed deterministic mission status
- sample count
- sample/test-only source marker
- provenance inputs hash presence
- generated image and sidecar artifacts
- static report JSON creation and parseability
- static report Markdown creation and reviewer-readable content
- static report checksums
- bounded summary output
- no absolute temp path leakage in summary output
- safety-boundary text
- CLI success path
- sanitized broad CLI failure behavior

`tests/test_architecture_boundaries.py` preserves the narrow architecture
exception for `src/orbitmind/sample.py` as a CLI composition root only.

## Validation commands

Validation was run from the project virtual environment. On this machine, plain
global `python -m orbitmind.sample` outside the virtual environment used the
global interpreter and could not resolve the editable package; after activating
the project `.venv`, the documented command passed.

Commands run:

```bash
python -m orbitmind.sample
python -m ruff check .
python -m ruff format --check .
python -m mypy src --show-error-codes --no-incremental
python -m pytest
python -m pytest -q
python -m pytest tests/test_sample_runner.py tests/test_architecture_boundaries.py
python -m alembic heads
git diff --check
```

Results:

- activated-venv `python -m orbitmind.sample`: passed
- `ruff check .`: passed
- `ruff format --check .`: passed
- `mypy src --show-error-codes --no-incremental`: passed
- initial non-quiet `pytest`: timed out after 15 minutes without a reported
  failure
- full `pytest -q`: passed on the longer closeout run
- targeted sample/boundary tests: `7 passed, 1 warning`
- `alembic heads`: `m8b9c0d1e2f3 (head)`
- `git diff --check`: passed

## Remaining gaps

- A reviewer still needs the project environment installed or activated.
- There is only one bundled sample mission.
- There are no CLI flags yet.
- There is no sample-pack selection.
- There is no live-provider validation.
- There is no dashboard, UI, PDF, HTML export, or API redesign.
- There is no public-alpha or production-readiness claim.

## Final verdict

One-command sample works.
