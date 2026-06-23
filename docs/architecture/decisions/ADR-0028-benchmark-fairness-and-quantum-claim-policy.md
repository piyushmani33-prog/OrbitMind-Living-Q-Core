# ADR-0028 — Benchmark Fairness and Quantum-Claim Policy

- **Status:** Accepted (2026-06-21)

## Context
It is easy to mislead by comparing only objective values, hiding runtime/infeasibility/
problem size, or by labelling a simulator result as "quantum advantage". Phase 4A must be
scientifically honest and must never overclaim.

## Decision
- **Same instance:** classical and quantum solvers receive the identical *normalized*
  problem (verified by checksum equality across all results — `opt.same_instance`).
- **Full record per solver:** problem checksum, solver name/version, configuration, seed,
  start/end timestamps, wall-clock runtime, objective value, raw mission value,
  feasibility, constraint violations, optimality status, known optimum (when available),
  objective gap, resource usage, and error/timeout status. Quantum additionally records
  qubits, circuit depth, gate counts, shots, optimizer iterations, simulator backend,
  transpile level, and **feasible-sample ratio**. We never compare objectives while
  hiding runtime, infeasibility, or size.
- **Honest sample processing:** the most frequent bitstring is **not** assumed best. Every
  sample is decoded, independently re-evaluated for feasibility/value, and the **best
  verified feasible** sample is selected. Infeasible/failed samples are **preserved for
  diagnostics**, never suppressed.
- **Policy-driven conclusions** (`benchmark.conclude`, a pure function): `classical-exact-best`,
  `classical-greedy-best`, `quantum-competitive`, `quantum-worse`, `quantum-infeasible`,
  `equivalent-objective`, `insufficient-evidence`, `experiment-failed`. The verifier
  re-derives the conclusion and rejects a mismatch (`opt.conclusion_policy`).
- **`quantum-competitive` means ONLY that a feasible quantum result met a defined bounded
  threshold (relative gap + minimum feasible-sample ratio) for THIS tiny instance. It is
  NOT a claim of general quantum advantage** — that claim is never made. Simulator results
  do not demonstrate hardware advantage.

## Alternatives considered
1. **Report objective values only.** Hides the real story (infeasibility, runtime, size).
   Rejected.
2. **Pick the modal bitstring as the answer.** Statistically wrong and unverified.
   Rejected — verified-feasible selection only.

## Consequences
- Every comparison is reproducible, fully attributed, and conservatively labelled; the
  five honest outcomes (competitive / worse / infeasible / inconclusive / failed-or-timed-
  out) are all representable and tested.

## Review trigger
Revisit if thresholds need tuning for larger instances, or if additional honest outcomes
are required.
