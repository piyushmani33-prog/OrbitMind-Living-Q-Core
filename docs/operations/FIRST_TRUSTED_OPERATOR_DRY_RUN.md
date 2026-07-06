# First Trusted Operator — Dry-Run Pack

A short, self-contained guide for **one careful technical reviewer** to review
OrbitMind locally and give feedback. It is a review dry-run, not an operations
manual and not a launch.

This pack does **not** present OrbitMind as production, public alpha, live
tracking, live-provider validation, quantum advantage, or a
command/readiness/approval/certification system. It complements the trust rules
in [`FIRST_TRUSTED_OPERATOR_BOUNDARY.md`](FIRST_TRUSTED_OPERATOR_BOUNDARY.md) and
the run procedure in [`SOLO_ALPHA_SMOKE_FLOW.md`](SOLO_ALPHA_SMOKE_FLOW.md).

## 1. Who this is for
- A **first trusted technical reviewer/operator** — the project owner or one
  owner-nominated technical person (see the operator boundary doc).
- **Not** public users, **not** customers, **not** production operators.

## 2. What to review
- README and setup clarity from a fresh clone.
- The local, API-only flow (health/version/capabilities and one deterministic
  bundled sample mission), if you choose to run it.
- Whether the **safety boundaries** are obvious and hard to misread.
- The **deterministic, bundled sample/test-only** workflow (not live data).
- **Audit/provenance** outputs (lifecycle events, `inputs_hash`, `source_data`,
  epistemic labels).
- **Artifact inspection** as local inspection aids only.
- Whether OrbitMind is understandable within **5–10 minutes**.

## 3. What NOT to review yet
- No public alpha; no production deployment.
- No live satellite tracking; no live-provider validation.
- No quantum advantage; no UI/dashboard expectations.
- No command/readiness/approval/certification/operational-safety use.

Treat any of the above as explicitly out of scope for this dry run.

## 4. Dry-run steps
Use a fresh clone or a clean local checkout. From the project root:

```bash
# create + activate a virtual environment
python -m venv .venv
# Windows (PowerShell/cmd):  .venv\Scripts\activate
# macOS/Linux:               source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

# offline quality gates (no network, no PostgreSQL required)
python -m ruff check .
python -m ruff format --check .
python -m mypy src
python -m pytest -q
python -m alembic heads        # expect a single head
```

Then, **only if you want to** and following the README's documented flow:

- Run the local API sample flow exactly as described in the README's
  "Verify the backend" / usage sections and in
  [`SOLO_ALPHA_SMOKE_FLOW.md`](SOLO_ALPHA_SMOKE_FLOW.md) (the source of truth for
  exact commands and expected values). Submit only the canonical bundled sample
  mission.
- Inspect any generated files under `artifacts/<mission_id>/` **only as local
  inspection aids** — they are not authority. The typed response, provenance,
  and audit trail are the record.

Do not add features, run non-canonical experiments as validation, enable
providers/live-data, or treat any result as live truth.

## 5. Feedback form
Please answer briefly (a short report is enough — no code changes):

- Could you understand OrbitMind within 5 minutes?
- Could you set it up from a fresh clone?
- Where did you get confused?
- Did any claim feel too big?
- Did the safety boundaries feel clear?
- Did the provenance/audit behavior look credible?
- What are your top 3 fixes before wider reviewer outreach?
- Would you continue reviewing? (yes / no / maybe) — and why?

Please send feedback **privately** to the project owner. Do not post secrets,
logs, database URLs, tokens, or private paths; send a sanitized summary instead.

## 6. Stop conditions
Stop the dry run and report if any of these occur:

- Setup fails (install, migrations, or the offline gates do not pass).
- The README (or any output) implies **live satellite tracking**.
- Any **secret, credential, token, or private file** is found.
- Output appears to claim **real-world current satellite truth** from
  stale/bundled sample data.
- OrbitMind appears to be presented as **production or public alpha**.

## 7. Final output
The reviewer returns a **short written report** (answers to the feedback form
plus any stop conditions hit) — **not code changes**. The owner triages the
feedback and decides the next step separately.
