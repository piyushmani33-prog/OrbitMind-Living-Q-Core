# Optimization Benchmarks

Run exact + greedy + (optional) quantum on the same normalized instance, independently
verify every schedule, and produce a policy-driven conclusion + artifacts. See
ADR-0025/0028 and [QUANTUM_BENCHMARK_POLICY.md](../architecture/QUANTUM_BENCHMARK_POLICY.md).

## Run a benchmark (API)
```bash
curl -X POST localhost:8000/api/v1/optimization/problems/<problem_id>/benchmark \
  -H 'content-type: application/json' \
  -d '{"seed":7,"shots":2048,"optimizer_iterations":24,"qaoa_layers":1,
       "generate_artifacts":true,"competitive_relative_gap":0.0,
       "min_feasible_sample_ratio":0.05}'
```
The response carries the full `run` (solver results + quantum experiment + comparison),
the `findings` (verification), `verified`, and a disclaimer. `run_quantum:false` runs the
classical baselines only.

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
