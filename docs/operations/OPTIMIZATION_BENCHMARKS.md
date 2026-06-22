# Optimization Benchmarks

Run exact + greedy + (optional) quantum on the same normalized instance, independently
verify every schedule, and produce a policy-driven conclusion + artifacts. See
ADR-0025/0028 and [QUANTUM_BENCHMARK_POLICY.md](../architecture/QUANTUM_BENCHMARK_POLICY.md).

## Run a benchmark (API)
```bash
curl -X POST localhost:8000/api/v1/optimization/problems/<problem_id>/benchmark \
  -H 'content-type: application/json' \
  -d '{"seed":7,"shots":2048,"optimizer_iterations":24,"qaoa_layers":1,
       "generate_artifacts":true,"policy_id":"strict-v1"}'
```
The comparison thresholds are **server-owned**: a request selects a policy by `policy_id`
(`strict-v1` default, or `lenient-v1`) — it does **not** send raw `competitive_relative_gap` /
`min_feasible_sample_ratio` values (those are rejected as client-supplied thresholds). The
response carries the full `run` (solver results + quantum experiment + comparison), the
`findings` (verification), `verified`, and a disclaimer. `run_quantum:false` runs the classical
baselines only.

## Evidence signing (execution receipts)
Each accepted benchmark is sealed with an HMAC-SHA256 **execution receipt** that binds the
problem/policy/association ids and every config/sample/circuit/artifact digest, plus the
worker's 128-bit execution nonce for quantum runs.

- **Key config** (env only, never the DB/logs): `ORBITMIND_EVIDENCE_SIGNING_KEY` (the active
  secret), `ORBITMIND_EVIDENCE_SIGNING_KEY_ID` (default `primary`), and
  `ORBITMIND_EVIDENCE_SIGNING_RETIRED_KEYS` (`kid1:secret1,kid2:secret2` for verify-only
  rotation). Secrets are `SecretStr` — they never appear in `repr`, `model_dump`, logs, errors,
  audits, or any API response.
- **Key strength**: a configured key must be **≥ 32 bytes** and not a known placeholder
  (`changeme`, `placeholder`, …); active + retired key ids and material must be distinct.
  Generate one with `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
- **No-signer mode**: when the key is **empty**, benchmarks run **diagnostically but are never
  ACCEPTED** (execution provenance unavailable). There is **no implicit test-environment
  signer** — tests inject a key explicitly. `.env.example` ships a **blank** key.
- **Rotation**: the active key signs; retired keys verify only. A receipt signed by a retired
  key still verifies while that key is in the keyring and degrades to an honest
  `unknown-key-id` (not a crash) once removed.
- **Receipt linkage in artifacts**: the signed receipt (public metadata + canonical payload +
  signature, never the secret) is embedded into every artifact sidecar, so a consumer can
  authenticate a sidecar **offline** (no DB) via the embedded HMAC + field binding.
- **Timeout/failure prohibition**: a quantum experiment that is not a **completed** worker run
  (timed-out/failed/cancelled/unsupported/inconclusive) receives **no receipt**, is **not
  accepted**, yields an `insufficient-evidence` conclusion, and registers **no** memory edges.

## Read-time verification (do not trust the stored flag)
Every read **re-authenticates**: it reconstructs the domain benchmark from persistence and
re-runs semantic + ownership + receipt verification — the stored `verification_passed` flag is
never trusted on its own.

- `GET /runs` returns strict, re-authenticated `RunSummaryView`s (no paths/config).
- `GET /benchmarks/<id>` returns the authenticated benchmark; a tampered row is served with
  `integrity_failed:true` and a non-positive conclusion (never a positive serve).
- `GET /runs/<id>/artifacts` **withholds** artifacts (bounded `422`) when re-auth fails.
- `GET /benchmarks/<id>/evidence-graph` re-authenticates, then navigates the benchmark's memory
  edges; if re-auth fails every edge is flagged `integrity_failed` and `valid_evidence:false`
  (the edges + audit history are retained, not deleted).

On a tamper an `optimization.benchmark_integrity_failed` audit is written in its own
transaction; the original audit history is preserved.

## Historical policy verification
The benchmark carries an immutable, **self-validating** policy snapshot. Verification
authenticates an **active** policy against the server registry, and a **retired** policy (no
longer in the registry) against that self-consistent snapshot — so historical evidence stays
verifiable after a controlled retirement instead of crashing or silently switching thresholds.

## Trust limits
Receipts attest **execution provenance + integrity** of a bounded, simulator-only benchmark on
a tiny fixture (epistemic status `model-estimate`). They are **not** evidence of quantum
advantage, and not a verified scientific fact. A valid receipt only proves the evidence was
produced + sealed by the trusted runtime and has not been altered.

## Artifacts
With `generate_artifacts:true`, files are written under `artifacts/<run_id>/`, each with a
JSON sidecar (artifact type, problem checksum, solver, timestamp, software versions, seed,
epistemic status `model-estimate`, verification summary, checksum, limitations):
1. `selected_timeline.png` — selected-observation timeline
2. `objective_comparison.png` — solver objective comparison
3. `feasibility_comparison.png` — feasibility / constraint-violation comparison
4. `quantum_sample_distribution.png` — sample counts coloured by feasibility
5. `circuit_diagram.png` (or `.txt` fallback) — the QAOA circuit (documentation only)
6. `benchmark_summary.json` — machine-readable summary

Retrieve metadata: `GET /api/v1/optimization/runs/<run_id>/artifacts`. **Generated
artifacts/images are git-ignored and never committed.**

## Verification gate
A benchmark is only registered to scientific memory if **all critical/error checks pass**
(`opt.qubo_energy_equivalence`, `opt.same_instance`, `opt.quantum_simulator_only`,
`opt.quantum_sample_observed`, `opt.conclusion_policy`, objective recomputation, …). A
solver result failing verification is **not** marked successful.

## Memory integration (bounded)
On a verified benchmark, bounded entity links are registered (NO broad claims): problem
`solved-by` solver run, solver run `produced` schedule, quantum experiment
`compared-against` exact run, comparison `supported-by` artifacts. Query with
`GET /api/v1/memory/graph/<problem_id>/neighbors`.

## Local PostgreSQL benchmark validation
The Phase 4A tables migrate cleanly to head on PostgreSQL; run the PostgreSQL-marked
suite (see [POSTGRESQL_LOCAL_OPERATIONS.md](POSTGRESQL_LOCAL_OPERATIONS.md)):
```bash
ORBITMIND_TEST_POSTGRES_URL=postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind_test \
  python -m pytest -m postgres tests/integration/test_postgres_optimization.py -v
```
