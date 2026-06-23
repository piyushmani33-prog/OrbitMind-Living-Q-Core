# Satellite Observation Scheduling (Phase 4A)

Choose a set of candidate observation opportunities that **maximizes total mission value**
subject to conflicts and resource limits. One binary decision variable per opportunity.
See ADR-0024.

## Variables & bit-order convention
The decision variables are the opportunities; the **stable variable order is the
opportunity ids sorted lexicographically**, index 0 first. Every encoding/decoding uses
this order. Aer measurement strings are reversed (qubit 0 is the rightmost character)
before decoding into this index order.

## Constraints (`ConstraintSet`)
Enforced by the shared `Evaluator` (every solver uses the same normalized constraints):

| Constraint | Kind | In QUBO? |
|-----------|------|----------|
| Same-satellite time overlap | `no-overlap` | yes (pairwise `+P`) |
| Mutually exclusive opportunities | `mutual-exclusion` | yes (pairwise `+P`) |
| Mandatory opportunity | `mandatory` | yes (`+P(1-x)`) |
| Max selected observations | `max-observations` | no (verifier) |
| Total energy capacity (per satellite) | `energy-capacity` | no (verifier) |
| Total storage capacity (per satellite) | `storage-capacity` | no (verifier) |
| Per-target observation limit | `per-target-limit` | no (verifier) |
| Minimum mission value | `min-mission-value` | no (verifier) |

**No solver's feasibility claim is trusted** — the evaluator re-checks every returned
schedule (ADR-0025).

## Objective (decomposed)
`ScheduleEvaluation` separates: **raw mission value** (Σ selected values), **constraint
penalty** (`P` × number of QUBO-encoded violations), and **penalized objective**
(`raw − penalty`, equal to `−QUBO energy`). Feasible schedules are ranked by raw mission
value; infeasible schedules are rejected (not "best"). Penalty `P` defaults to
`total value + 1` (provably sufficient; ADR-0026).

## Bundled fixtures
- `default` — 4 opportunities, conflict-only (QUBO fully captures feasibility); optimum 10.
- `resource-bound` — 4 opportunities exercising capacity, max-observations, per-target,
  and mandatory; optimum 15.
- `mutual-exclusion` — 3 opportunities with a configured mutual exclusion; optimum 10.

Instances are intentionally tiny (3–4 qubits) so the exact solver enumerates the optimum
and the QAOA circuit stays bounded (ADR-0029). They are **bundled, deterministic
fixtures — not live CelesTrak/JPL data.**
