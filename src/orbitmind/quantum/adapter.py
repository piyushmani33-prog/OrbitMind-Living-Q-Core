"""Bounded quantum adapter + capability self-test (ADR-0005).

``quantum_available()`` is a cheap, import-free presence check suitable for the
health/capabilities endpoints. ``QuantumAdapter.self_test()`` actually imports
Qiskit + AerSimulator and is invoked ONLY on explicit request (CLI/experiment),
never on an ordinary API request, and never contacts real hardware.
"""

from __future__ import annotations

import importlib.util
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version

from orbitmind.quantum.models import QuantumSelfTestResult


@lru_cache(maxsize=1)
def quantum_available() -> bool:
    """True if the Qiskit + Aer packages are importable (no heavy import performed)."""
    return (
        importlib.util.find_spec("qiskit") is not None
        and importlib.util.find_spec("qiskit_aer") is not None
    )


def _safe_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


class QuantumAdapter:
    """A deliberately small surface over the quantum backend (simulator-first)."""

    def self_test(self) -> QuantumSelfTestResult:
        """Import Qiskit + AerSimulator and report availability. Runs no hardware."""
        if not quantum_available():
            return QuantumSelfTestResult(available=False, detail="qiskit/qiskit-aer not installed")
        try:
            import qiskit  # noqa: F401  (import is the test)
            from qiskit_aer import AerSimulator

            AerSimulator()  # construct a local simulator; does not contact hardware
        except Exception as exc:
            return QuantumSelfTestResult(available=False, detail=f"import failed: {exc}")
        return QuantumSelfTestResult(
            available=True,
            qiskit_version=_safe_version("qiskit"),
            aer_version=_safe_version("qiskit-aer"),
            detail="AerSimulator constructed (simulator only, no hardware)",
        )
