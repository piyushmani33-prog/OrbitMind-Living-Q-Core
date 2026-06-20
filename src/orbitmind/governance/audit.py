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

    # Phase 2 — external source access
    SOURCE_ACCESS_REQUESTED = "source.access_requested"
    NETWORK_REJECTED = "source.network_rejected"
    CACHE_HIT = "source.cache_hit"
    CACHE_MISS = "source.cache_miss"
    REFRESH_SUPPRESSED = "source.refresh_suppressed"
    SOURCE_REQUEST_STARTED = "source.request_started"
    SOURCE_REQUEST_COMPLETED = "source.request_completed"
    SOURCE_REQUEST_FAILED = "source.request_failed"
    SOURCE_SCHEMA_REJECTED = "source.schema_rejected"
    RECORD_NORMALIZED = "source.record_normalized"
    STALE_RECORD_USED = "source.stale_record_used"
    EXTERNAL_MISSION_COMPLETED = "mission.external_completed"
    EXTERNAL_MISSION_FAILED = "mission.external_failed"

    # Phase 3A — small-body intelligence
    SMALL_BODY_LOOKUP_REQUESTED = "smallbody.lookup_requested"
    SBDB_QUERY_REQUESTED = "smallbody.sbdb_query_requested"
    CAD_QUERY_REQUESTED = "smallbody.cad_query_requested"
    JPL_REQUEST_STARTED = "smallbody.jpl_request_started"
    JPL_REQUEST_COMPLETED = "smallbody.jpl_request_completed"
    JPL_REQUEST_FAILED = "smallbody.jpl_request_failed"
    SMALL_BODY_NORMALIZED = "smallbody.record_normalized"
    SMALL_BODY_REJECTED = "smallbody.record_rejected"
    OBJECT_PERSISTED = "smallbody.object_persisted"
    CLOSE_APPROACHES_PERSISTED = "smallbody.close_approaches_persisted"
    SMALL_BODY_ARTIFACT_GENERATED = "smallbody.artifact_generated"
    RESULT_SET_TRUNCATED = "smallbody.result_truncated"
    UNSUPPORTED_OBJECT_REJECTED = "smallbody.unsupported_object_rejected"


class AuditEvent(BaseModel):
    """An append-only record of a lifecycle transition."""

    id: str = Field(default_factory=new_id)
    mission_id: str | None = None
    action: AuditAction
    actor: str = "system"
    detail: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)
