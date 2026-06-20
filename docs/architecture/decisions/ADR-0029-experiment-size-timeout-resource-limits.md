# ADR-0029 — Experiment Size, Timeout, and Resource Limits

- **Status:** Accepted (2026-06-21)

## Context
Unbounded instance size, shot counts, optimizer iterations, or wall-clock time would make
the exact solver intractable, the QAOA circuit large, and CI slow/fragile. Bounds keep the
phase honest and reproducible.

## Decision
- `SchedulingProblemLimits` (per problem) bounds: `max_variables` (≤24), the exact
  solver's `exact_max_variables` (≤22), `max_shots` (≤65536), `max_optimizer_iterations`
  (≤512), and `max_timeout_seconds` (≤120). Problem normalization rejects instances above
  `max_variables`.
- The **API** further bounds inputs: shots ≤16384, optimizer iterations ≤128, QAOA layers
  ∈ [1,3], timeout ∈ (0,60]; only supported solver names (`exact`/`greedy`) and the fixed
  `AerSimulator` backend are accepted. No hardware-provider input, no arbitrary Python, no
  command execution, and **no raw Qiskit object deserialization** (only structured,
  validated JSON crosses the boundary).
- **Timeouts/cancellation:** the exact solver checks a deadline during enumeration and
  returns `timed-out` with a feasible (not proven) result; the quantum experiment checks a
  deadline during parameter search and returns `timed-out`. Quantum execution is
  **disabled when Aer is unavailable** — the API returns a clear `unsupported` status
  rather than silently using a different algorithm.
- Bundled fixtures are 3–4 opportunities (3–4 qubits) so the exact optimum is enumerable
  and the circuit is tiny, keeping CI bounded.

## Alternatives considered
1. **No hard caps, rely on convention.** Risks an accidental 2^30 enumeration or a huge
   circuit. Rejected — explicit, validated bounds.
2. **Allow a user-supplied backend string.** Could smuggle a hardware provider. Rejected —
   the backend is fixed to the local simulator.

## Consequences
- Deterministic, fast, offline experiments; the API cannot be coerced into an unbounded or
  unsafe computation.

## Review trigger
Revisit the caps if a future phase needs larger (still simulator-only) experiments.
