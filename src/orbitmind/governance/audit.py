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

    # Phase 3B — scientific memory
    INGESTION_REQUESTED = "memory.ingestion_requested"
    INGESTION_STARTED = "memory.ingestion_started"
    FILE_ACCEPTED = "memory.file_accepted"
    FILE_REJECTED = "memory.file_rejected"
    DUPLICATE_DETECTED = "memory.duplicate_detected"
    DOCUMENT_VERSION_CREATED = "memory.document_version_created"
    CHUNKING_COMPLETED = "memory.chunking_completed"
    INGESTION_COMPLETED = "memory.ingestion_completed"
    INGESTION_FAILED = "memory.ingestion_failed"
    CLAIM_REGISTERED = "memory.claim_registered"
    EVIDENCE_LINKED = "memory.evidence_linked"
    CONCEPT_REGISTERED = "memory.concept_registered"
    RETRIEVAL_REQUESTED = "memory.retrieval_requested"
    RETRIEVAL_COMPLETED = "memory.retrieval_completed"
    RETRIEVAL_FAILED = "memory.retrieval_failed"
    MEMORY_RESULT_TRUNCATED = "memory.result_truncated"
    GRAPH_TRAVERSAL_REQUESTED = "memory.graph_traversal_requested"

    # Phase 4A — bounded quantum optimization
    OPTIMIZATION_PROBLEM_CREATED = "optimization.problem_created"
    CLASSICAL_SOLVE_REQUESTED = "optimization.classical_solve_requested"
    CLASSICAL_SOLVE_COMPLETED = "optimization.classical_solve_completed"
    QUANTUM_EXPERIMENT_REQUESTED = "optimization.quantum_experiment_requested"
    QUANTUM_EXPERIMENT_COMPLETED = "optimization.quantum_experiment_completed"
    QUANTUM_UNSUPPORTED = "optimization.quantum_unsupported"
    BENCHMARK_REQUESTED = "optimization.benchmark_requested"
    BENCHMARK_COMPLETED = "optimization.benchmark_completed"
    OPTIMIZATION_VERIFIED = "optimization.verified"
    OPTIMIZATION_VERIFICATION_FAILED = "optimization.verification_failed"
    OPTIMIZATION_ARTIFACT_GENERATED = "optimization.artifact_generated"
    BENCHMARK_MEMORY_REGISTERED = "optimization.benchmark_memory_registered"


class AuditEvent(BaseModel):
    """An append-only record of a lifecycle transition."""

    id: str = Field(default_factory=new_id)
    mission_id: str | None = None
    action: AuditAction
    actor: str = "system"
    detail: dict[str, Any] = Field(default_factory=dict)
    at: datetime = Field(default_factory=utcnow)
