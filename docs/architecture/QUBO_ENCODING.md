# QUBO Encoding (Phase 4A)

See ADR-0026. A **small internal QUBO** (`optimization/qubo.py`) — no `qiskit-optimization`
dependency.

## Form
Minimize `E(x) = offset + Σ_i linear_i x_i + Σ_{i<j} quad_ij x_i x_j`, `x_i ∈ {0,1}`.
`QuboModel` records linear/quadratic coefficients, the offset, the variable→opportunity
mapping, the penalty coefficient + explanation, and a deterministic checksum.

## The energy identity (exhaustively verified)
The QUBO is built so that, for **every** bitstring `x`:

```
E(x) == -penalized_objective(x)
```

where `penalized_objective(x) = raw_mission_value(x) − P·(#conflict-pairs both-selected + #mandatory not-selected)`.
Minimizing `E` therefore maximizes the penalized objective. This identity is checked
**exhaustively** on tiny instances (`test_optimization_core`, `opt.qubo_energy_equivalence`);
**a mismatch is a critical failure.**

## Coefficients
With penalty `P` (default `total mission value + 1`):
- `linear_i = −(value_i · mission_value_weight) − P·[i is mandatory]`
- `quad_ij = +P` for each conflict pair (overlap or mutual exclusion)
- `offset = P · (number of mandatory opportunities)`

The mission value is **weighted** by `objective.mission_value_weight` (review finding #7)
— consistently across the evaluator, the QUBO linear terms, the penalty bound, and the
benchmark/verification. Default weight is `1.0` (unchanged behaviour). All penalties are
exactly linear/quadratic in `x` — **no slack variables**, so the qubit count equals the
number of opportunities.

## Ising conversion
`qubo_to_ising` maps `x_i = (1 − z_i)/2` to `H = Σ h_i Z_i + Σ J_ij Z_i Z_j + offset`. The
QAOA cost layer applies `RZ(2γ h_i)` and `RZZ(2γ J_ij)`; the mixer applies `RX(2β)`. The
round-trip is verified (`test_ising_roundtrip`).

## Penalty policy + proof (review finding #6)
The penalty is **generated automatically** — `P = (Σ max(0, value_i)·weight) + 1`, i.e.
**strictly greater than the maximum possible total positive weighted mission value**, so no
combination of encoded violations can ever beat the best feasible assignment. Externally-
submitted custom penalties are **not accepted via the API**; an internal explicit penalty
(research/testing only) must be positive + finite or execution stops with a validation
error. `penalty_policy` (`penalties.py`) records the value, source, bound formula, and
**proves sufficiency exhaustively** for tiny instances (the global QUBO minimum must be an
encoded-feasible assignment, strictly below every encoded-infeasible one). A penalty is
**never** reported sufficient when no satisfying encoded assignment exists (contradictory
hard constraints, e.g. two conflicting mandatory opportunities). Larger `P` widens the QAOA
energy scale and can make the variational landscape harder — a documented trade-off.

## What the QUBO does NOT encode
Resource/cardinality constraints (energy/storage capacity, max-observations, per-target
limit, minimum value) are **enforced by the independent evaluator**, not the QUBO. The
QAOA optimizes conflict/mandatory penalties + value; resource-infeasible samples are
caught and rejected at verification. This is why an instance like `resource-bound` shows a
**feasible-sample ratio below 1.0** — an honest, documented consequence of the encoding,
not a bug.
