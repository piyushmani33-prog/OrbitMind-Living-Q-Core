"""Offline tests for Quantum Simulator v0 (numpy-only, Qiskit-free, deterministic).

These are plain offline unit tests: no ``quantum`` marker, no Qiskit, no
PostgreSQL. They also enforce the ADR-0030 boundaries: the simulator imports no
Qiskit, and the mission/orbit path does not import the simulator.

Bit-order under test: qubit 0 is the left-most output bit (Bell -> "00"/"11").
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pytest

import orbitmind
import orbitmind.quantum.simulator as simulator_pkg
from orbitmind.quantum.simulator import (
    Circuit,
    GateKind,
    GateOp,
    InvalidCircuitError,
    InvalidMeasurementError,
    StatevectorSimulator,
)

_INV_SQRT2 = 1.0 / np.sqrt(2.0)


def _assert_safe(message: str) -> None:
    lowered = message.lower()
    for forbidden in (
        "traceback",
        "/",
        "\\",
        ".py",
        "select ",
        "postgresql://",
        "secret",
        "password",
    ):
        assert forbidden not in lowered, message


def _imported_modules(source: str) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def _prepare(bits: str) -> Circuit:
    """Prepare the computational basis state |bits> using X gates (qubit 0 = left)."""
    circuit = Circuit(len(bits))
    for index, bit in enumerate(bits):
        if bit == "1":
            circuit = circuit.x(index)
    return circuit


# --- statevector behavior -------------------------------------------------
def test_x_gate_flips_zero_to_one() -> None:
    result = StatevectorSimulator().run(Circuit(1).x(0))
    assert np.allclose(result.amplitudes, [0.0, 1.0])


def test_h_creates_equal_superposition() -> None:
    result = StatevectorSimulator().run(Circuit(1).h(0))
    assert np.allclose(result.amplitudes, [_INV_SQRT2, _INV_SQRT2])


def test_z_phase_on_basis_states() -> None:
    sim = StatevectorSimulator()
    assert np.allclose(sim.run(Circuit(1).z(0)).amplitudes, [1.0, 0.0])
    assert np.allclose(sim.run(Circuit(1).x(0).z(0)).amplitudes, [0.0, -1.0])


def test_hzh_equals_x() -> None:
    # HZH = X, so HZH|0> = |1>.
    result = StatevectorSimulator().run(Circuit(1).h(0).z(0).h(0))
    assert np.allclose(result.amplitudes, [0.0, 1.0])


def test_cnot_truth_table() -> None:
    sim = StatevectorSimulator()
    expected = {"00": "00", "01": "01", "10": "11", "11": "10"}
    for source, destination in expected.items():
        amplitudes = sim.run(_prepare(source).cx(0, 1)).amplitudes
        target = np.zeros(4)
        target[int(destination, 2)] = 1.0
        assert np.allclose(amplitudes, target), (source, destination)


def test_bell_state_amplitudes() -> None:
    result = StatevectorSimulator().run(Circuit(2).h(0).cx(0, 1))
    assert np.allclose(result.amplitudes, [_INV_SQRT2, 0.0, 0.0, _INV_SQRT2])


def test_statevector_is_normalized() -> None:
    result = StatevectorSimulator().run(Circuit(3).h(0).h(1).cx(1, 2).z(0))
    amplitudes = np.asarray(result.amplitudes)
    assert np.isclose(np.sum(np.abs(amplitudes) ** 2), 1.0)


# --- measurement behavior -------------------------------------------------
def test_bell_measurement_yields_only_00_and_11() -> None:
    counts = StatevectorSimulator().measure(Circuit(2).h(0).cx(0, 1), shots=200, seed=7).counts
    assert set(counts) <= {"00", "11"}
    assert sum(counts.values()) == 200


def test_seeded_measurement_is_deterministic() -> None:
    sim = StatevectorSimulator()
    circuit = Circuit(2).h(0).cx(0, 1)
    first = sim.measure(circuit, shots=128, seed=42).counts
    second = sim.measure(circuit, shots=128, seed=42).counts
    assert first == second


def test_measurement_counts_sum_to_shots() -> None:
    counts = StatevectorSimulator().measure(Circuit(1).h(0), shots=137, seed=3).counts
    assert sum(counts.values()) == 137
    assert all(len(key) == 1 for key in counts)


# --- sanitized validation errors ------------------------------------------
def test_invalid_num_qubits_is_sanitized() -> None:
    for bad in (0, 4):
        with pytest.raises(InvalidCircuitError) as exc:
            Circuit(bad)
        assert exc.value.code == "invalid_quantum_circuit"
        _assert_safe(exc.value.message)


def test_single_qubit_gate_wrong_arity_is_sanitized() -> None:
    with pytest.raises(InvalidCircuitError) as exc:
        GateOp(kind=GateKind.X, targets=(0, 1))
    assert exc.value.code == "invalid_quantum_circuit"
    _assert_safe(exc.value.message)


def test_cnot_wrong_arity_is_sanitized() -> None:
    with pytest.raises(InvalidCircuitError) as exc:
        GateOp(kind=GateKind.CNOT, targets=(0,))
    assert exc.value.code == "invalid_quantum_circuit"
    _assert_safe(exc.value.message)


def test_target_out_of_range_is_sanitized() -> None:
    with pytest.raises(InvalidCircuitError) as exc:
        Circuit(2, (GateOp(kind=GateKind.X, targets=(5,)),))
    assert exc.value.code == "invalid_quantum_circuit"
    _assert_safe(exc.value.message)


def test_cnot_control_equals_target_is_sanitized() -> None:
    with pytest.raises(InvalidCircuitError) as exc:
        GateOp(kind=GateKind.CNOT, targets=(1, 1))
    assert "differ" in exc.value.message
    _assert_safe(exc.value.message)


def test_nonpositive_shots_is_sanitized() -> None:
    with pytest.raises(InvalidMeasurementError) as exc:
        StatevectorSimulator().measure(Circuit(1).h(0), shots=0, seed=1)
    assert exc.value.code == "invalid_quantum_measurement"
    _assert_safe(exc.value.message)


# --- boundary guards (ADR-0030 / ADR-0005) --------------------------------
def test_simulator_does_not_import_qiskit() -> None:
    simulator_dir = Path(simulator_pkg.__file__).resolve().parent
    for py_file in simulator_dir.glob("*.py"):
        modules = _imported_modules(py_file.read_text(encoding="utf-8"))
        assert not any(module.startswith(("qiskit", "qiskit_aer")) for module in modules), (
            py_file.name
        )


def test_mission_path_does_not_import_simulator() -> None:
    package_root = Path(orbitmind.__file__).resolve().parent
    for package in ("space", "orchestration", "mission", "api"):
        package_dir = package_root / package
        if not package_dir.exists():
            continue
        for py_file in package_dir.rglob("*.py"):
            modules = _imported_modules(py_file.read_text(encoding="utf-8"))
            assert not any(
                module.startswith("orbitmind.quantum.simulator") for module in modules
            ), py_file
