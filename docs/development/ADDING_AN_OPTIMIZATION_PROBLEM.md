# Adding an Optimization Problem

Problems are **bounded, deterministic** scheduling instances. See ADR-0024/0029.

## As a bundled fixture (preferred for the benchmark)
Add a builder to `src/orbitmind/optimization/fixtures.py` returning a `SchedulingProblem`
and register it in `FIXTURES`:

```python
def my_instance() -> SchedulingProblem:
    return SchedulingProblem(
        name="my-instance",
        opportunities=[_opp("OPP-1", "SAT-A", "T1", 0, 30, 5.0), ...],
        satellites=[SatelliteResource(id="SAT-A", energy_capacity=100.0, storage_capacity=100.0)],
        targets=[ObservationTarget(id="T1")],
        constraints=ConstraintSet(max_observations=3, mandatory=("OPP-1",)),
    )
```

Keep it **tiny** (≤ ~6 opportunities) so the exact solver enumerates the optimum and the
QAOA circuit stays small. Use fixed UTC datetimes (deterministic). Then add a test asserting
the exact optimum and that the QUBO energy equals the negated penalized objective for all
bitstrings (`test_optimization_core` is parametrized over fixture names — add yours).

## Via the API (structured spec)
`POST /api/v1/optimization/problems` with a full `problem` body (or `{"fixture": "<name>"}`).
Validation enforces: unique opportunity ids, `≤ max_variables`, nonnegative costs, bounded
mission values, timezone-aware windows, and valid constraint references. The server stamps
the deterministic checksum.

## Invariants
- One binary variable per opportunity; variable order = sorted opportunity ids.
- Every constraint you add must be checked by the shared `Evaluator` (`evaluation.py`); if
  it is pairwise/mandatory it is also encoded in the QUBO (`qubo.py`) and must preserve the
  exhaustive energy identity.
- All datetimes timezone-aware UTC; costs nonnegative; values bounded.
