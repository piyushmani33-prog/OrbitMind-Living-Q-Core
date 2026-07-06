"""Circuit and gate-operation value objects for the v0 statevector simulator.

Bit-order convention (pinned): qubit index 0 is the LEFT-MOST bit of an output
bitstring and the most-significant basis index. For a 2-qubit circuit the basis
order is ``"00", "01", "10", "11"`` where the first character is qubit 0. The Bell
circuit ``H(0); CNOT(0, 1)`` therefore yields only ``"00"`` and ``"11"``.

Circuits are immutable, frozen value objects. Structural problems raise the
sanitized :class:`InvalidCircuitError` (safe static messages only).
"""

from __future__ import annotations

from dataclasses import dataclass

from orbitmind.quantum.simulator.errors import InvalidCircuitError
from orbitmind.quantum.simulator.gates import SINGLE_QUBIT_KINDS, GateKind

_MIN_QUBITS = 1
_MAX_QUBITS = 3


@dataclass(frozen=True, slots=True)
class GateOp:
    """A single gate application.

    ``targets`` is ``(qubit,)`` for X/H/Z and ``(control, target)`` for CNOT.
    """

    kind: GateKind
    targets: tuple[int, ...]

    def __post_init__(self) -> None:
        if any(target < 0 for target in self.targets):
            raise InvalidCircuitError("target qubit index out of range for the circuit width")
        if self.kind in SINGLE_QUBIT_KINDS:
            if len(self.targets) != 1:
                raise InvalidCircuitError("single-qubit gate requires exactly one target qubit")
        elif self.kind is GateKind.CNOT:
            if len(self.targets) != 2:
                raise InvalidCircuitError("CNOT requires exactly two target qubits")
            if self.targets[0] == self.targets[1]:
                raise InvalidCircuitError("CNOT control and target qubits must differ")


@dataclass(frozen=True, slots=True)
class Circuit:
    """An ordered list of gate operations over ``num_qubits`` (1-3) qubits."""

    num_qubits: int
    ops: tuple[GateOp, ...] = ()

    def __post_init__(self) -> None:
        if self.num_qubits < _MIN_QUBITS or self.num_qubits > _MAX_QUBITS:
            raise InvalidCircuitError("num_qubits must be 1, 2, or 3")
        for op in self.ops:
            if any(target >= self.num_qubits for target in op.targets):
                raise InvalidCircuitError("target qubit index out of range for the circuit width")

    def _add(self, op: GateOp) -> Circuit:
        return Circuit(num_qubits=self.num_qubits, ops=(*self.ops, op))

    def x(self, qubit: int) -> Circuit:
        """Return a new circuit with an X gate appended on ``qubit``."""
        return self._add(GateOp(kind=GateKind.X, targets=(qubit,)))

    def h(self, qubit: int) -> Circuit:
        """Return a new circuit with an H gate appended on ``qubit``."""
        return self._add(GateOp(kind=GateKind.H, targets=(qubit,)))

    def z(self, qubit: int) -> Circuit:
        """Return a new circuit with a Z gate appended on ``qubit``."""
        return self._add(GateOp(kind=GateKind.Z, targets=(qubit,)))

    def cx(self, control: int, target: int) -> Circuit:
        """Return a new circuit with a CNOT (control -> target) appended."""
        return self._add(GateOp(kind=GateKind.CNOT, targets=(control, target)))
