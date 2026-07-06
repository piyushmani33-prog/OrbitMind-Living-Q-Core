"""Local terminal demo for Quantum Simulator v0 (Qiskit-free, numpy-backed).

Builds a Bell state, prints the deterministic statevector amplitudes, and shows
seeded measurement counts using only the public simulator API.

Local simulator only — NOT a quantum-advantage claim and NOT a hardware/QPU
result. See ``docs/quantum/SIMULATOR_V0_USAGE.md``.

Run:
    python examples/quantum_simulator_v0_demo.py
"""

from __future__ import annotations

from orbitmind.quantum.simulator import Circuit, StatevectorSimulator

_AMPLITUDE_TOLERANCE = 1e-9
_SHOTS = 1000
_SEED = 1234


def main() -> None:
    simulator = StatevectorSimulator()

    # Bell circuit: H on qubit 0, then CNOT (control = 0, target = 1).
    circuit = Circuit(2).h(0).cx(0, 1)

    print("OrbitMind - Quantum Simulator v0 demo")
    print("=" * 40)
    print("Circuit: 2 qubits; H(0); CNOT(0 -> 1)   (a Bell state)")
    print("Bit-order: qubit 0 is the LEFT-most bit (e.g. '10' means q0=1, q1=0).")
    print()

    result = simulator.run(circuit)
    width = result.num_qubits
    print("Nonzero statevector amplitudes (deterministic):")
    for index, amplitude in enumerate(result.amplitudes):
        if abs(amplitude) > _AMPLITUDE_TOLERANCE:
            label = format(index, f"0{width}b")
            amp = f"{amplitude.real:+.4f}{amplitude.imag:+.4f}j"
            print(f"  |{label}>: amplitude={amp}  p={abs(amplitude) ** 2:.4f}")
    print()

    measurement = simulator.measure(circuit, shots=_SHOTS, seed=_SEED)
    print(f"Seeded measurement (shots={measurement.shots}, seed={measurement.seed}):")
    for outcome in sorted(measurement.counts):
        print(f"  {outcome}: {measurement.counts[outcome]}")
    print("  (exact counts vary by NumPy version; the same seed is reproducible locally.)")
    print()

    print("Safety note:")
    print("  - Local simulator only (numpy-backed, Qiskit-free).")
    print("  - NOT a quantum-advantage claim.")
    print("  - NOT a hardware/QPU result.")


if __name__ == "__main__":
    main()
