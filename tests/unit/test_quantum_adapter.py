"""Unit tests for the bounded quantum adapter (ADR-0005).

Marked ``quantum`` since they exercise the optional Qiskit/Aer dependency. The
adapter self-test must never run on an API request and never contacts hardware.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from orbitmind.quantum.adapter import QuantumAdapter, quantum_available


def test_quantum_available_is_boolean() -> None:
    assert isinstance(quantum_available(), bool)


@pytest.mark.quantum
def test_self_test_reports_simulator_only() -> None:
    result = QuantumAdapter().self_test()
    if not quantum_available():  # environment without qiskit
        assert result.available is False
        return
    assert result.available is True
    assert result.qiskit_version is not None
    assert "hardware" in result.detail.lower()  # explicitly simulator-only


def test_orbital_slice_does_not_import_quantum() -> None:
    # Guard: importing the orchestrator must not pull in qiskit-heavy modules.
    import importlib

    orchestrator = importlib.import_module("orbitmind.orchestration.orchestrator")
    source = orchestrator.__file__
    assert source is not None
    text = Path(source).read_text(encoding="utf-8")
    assert "qiskit" not in text
    assert "orbitmind.quantum" not in text
