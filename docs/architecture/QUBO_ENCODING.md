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
- `linear_i = −value_i − P·[i is mandatory]`
- `quad_ij = +P` for each conflict pair (overlap or mutual exclusion)
- `offset = P · (number of mandatory opportunities)`

All penalties are exactly linear/quadratic in `x` — **no slack variables**, so the qubit
count equals the number of opportunities.

## Ising conversion
`qubo_to_ising` maps `x_i = (1 − z_i)/2` to `H = Σ h_i Z_i + Σ J_ij Z_i Z_j + offset`. The
QAOA cost layer applies `RZ(2γ h_i)` and `RZZ(2γ J_ij)`; the mixer applies `RX(2β)`. The
round-trip is verified (`test_ising_roundtrip`).

## Penalty-weight limitation
`P = total value + 1` is a safe upper bound that guarantees a constraint violation can
never be optimal; `penalty_is_sufficient` reports if a smaller configured `P` is unsafe.
Larger `P` widens the QAOA energy scale and can make the variational landscape harder —
a documented trade-off.

## What the QUBO does NOT encode
Resource/cardinality constraints (energy/storage capacity, max-observations, per-target
limit, minimum value) are **enforced by the independent evaluator**, not the QUBO. The
QAOA optimizes conflict/mandatory penalties + value; resource-infeasible samples are
caught and rejected at verification. This is why an instance like `resource-bound` shows a
**feasible-sample ratio below 1.0** — an honest, documented consequence of the encoding,
not a bug.
