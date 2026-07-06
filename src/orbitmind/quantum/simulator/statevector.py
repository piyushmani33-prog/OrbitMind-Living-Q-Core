"""Deterministic, local statevector simulator (v0) — numpy only, no Qiskit.

Simulator-only, off the mission/orbit path. Not a quantum-advantage claim and not
command/readiness/approval/certification. See ADR-0030 and ADR-0005.

Bit-order: qubit 0 is the most-significant basis index / left-most output bit
(see :mod:`orbitmind.quantum.simulator.circuit`). The statevector path is pure
linear algebra with no randomness, so it is fully deterministic. Measurement is
seeded (``numpy.random.default_rng(seed)``): the same circuit, shots, and seed
always produce the same counts.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from orbitmind.quantum.simulator.circuit import Circuit
from orbitmind.quantum.simulator.errors import InvalidMeasurementError
from orbitmind.quantum.simulator.gates import SINGLE_QUBIT_MATRICES, GateKind


@dataclass(frozen=True, slots=True)
class StatevectorResult:
    """The deterministic amplitudes of a simulated circuit."""

    num_qubits: int
    amplitudes: tuple[complex, ...]


@dataclass(frozen=True, slots=True)
class MeasurementResult:
    """Seeded measurement counts keyed by big-endian (qubit 0 = left) bitstring."""

    shots: int
    seed: int
    counts: dict[str, int]


def _apply_single_qubit(
    state: NDArray[np.complex128],
    matrix: NDArray[np.complex128],
    qubit: int,
    num_qubits: int,
) -> NDArray[np.complex128]:
    tensor = state.reshape((2,) * num_qubits)
    contracted = np.tensordot(matrix, tensor, axes=([1], [qubit]))
    moved = np.moveaxis(contracted, 0, qubit)
    return np.asarray(moved, dtype=np.complex128).reshape(2**num_qubits)


def _apply_cnot(
    state: NDArray[np.complex128],
    control: int,
    target: int,
    num_qubits: int,
) -> NDArray[np.complex128]:
    indices = np.arange(2**num_qubits)
    control_bit = 1 << (num_qubits - 1 - control)
    target_bit = 1 << (num_qubits - 1 - target)
    control_set = (indices & control_bit) != 0
    result = state.copy()
    # CNOT is an involution: for control-set indices, take the amplitude from the
    # index with the target bit flipped.
    result[control_set] = state[indices[control_set] ^ target_bit]
    return result


class StatevectorSimulator:
    """A deterministic statevector simulator for small (<=3 qubit) circuits."""

    def run(self, circuit: Circuit) -> StatevectorResult:
        """Simulate ``circuit`` from |0...0> and return the amplitudes (no randomness)."""
        state: NDArray[np.complex128] = np.zeros(2**circuit.num_qubits, dtype=np.complex128)
        state[0] = 1.0
        for op in circuit.ops:
            if op.kind is GateKind.CNOT:
                state = _apply_cnot(state, op.targets[0], op.targets[1], circuit.num_qubits)
            else:
                matrix = SINGLE_QUBIT_MATRICES[op.kind]
                state = _apply_single_qubit(state, matrix, op.targets[0], circuit.num_qubits)
        return StatevectorResult(
            num_qubits=circuit.num_qubits,
            amplitudes=tuple(complex(amplitude) for amplitude in state),
        )

    def measure(self, circuit: Circuit, *, shots: int, seed: int) -> MeasurementResult:
        """Return seeded measurement counts. Same circuit + shots + seed -> same counts.

        ``seed`` is a required keyword-only integer (explicit by construction).
        """
        if shots <= 0:
            raise InvalidMeasurementError("shots must be a positive integer")
        result = self.run(circuit)
        amplitudes = np.asarray(result.amplitudes, dtype=np.complex128)
        probabilities: NDArray[np.float64] = (np.abs(amplitudes) ** 2).astype(np.float64)
        probabilities = probabilities / float(np.sum(probabilities))
        rng = np.random.default_rng(seed)
        outcomes = rng.choice(probabilities.shape[0], size=shots, p=probabilities)
        counts: dict[str, int] = {}
        width = circuit.num_qubits
        for outcome in outcomes:
            key = format(int(outcome), f"0{width}b")
            counts[key] = counts.get(key, 0) + 1
        return MeasurementResult(shots=shots, seed=seed, counts=counts)
