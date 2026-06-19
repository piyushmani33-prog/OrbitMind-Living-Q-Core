"""Approval domain model (human-in-the-loop boundary, SR-18).

Modeled now; Phase 1 missions are read-only deterministic compute and require no
approval. The model exists so future risky actions can be gated.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow


class ApprovalStatus(StrEnum):
    """State of a human-approval request."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRecord(BaseModel):
    """A request for human approval of a risky action."""

    id: str = Field(default_factory=new_id)
    subject_ref: str
    requested_by: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=utcnow)
    decided_by: str | None = None
    decided_at: datetime | None = None
