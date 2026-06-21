# Quantum Benchmark Policy (Phase 4A)

See ADR-0028. The benchmark is fair, fully recorded, and conservatively labelled. **It
never claims general quantum advantage.**

## Fairness
Classical (exact + greedy) and quantum solvers run the **same normalized instance**
(checksum equality is verified). For every solver we record: problem checksum, solver
name/version, configuration, seed, start/end timestamps, runtime, objective, raw mission
value, feasibility, violations, optimality status, known optimum, objective gap, resource
usage, and error/timeout status. Quantum additionally records qubits, depth, gate counts,
shots, optimizer iterations, backend, transpile level, and feasible-sample ratio. **We do
not compare objectives while hiding runtime, infeasibility, or problem size.**

## Honest sample processing
The most frequent bitstring is **not** assumed best. Each sample is decoded → independently
evaluated → raw value / violations / objective computed → the **best verified feasible**
sample is selected. Reported: total shots, distinct samples, feasible-sample ratio, best
feasible sample, best infeasible sample, objective gap vs the exact optimum, selected
sample probability, and whether the exact optimum appeared in samples. **Infeasible and
failed samples are preserved for diagnostics, never suppressed.**

## Conclusions (policy-driven, `benchmark.conclude`)
| Conclusion | Meaning |
|-----------|---------|
| `classical-exact-best` | Exact optimum found; no quantum comparison (or quantum not run). |
| `classical-greedy-best` | Greedy is the best classical; no proven optimum / no quantum. |
| `quantum-competitive` | Feasible quantum met the bounded threshold (rel-gap ≤ threshold of the proven optimum, or beat the heuristic when the optimum is unproven). **NOT advantage.** |
| `quantum-worse` | Feasible quantum below the reference beyond the threshold. |
| `quantum-infeasible` | No feasible quantum sample observed. |
| `equivalent-objective` | Quantum exactly ties the best classical when the optimum is **not** proven. |
| `insufficient-evidence` | Feasible-sample ratio below threshold, timed out with no feasible sample, or no classical reference. |
| `experiment-failed` | The quantum experiment errored. |

The verifier re-derives the conclusion from the recorded results and **rejects a mismatch**
(`opt.conclusion_policy`).

## Reproducibility & its limits
Fixed `seed`/`seed_simulator`/`seed_transpiler` and a deterministic parameter search make
a run reproducible bit-for-bit on the same machine + package versions. **Limits:** shot
noise (finite sampling), optimizer variability across parameter grids, and the fact that
matching the optimum on a 3–4 qubit simulator instance is a correctness signal, not a
performance claim. **No production decision is ever made on quantum output alone.**

## Status guards precede objective comparison (review finding #19)
The conclusion is decided by checking the quantum **status first**. A run that is
`timed-out`, `cancelled`, `failed`, `unsupported`, `pending`, `running`, `inconclusive`,
that lacks a feasible sample, or whose `problem_checksum` differs from the classical
baselines can **never** receive `quantum-competitive`/`equivalent-objective` — it is forced
to a non-positive conclusion (`insufficient-evidence` / `experiment-failed` /
`quantum-infeasible`) before any objective is compared.

## Whole-experiment timeout (review finding #3)
The quantum experiment runs in an **isolated child process** with a hard, parent-side
wall-clock deadline covering the entire operation (QUBO prep, circuit build, transpilation,
parameter search, sampling, decoding, selection). On expiry the worker is **terminated**:
no final sampling completes, the status is `timed-out`, no best solution is presented as
completed evidence, and the benchmark conclusion is non-positive.

## Tamper-resistant verification (review finding #2)
The verifier **recomputes** authoritative values from canonical inputs — it re-solves the
exact/greedy baselines, re-derives the penalty + QUBO energy (exhaustively), recomputes
per-sample probability/feasibility/energy and the feasible-sample ratio from the observed
counts, confirms the selected sample was actually observed, recomputes artifact checksums
from disk and validates sidecar metadata, and re-derives the conclusion. A persisted value
is never trusted as proof of itself; any failed material check downgrades the run to
non-positive and blocks scientific-memory registration.

## Observed bounded results (default fixtures, seed 7)
- `default` → `quantum-competitive` (matched optimum 10; feasible-sample ratio 1.0).
- `resource-bound` → `quantum-competitive` (matched optimum 15; feasible-sample ratio
  ~0.36 — resource constraints not in the QUBO).
- `mutual-exclusion` → `quantum-worse` (quantum 9 vs optimum 10) — an honest "worse"
  outcome.
