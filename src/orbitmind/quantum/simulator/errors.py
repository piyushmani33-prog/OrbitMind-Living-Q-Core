"""Sanitized validation errors for the local quantum statevector simulator (v0).

These derive from the platform's ``ValidationError`` so their messages stay safe
(no paths, stack traces, secrets, SQL, or environment details). v0 has no API;
the shared base merely preserves a future ``422`` mapping without any change here.
"""

from __future__ import annotations

from orbitmind.core.errors import ValidationError


class InvalidCircuitError(ValidationError):
    """A circuit or gate operation is structurally invalid."""

    code = "invalid_quantum_circuit"


class InvalidMeasurementError(ValidationError):
    """Measurement parameters (shots/seed) are invalid."""

    code = "invalid_quantum_measurement"
