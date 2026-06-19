"""Audit event domain model and action vocabulary (NFR-11)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow


class AuditAction(StrEnum):
    """Mission lifecycle audit actions."""

    MISSION_SUBMITTED = "mission.submitted"
    MISSION_VALIDATED = "mission.validated"
    WORKFLOW_STARTED = "workflow.started"
    PROPAGATION_COMPLETED = "propagation.completed"
    PROPAGATION_FAILED = "propagation.failed"
    VERIFICATION_COMPLETED = "verification.completed"
    ARTIFACT_GENERATED = "artifact.generated"
    MISSION_COMPLETED = "mission.completed"
    MISSION_FAILED = "mission.failed"


class AuditEvent(BaseModel):
    """An append-only record of a lifecycle transition."""

    id: str = Field(default_factory=new_id)
    mission_id: str | None = None
    action: AuditAction
    actor: str = "system"
    detail: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)
