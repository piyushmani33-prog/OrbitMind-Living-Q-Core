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

## Observed bounded results (default fixtures, seed 7)
- `default` → `quantum-competitive` (matched optimum 10; feasible-sample ratio 1.0).
- `resource-bound` → `quantum-competitive` (matched optimum 15; feasible-sample ratio
  ~0.36 — resource constraints not in the QUBO).
- `mutual-exclusion` → `quantum-worse` (quantum 9 vs optimum 10) — an honest "worse"
  outcome.
