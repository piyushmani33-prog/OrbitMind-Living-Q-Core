"""Quantum experiment domain model (modeled; not produced by the orbital slice)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow


class QuantumSelfTestResult(BaseModel):
    """Outcome of the quantum capability self-test."""

    available: bool
    qiskit_version: str | None = None
    aer_version: str | None = None
    detail: str = ""


class QuantumExperimentRecord(BaseModel):
    """Record of a (future) bounded quantum experiment with a classical baseline."""

    id: str = Field(default_factory=new_id)
    name: str
    backend: str  # e.g. "AerSimulator" (simulator-first; no hardware)
    shots: int
    classical_baseline_ref: str  # every quantum result requires a classical baseline
    result_summary: dict[str, float] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
