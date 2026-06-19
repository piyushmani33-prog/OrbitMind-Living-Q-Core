"""Verification finding domain model."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Severity(StrEnum):
    """How serious a failed check is."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class FindingStatus(StrEnum):
    """Outcome of a verification check."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class VerificationFinding(BaseModel):
    """Result of a single deterministic verification check."""

    model_config = ConfigDict(frozen=True)

    check_id: str
    severity: Severity
    status: FindingStatus
    explanation: str
    values: dict[str, Any] = Field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status is FindingStatus.PASSED
