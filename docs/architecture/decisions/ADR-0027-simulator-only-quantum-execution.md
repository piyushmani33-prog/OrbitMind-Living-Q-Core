# ADR-0027 — Simulator-Only Quantum Execution

- **Status:** Accepted (2026-06-21)

## Context
The quantum layer must remain bounded, reproducible, and off the production mission path
(ADR-0005). Real hardware introduces accounts, API keys, network calls, queueing, and
non-reproducibility — none acceptable in this phase.

## Decision
- The quantum experiment runs **only on the locally installed Qiskit Aer simulator**
  (Qiskit **2.4.2**, qiskit-aer **0.17.2**). **No real hardware, no IBM account, no API
  key, no external network request.**
- The installed APIs were inspected before implementation. We build a **manual QAOA
  circuit** (`h`, `rz`, `rzz`, `rx`, `measure_all`) and sample with
  `qiskit_aer.primitives.SamplerV2(seed=...)` — `qiskit_algorithms`/`qiskit-optimization`
  are **not installed** and are **not added** (avoiding an abandoned/incompatible
  dependency; section 20). No new dependency was introduced.
- Parameters are chosen by a **deterministic, bounded** grid (p=1) / seeded search (p>1),
  not a stochastic optimizer, so runs are reproducible. Fixed `seed`, `seed_simulator`,
  and `seed_transpiler` are recorded, along with qubit count, circuit depth, gate counts,
  shots, optimizer iterations, backend, and transpile level.
- **The quantum layer is an experimental *adapter*, not OrbitMind's cognition engine.**
  OrbitMind's intelligence is the deterministic spine (intake → orchestration → domain
  tools → verification → evidence/memory). The quantum adapter is a bounded, optional,
  simulator-only comparison that is recorded and verified; an experimental quantum result
  **never directly controls a production mission**.
- If the installed Qiskit could not safely support the approach, we would stop and report
  the exact compatibility issue rather than invent unsupported APIs.

## Alternatives considered
1. **Real IBM Quantum hardware.** Network/account/key, queueing, non-reproducible, out of
   scope. Rejected.
2. **`qiskit-algorithms` QAOA / `qiskit-optimization`.** Not installed; would add a
   dependency and hide the circuit. Rejected — a manual circuit is small and fully
   inspectable on the installed Qiskit 2.x.

## Consequences
- Deterministic, offline, reproducible experiments with full circuit provenance; results
  are clearly labelled as simulator output that does not demonstrate hardware advantage.

## Review trigger
Revisit only if a future phase explicitly scopes real-hardware experiments behind the
existing capability adapter, with their own ADR and safety review.
