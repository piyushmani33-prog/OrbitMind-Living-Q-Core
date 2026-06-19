"""Workflow domain models for the in-process deterministic engine (ADR-0004)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow


class WorkflowStatus(StrEnum):
    """Overall workflow run state."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class WorkflowStep(BaseModel):
    """One recorded step in a workflow run (lightweight trace substitute)."""

    name: str
    status: str  # ok | error
    started_at: datetime
    finished_at: datetime
    detail: dict[str, Any] = Field(default_factory=dict)


class WorkflowRun(BaseModel):
    """A deterministic, step-logged workflow execution."""

    id: str = Field(default_factory=new_id)
    mission_id: str
    workflow_name: str
    status: WorkflowStatus = WorkflowStatus.RUNNING
    steps: list[WorkflowStep] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
