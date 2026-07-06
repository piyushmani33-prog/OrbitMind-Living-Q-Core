"""Local, deterministic, Qiskit-free statevector simulator (v0). See ADR-0030.

Simulator-only, off the mission/orbit path, no API/persistence/provider/QPU, and
no quantum-advantage or command/readiness/approval/certification claim.
"""

from orbitmind.quantum.simulator.circuit import Circuit, GateOp
from orbitmind.quantum.simulator.errors import InvalidCircuitError, InvalidMeasurementError
from orbitmind.quantum.simulator.gates import GateKind
from orbitmind.quantum.simulator.statevector import (
    MeasurementResult,
    StatevectorResult,
    StatevectorSimulator,
)

__all__ = [
    "Circuit",
    "GateKind",
    "GateOp",
    "InvalidCircuitError",
    "InvalidMeasurementError",
    "MeasurementResult",
    "StatevectorResult",
    "StatevectorSimulator",
]
