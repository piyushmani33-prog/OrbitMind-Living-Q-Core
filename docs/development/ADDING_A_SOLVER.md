# Adding a Solver

Every solver — classical or quantum — must be **deterministic**, return a `SolverResult`
(or `QuantumExperiment`), and have its schedule **independently re-verified** by the shared
`Evaluator`. A solver's own feasibility/objective claim is never trusted (ADR-0025/0028).

## Classical solver
Add `src/orbitmind/optimization/solvers/<name>.py`:

```python
def solve_mine(problem, config, evaluator=None):
    evaluator = evaluator or Evaluator(problem)
    # ... deterministic search; NO randomness; honor config.timeout_seconds ...
    ev = evaluator.evaluate(selected)          # the verifier decides feasibility/objective
    return build_result(
        solver_kind=config.solver_kind, solver_name="mine", solver_version="1.0",
        problem_checksum=problem.checksum, config=config, evaluation=ev,
        status=ExperimentStatus.COMPLETED, optimality=OptimalityStatus.FEASIBLE,
        known_optimum=None, runtime_seconds=..., evaluated_candidates=...,
        limitations="documented ordering / size limits",
    )
```

Requirements: fixed tie-breaking, a documented ordering rule, a hard size cap (return
`unsupported` above it if exhaustive), a timeout check, and recorded seed + software
versions (`build_result` captures versions). Add determinism + correctness tests
(`test_optimization_solvers`). **Do not add a large optimization dependency** unless
demonstrably necessary (ADR-0026, section 20).

## Quantum experiment
Stay within the simulator-only boundary (ADR-0027): Aer only, fixed seeds, bounded
shots/iterations/timeout, record full circuit metadata, decode every sample, select the
**best verified feasible** sample, and preserve infeasible samples. Reuse `build_qaoa_circuit`
and the QUBO/Ising helpers.

## Wiring
Add the solver to the benchmark (`benchmark.py`) and/or the service (`service.py`), extend
the comparison policy only if a genuinely new outcome is needed (and update
`QUANTUM_BENCHMARK_POLICY.md` + the verifier's `opt.conclusion_policy`).
