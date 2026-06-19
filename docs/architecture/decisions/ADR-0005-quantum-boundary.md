# ADR-0005 — Quantum Boundary

- **Status:** Accepted (2026-06-19)

## Context
"Q-Core" branding invites overuse of quantum computation. The specification is
explicit: quantum is **not** the main cognition engine, classical methods are the
default, Qiskit is a bounded adapter, simulation precedes hardware, and every
quantum result must be compared against a classical baseline.

## Decision
- Provide a **bounded `QuantumAdapter` interface** in `quantum` plus a
  **capability self-test** (imports Qiskit + AerSimulator, reports availability).
- The self-test is **never executed on API requests**; it runs only when invoked
  explicitly (CLI/experiment) and **never contacts real hardware**.
- The orbital vertical slice **does not depend on Qiskit** and does not import the
  `quantum` module.
- An optional Bell-state smoke experiment lives under `experiments/quantum`,
  isolated from production mission logic.
- **No QAOA / quantum optimization** until a later milestone (Phase 4) that
  includes a classical baseline and a reproducible objective + wall-clock
  comparison. No "quantum advantage" claim without that evidence.

## Alternatives considered
1. **Quantum on the mission path now.** Would be quantum-for-appearance with no
   classical baseline. Rejected (violates spec).
2. **Omit quantum entirely.** Loses the designed seam and the version self-test the
   spec asks for. Rejected.

## Consequences
- Mission reliability/perf is unaffected by Qiskit; the heavy `qiskit`/`qiskit-aer`
  deps are an optional extra (`pip install -e .[quantum]`), already present locally.
- A clear, auditable path exists for adding benchmarked quantum experiments later.

## Review trigger
Revisit at Phase 4 when introducing a QUBO/graph optimization problem with a
classical baseline.
