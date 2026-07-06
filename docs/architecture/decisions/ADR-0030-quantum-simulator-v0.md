# ADR-0030 — Quantum Simulator v0

- **Status:** Accepted (2026-07-06)

## Context
OrbitMind already has a bounded, optional Qiskit adapter (ADR-0005) used only for a
capability self-test and a later, baseline-gated optimization experiment. That path
requires the heavy `qiskit`/`qiskit-aer` extra and is not suited to a small, always-on,
fully-deterministic teaching/experiment seam. A minimal, dependency-light simulator is
useful for exercising basic quantum-circuit behavior in the default offline test suite
without adding any dependency (numpy is already core) and without touching the mission
workflow.

## Decision
Add a local, **pure-Python, numpy-only, Qiskit-free** statevector simulator under
`src/orbitmind/quantum/simulator/`:

- Gates: **X, H, Z** (single-qubit) and **CNOT** (two-qubit); numpy `complex128` matrices.
- Circuits of **1–3 qubits**; deterministic statevector output.
- **Seeded** measurement counts via `numpy.random.default_rng(seed)` — the same circuit,
  shots, and seed always produce the same counts.
- **Bit-order (pinned):** qubit index 0 is the left-most output bit / most-significant
  basis index. The Bell circuit `H(0); CNOT(0, 1)` yields only `"00"` and `"11"`.
- **Sanitized errors:** `InvalidCircuitError` (`invalid_quantum_circuit`) and
  `InvalidMeasurementError` (`invalid_quantum_measurement`), derived from the platform's
  `ValidationError`; messages are safe static strings (no paths, stack traces, secrets,
  SQL, or environment details).

## Scope (v0)
- Statevector simulation and seeded measurement for ≤3-qubit circuits over X/H/Z/CNOT.
- Circuit/measurement validation with sanitized errors.
- Offline, deterministic unit tests (no marker, no Qiskit, no PostgreSQL).

## Out of scope
- **No API**, no CLI, no UI/frontend.
- **No persistence**, no database, **no migration**.
- **No provider, cloud, QPU, or IBM Quantum** integration; **no Qiskit requirement**.
- Gates beyond X/H/Z/CNOT; more than 3 qubits; noise models; density matrices.
- **No QAOA / optimization / quantum-advantage benchmarking** (that remains the separate,
  classical-baseline-gated optimization concern).
- **No coupling to the mission/orbit workflow** — the mission path does not import the
  simulator (enforced by test).

## Relationship to ADR-0005
This ADR does **not** alter ADR-0005's decision or its Phase-4 review trigger. It adds a
complementary, Qiskit-free simulator inside the same bounded, simulator-only, off-mission
quantum boundary. The Qiskit adapter and `quantum_available()` are unchanged, and the
orbital slice still must not import the `quantum` module.

## Safety / no-overclaim
The simulator is simulator-only and deterministic. It makes **no quantum-advantage claim**
and **no command-readiness, approval, or certification claim**; results are deterministic
calculations. There is no classical-baseline comparison in v0, and none is claimed.

## Consequences
- Adds a small, fully-tested quantum seam with **no new dependency** and no impact on
  mission reliability, the API, persistence, or migrations (Alembic head unchanged).
- Boundary guards (no Qiskit import in the simulator; no simulator import on the mission
  path) run in the default offline suite on every push.

## Review trigger
Revisit if a real consumer needs more qubits/gates, a persisted record, or an API — each
of which requires its own reviewed contract.
