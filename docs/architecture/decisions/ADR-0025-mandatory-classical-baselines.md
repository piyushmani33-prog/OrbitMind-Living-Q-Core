# ADR-0025 — Mandatory Classical Baselines for Every Quantum Experiment

- **Status:** Accepted (2026-06-21)

## Context
A quantum result is meaningless without a classical reference on the *same* problem. The
project invariant (ADR-0005, AGENTS.md) requires a classical baseline for every quantum
experiment, and forbids treating quantum output as authoritative.

## Decision
- Every benchmark runs **two deterministic classical solvers** on the same normalized
  instance before/alongside any quantum experiment:
  - **Exact** (`solvers/exact.py`): exhaustive enumeration of all `2^n` subsets — the
    **proven optimum and ground truth** for instances within `exact_max_variables`. It is
    deterministic, has a hard size cap (returns `unsupported` above it), and a wall-clock
    timeout (returns `timed-out` with a feasible, not-proven result).
  - **Greedy** (`solvers/greedy.py`): a deterministic heuristic with a fixed documented
    ordering (mandatory first, then value-density desc, value desc, id asc) and fixed
    tie-breaking; **no randomness**.
- Every solver's schedule (classical OR quantum) is **independently re-evaluated by the
  shared deterministic `Evaluator`**; a solver's own feasibility/objective claim is never
  trusted (a result failing verification is not marked successful).
- The exact solver is ground truth **only** for instances small enough to enumerate.

## Alternatives considered
1. **A single classical heuristic.** Without the exact optimum we cannot state an honest
   optimality gap. Rejected.
2. **Trust solver-reported feasibility.** Violates the verification invariant; a buggy or
   adversarial solver could over-report. Rejected — the independent evaluator re-checks.

## Consequences
- Every quantum result has a proven optimum (when small enough) and a heuristic to
  compare against; the comparison conclusion is grounded, not asserted.

## Review trigger
Revisit if instances grow beyond exhaustive search (would need a branch-and-bound or ILP
baseline to retain a ground-truth reference).
