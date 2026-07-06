# Quantum Simulator v0 — Usage

A tiny, local, deterministic quantum **statevector simulator** you can run in a
terminal to see basic quantum-circuit behavior. It is intentionally minimal.

## What this is
- Local-only, **numpy-backed**, **Qiskit-free** simulator.
- 1–3 qubits; gates **X, H, Z, CNOT**.
- Deterministic statevector output and **seeded** measurement counts.
- Bit-order: **qubit 0 is the left-most bit** of an output bitstring (so `"10"`
  means qubit 0 = 1, qubit 1 = 0).

## What this is not
- Not connected to the mission/orbit workflow.
- Not an API, database, migration, UI, CLI framework, or provider integration.
- **No QPU / hardware**, **no cloud/provider**, **no IBM Quantum**, no new dependency.
- **Not a quantum-advantage claim**, not production-ready, and not a
  command-readiness / approval / certification result.

## Run the demo

### Windows (PowerShell / cmd)
```bat
.venv\Scripts\python.exe examples\quantum_simulator_v0_demo.py
```

### macOS / Linux
```bash
source .venv/bin/activate
python examples/quantum_simulator_v0_demo.py
```

(If you have not created the virtual environment yet, see the root `README.md`
installation section first.)

## Expected output shape
The exact numbers of the seeded counts can differ across NumPy versions, so treat
the block below as the **shape** of the output, not exact values:

```text
OrbitMind — Quantum Simulator v0 demo
========================================
Circuit: 2 qubits; H(0); CNOT(0 -> 1)   (a Bell state)
Bit-order: qubit 0 is the LEFT-most bit (e.g. '10' means q0=1, q1=0).

Nonzero statevector amplitudes (deterministic):
  |00>: amplitude=+0.7071+0.0000j  p=0.5000
  |11>: amplitude=+0.7071+0.0000j  p=0.5000

Seeded measurement (shots=1000, seed=1234):
  00: <about half>
  11: <about half>
  (exact counts vary by NumPy version; the same seed is reproducible locally.)

Safety note:
  - Local simulator only (numpy-backed, Qiskit-free).
  - NOT a quantum-advantage claim.
  - NOT a hardware/QPU result.
```

The **amplitudes are deterministic** (always `|00>` and `|11>` at ≈0.7071). The
**measurement counts are seeded**: the same seed reproduces the same counts on one
machine, but the exact split is not guaranteed identical across NumPy versions.

## Bell state, in simple terms
The circuit applies **H** to qubit 0 (putting it into an equal superposition of 0
and 1) and then a **CNOT** from qubit 0 to qubit 1 (which flips qubit 1 only when
qubit 0 is 1). The two qubits become **correlated**: a measurement yields only
`00` or `11`, never `01` or `10`. That correlation is the defining feature of a
Bell state.

## Safety boundaries
- **Local-only** and **simulator-only** — pure numpy statevector math.
- **No QPU / hardware**, **no provider / cloud**, no IBM Quantum.
- **No quantum-advantage claim.**
- **No coupling to the mission/orbit workflow** (the mission path does not import
  the simulator; enforced by test).
- **No command-readiness, approval, or certification** claim.

See `docs/architecture/decisions/ADR-0030-quantum-simulator-v0.md` (and ADR-0005)
for the bounded scope.
