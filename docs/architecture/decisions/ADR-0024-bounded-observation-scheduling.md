# ADR-0024 — Bounded Satellite Observation Scheduling Problem

- **Status:** Accepted (2026-06-21)

## Context
Phase 4A needs one concrete, bounded optimization problem to compare classical and
quantum (simulator) methods honestly. Satellite observation scheduling — choosing which
candidate observation opportunities to execute to maximize mission value subject to
conflicts and resource limits — is representative, has a clean 0/1 decision structure
(one binary per opportunity), and maps naturally to a QUBO.

## Decision
- Model the problem with typed domain models (`optimization/models.py`):
  `SchedulingProblem`, `ObservationOpportunity` (stable id, satellite, target, time
  window, mission value, duration, energy/storage/pointing cost, priority, source,
  provenance, limitations), `SatelliteResource`, `ObservationTarget`, `TimeWindow`,
  `ConstraintSet`, `SchedulingObjective`, `SchedulingProblemLimits`.
- One binary decision variable per opportunity; the **stable variable order is the
  opportunity ids sorted lexicographically** (the bit-order convention for all encoding
  and decoding).
- Instances are **bounded, deterministic, bundled fixtures** (`optimization/fixtures.py`).
  The benchmark never requires live CelesTrak/JPL access.
- A deterministic content `checksum` (`problem.py`) identifies a normalized instance so
  every solver provably runs the same problem.

## Alternatives considered
1. **Use a live tasking scenario from CelesTrak/JPL.** Non-deterministic, network-
   dependent, far larger than a bounded quantum experiment can handle. Rejected.
2. **A generic max-cut/knapsack toy.** Less faithful to OrbitMind's domain. Rejected in
   favour of a real scheduling structure kept tiny.

## Consequences
- A small, reproducible problem family suitable for exhaustive verification and a few-
  qubit QAOA circuit.
- This is a **bounded experiment**, not an operational tasking system; results never
  drive a production mission (ADR-0027/0028).

## Review trigger
Revisit when scheduling needs exceed exhaustively-verifiable sizes, or when operational
tasking (not a benchmark) is in scope.
