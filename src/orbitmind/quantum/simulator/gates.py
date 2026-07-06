"""Gate definitions for the local, Qiskit-free statevector simulator (v0).

Only X, H, Z (single-qubit) and CNOT (two-qubit) are supported. Gate matrices are
numpy ``complex128``. No Qiskit, no provider, no hardware.
"""

from __future__ import annotations

from enum import StrEnum

import numpy as np
from numpy.typing import NDArray


class GateKind(StrEnum):
    """The gates supported by Quantum Simulator v0."""

    X = "x"
    H = "h"
    Z = "z"
    CNOT = "cnot"


SINGLE_QUBIT_KINDS: frozenset[GateKind] = frozenset({GateKind.X, GateKind.H, GateKind.Z})

_INV_SQRT2: float = float(1.0 / np.sqrt(2.0))

PAULI_X: NDArray[np.complex128] = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=np.complex128)
HADAMARD: NDArray[np.complex128] = np.array(
    [[_INV_SQRT2, _INV_SQRT2], [_INV_SQRT2, -_INV_SQRT2]], dtype=np.complex128
)
PAULI_Z: NDArray[np.complex128] = np.array([[1.0, 0.0], [0.0, -1.0]], dtype=np.complex128)

SINGLE_QUBIT_MATRICES: dict[GateKind, NDArray[np.complex128]] = {
    GateKind.X: PAULI_X,
    GateKind.H: HADAMARD,
    GateKind.Z: PAULI_Z,
}
