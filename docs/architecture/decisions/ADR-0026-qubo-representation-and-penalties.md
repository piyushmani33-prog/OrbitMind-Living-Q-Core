# ADR-0026 — QUBO Representation and Constraint Penalties

- **Status:** Accepted (2026-06-21)

## Context
QAOA needs the problem as a QUBO/Ising. We must control the encoding exactly so the
quantum objective provably matches the classical evaluator, and we must size penalty
weights defensibly rather than by guesswork.

## Decision
- Implement a **small internal QUBO** (`optimization/qubo.py`) — no `qiskit-optimization`
  dependency (see ADR-0027 for the package-maintenance reasoning). `QuboModel` holds
  linear coefficients, quadratic coefficients, a constant offset, the
  variable→opportunity mapping, a penalty explanation, and a deterministic checksum.
- **Energy identity:** the QUBO minimizes `E(x) = offset + Σ linear_i x_i + Σ quad_ij x_i x_j`,
  constructed so that **`E(x) == -penalized_objective(x)`** for the shared `Evaluator`,
  for *every* bitstring. This is **exhaustively verified** on tiny instances; a mismatch
  is a **critical failure** (`opt.qubo_energy_equivalence`).
- **Encoded penalties** (all exactly linear/quadratic in x, no slack variables):
  - pairwise conflicts (same-satellite time overlap + mutual exclusion): `+P` when both
    selected (`quad_ij`);
  - mandatory opportunity `m`: `+P(1 - x_m)` (linear + offset).
- **Penalty weight `P`** defaults to `(total mission value + 1)` — provably larger than
  any value gained by violating a constraint, so a violation can never be optimal. A
  `penalty_is_sufficient` check reports when a configured `P` is too small. Resource/
  cardinality constraints (capacity, max-observations, per-target, min-value) are
  **enforced by the independent evaluator** (feasibility), not folded into the QUBO
  energy — keeping the qubit count equal to the number of opportunities (no slack bits).
- The objective decomposes explicitly into raw mission value, constraint penalty, and
  final penalized objective (recorded on every `ScheduleEvaluation`).

## Alternatives considered
1. **`qiskit-optimization` QuadraticProgram→QUBO.** Adds a not-IBM-maintained dependency
   (R-018) and hides the encoding. Rejected — a hand-built QUBO is small and verifiable.
2. **Slack variables for inequality (capacity) constraints.** Exactly QUBO-encodable but
   adds `log2(capacity)` qubits per constraint, breaking "tiny instances". Rejected;
   capacity is verified classically and documented as a known modelling limitation.

## Consequences
- An exactly-verified, dependency-free QUBO; QAOA optimizes conflict/mandatory penalties
  while resource feasibility is enforced at verification (documented in QUBO_ENCODING.md).

## Review trigger
Revisit if resource constraints must be inside the QUBO (requires slack qubits) or if a
maintained QUBO library becomes clearly preferable.
