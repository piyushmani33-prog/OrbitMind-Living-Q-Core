"""Bell-state smoke experiment (ISOLATED from production mission logic).

This script is NOT imported by the application and never runs on an API request.
It demonstrates the bounded quantum adapter boundary (ADR-0005): a Qiskit Aer
*simulator* experiment, compared against the classical expectation. It contacts no
real hardware.

Run manually:
    python experiments/quantum/bell_state.py
"""

from __future__ import annotations

from orbitmind.quantum.adapter import QuantumAdapter, quantum_available

SHOTS = 1024
SEED = 42


def run_bell_state() -> dict[str, int]:
    """Build/measure a 2-qubit Bell state on AerSimulator; return measured counts."""
    from qiskit import QuantumCircuit, transpile
    from qiskit_aer import AerSimulator

    circuit = QuantumCircuit(2, 2)
    circuit.h(0)
    circuit.cx(0, 1)
    circuit.measure([0, 1], [0, 1])

    simulator = AerSimulator()
    compiled = transpile(circuit, simulator)
    result = simulator.run(compiled, shots=SHOTS, seed_simulator=SEED).result()
    counts: dict[str, int] = result.get_counts()
    return counts


def main() -> int:
    selftest = QuantumAdapter().self_test()
    print(f"quantum available: {quantum_available()} | self-test: {selftest.detail}")
    if not selftest.available:
        print("Qiskit/Aer unavailable; skipping experiment.")
        return 0

    counts = run_bell_state()
    print(f"measured counts (shots={SHOTS}, seed={SEED}): {counts}")

    # Classical baseline/expectation for an ideal Bell state: only |00> and |11>,
    # each ~50%. Compare the simulator outcome against that expectation.
    entangled = counts.get("00", 0) + counts.get("11", 0)
    leakage = SHOTS - entangled
    print(
        f"classical expectation: ~50/50 over {{'00','11'}}, no '01'/'10'. "
        f"observed entangled={entangled}/{SHOTS}, off-state leakage={leakage}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
