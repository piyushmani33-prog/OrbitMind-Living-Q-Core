# First Trusted Operator Boundary

## Purpose
This document defines the first trusted operator boundary after Solo Alpha
smoke passed and the results closure was recorded.

It controls who may run the local/API-only Solo Alpha smoke flow, what they may
do, how feedback must be reported, and what claims remain forbidden.

This boundary does not widen OrbitMind to public alpha, external demo,
recruiter/user demo, UI, automation, live provider data, rendering, export,
Surface B, or quantum work.

## Operator Profile
The first trusted operator is:

- the project owner by default; or
- one owner-nominated technically trusted person.

The operator must be comfortable with:

- local Windows/PowerShell;
- the existing `.venv`;
- local API calls;
- Docker Compose/PostgreSQL, if running the optional PostgreSQL lane.

Governance constraints:

- Only one owner-nominated technical operator may be active at a time.
- The owner may revoke the nomination at any time.
- The nominated operator must acknowledge these trust constraints before
  running anything.

Trust constraints:

- Do not share logs publicly.
- Do not paste secrets.
- Do not paste raw DB URLs.
- Do not paste credentials.
- Do not paste stack traces publicly.
- Do not make external claims.
- Do not treat bundled sample data as live truth.
- Do not claim production readiness, certification, approval, public alpha, or
  live tracking.

## Allowed Setup
Allowed setup is limited to:

- local machine only;
- existing `.venv`;
- local API only;
- required SQLite lane;
- PostgreSQL lane allowed and preferred only when Docker/PostgreSQL is
  available;
- PostgreSQL validation counts only when the PostgreSQL lane actually runs
  against `127.0.0.1:55432`.

If PostgreSQL is skipped locally, it is not a live PostgreSQL pass.

## Allowed Docs And Checklists
The operator may read and follow:

- `docs/operations/SOLO_ALPHA_SMOKE_FLOW.md`;
- `docs/operations/SOLO_ALPHA_RESULTS_CLOSURE.md`;
- `docs/operations/RUNBOOK.md`.

`SOLO_ALPHA_SMOKE_FLOW.md` is the source of truth for exact smoke commands and
expected values. This boundary document does not duplicate all expected values
to avoid drift. If expected values differ, defer to
`SOLO_ALPHA_SMOKE_FLOW.md`.

## Allowed Actions
The operator may:

- run baseline checks;
- run Alembic;
- start the local API;
- call `GET /health`;
- call `GET /version`;
- call `GET /api/v1/system/capabilities`;
- submit only the canonical bundled ISS sample mission from the smoke checklist;
- retrieve the submitted mission;
- list missions;
- list artifacts;
- call the mission visual manifest;
- call the mission static report;
- call the mission map/orbit context;
- call the product summary catalog;
- run the safe failure check for unsupported satellite `DOES_NOT_EXIST`;
- run the safe failure check for an unknown mission id;
- optionally run `pytest -m postgres -v` when PostgreSQL is actually available;
- optionally verify the postgres collect count.

## Prohibited Actions
The operator must not:

- run public alpha;
- run an external demo;
- run a recruiter/user demo;
- present the smoke as production readiness;
- present the smoke as certification or approval;
- present the smoke as readiness scoring or authority scoring;
- make live tracking claims;
- make provider/live-data validation claims;
- make command-readiness claims;
- make quantum authority or quantum advantage claims;
- perform UI, frontend, or dashboard work;
- perform rendering, chart, graph, or map drawing work;
- perform export/PDF work;
- implement Surface B;
- implement the observation-study visual manifest;
- trigger provider/live-data refresh;
- use CelesTrak, JPL, or source refresh as validation;
- manually mutate the database;
- create migrations;
- change source code;
- change API behavior;
- add scripts;
- add automation;
- present arbitrary non-canonical mission exploration as validation.

## Feedback Template
Use this template for private feedback to the project owner:

```text
Operator category: owner | owner-nominated technical operator
Date:
Commit/HEAD:
Branch:
Alembic head:
OS:
Python version:
.venv used: yes | no
SQLite lane run: yes | no
PostgreSQL lane run: yes | no
PostgreSQL result if run: passed / skipped / failed; counts:
Exact checklist sections completed:
Mission id(s):
Mission status:
Sample count:
Artifacts present:
Read-product/schema checks:
Safe failure results:
Stop conditions encountered:
Unexpected output:
Confusing doc step:
Missing prerequisite:
Explicit note: no public/demo/production claims were made.
```

## Feedback Sanitization And Private Routing
Before sharing feedback, the operator must redact:

- credentials;
- DB URLs;
- tokens;
- secrets;
- filesystem paths;
- stack traces;
- raw SQL error details;
- internal service details.

Feedback must be shared privately with the project owner. Feedback must not be
posted publicly.

If a stop condition includes sensitive output, record only:

- the stop condition category;
- the endpoint or step;
- a sanitized summary.

Do not paste the raw leaked string into a public channel or public issue.

## Feedback To Ignore Or Defer For Now
Defer:

- UI polish requests;
- dashboard requests;
- frontend requests;
- rendering requests;
- graph, map, or export requests;
- live tracking/provider asks;
- arbitrary feature ideas outside the smoke boundary;
- performance, load, or SLO claims;
- quantum claims;
- public or recruiter demo requests.

## Stop Conditions
Stop and report privately if any of these occur:

- tracked files are dirty before or after the run unexpectedly;
- Alembic head mismatch;
- health fails;
- database disconnected;
- unexpected HTTP 500;
- unsanitized error body;
- sample count differs from the smoke checklist expected value;
- `source.test_only` is missing or false;
- expected artifacts from the smoke checklist are missing;
- response leaks path, stack, SQL, DB URL, secret, password, token, or internal
  detail;
- response claims live/provider data;
- response claims command readiness;
- response claims approval/certification/readiness;
- response claims quantum authority;
- PostgreSQL lane is skipped when PostgreSQL validation is being claimed.

Use `SOLO_ALPHA_SMOKE_FLOW.md` as the source of truth for exact expected values
such as sample count and artifact names.

## Explicit Out Of Scope
This boundary excludes:

- public alpha;
- external demo;
- recruiter/user demo;
- UI/frontend;
- dashboard;
- rendering;
- charts;
- graph/map drawing;
- export/PDF;
- Surface B;
- observation-study visual manifest implementation;
- provider/live-data;
- live tracking;
- source refresh;
- migrations;
- persistence changes;
- source changes;
- API behavior changes;
- scripts;
- automation;
- Quantum Studio;
- quantum implementation;
- quantum authority;
- load, concurrency, SLO, cloud, or security certification claims.

## Next-Step Rule
This boundary does not authorize automation.

This boundary does not authorize UI/frontend work.

This boundary does not authorize public alpha or recruiter/user demo.

This boundary does not authorize provider/live-data or quantum work.

Any widening beyond one local trusted operator requires a separate planning
branch and review.
