"""Immutable domain models for the governed research-learning foundation.

These models are separate from API DTOs and persistence rows. Raw research document
content is accepted only by ``NormalizedResearchDocument`` and is intentionally absent
from every persisted cycle record and user-facing result.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from orbitmind.core.timeutils import ensure_utc
from orbitmind.governance.epistemic import EpistemicStatus

RESEARCH_LEARNING_SCHEMA_VERSION: Literal["governed-research-learning-v1"] = (
    "governed-research-learning-v1"
)
MAX_RESEARCH_DOCUMENTS = 16
MAX_RESEARCH_DOCUMENT_CHARS = 50_000

type UtcDateTime = Annotated[datetime, AfterValidator(ensure_utc)]


class FrozenResearchModel(BaseModel):
    """Strict immutable base for research domain records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ResearchInputType(StrEnum):
    USER_COMMAND = "user_command"
    DOCUMENT = "document"
    OBSERVATION = "observation"
    TELEMETRY = "telemetry"
    SENSOR_READING = "sensor_reading"
    IMAGE_REFERENCE = "image_reference"
    AUDIO_REFERENCE = "audio_reference"
    PROVIDER_RECORD = "provider_record"
    SIMULATION_RESULT = "simulation_result"


class ResearchSourceType(StrEnum):
    USER = "user"
    LOCAL_FIXTURE = "local_fixture"
    APPROVED_PUBLIC_SOURCE = "approved_public_source"
    PROVIDER = "provider"
    SIMULATION = "simulation"


class ConsentScope(StrEnum):
    EXPLICIT_RESEARCH = "explicit_research"
    MISSION_ONLY = "mission_only"
    INTERNAL_TEST = "internal_test"


class PrivacyClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class RetentionClass(StrEnum):
    TRANSIENT = "transient"
    RESEARCH_RECORD = "research_record"
    MISSION_RECORD = "mission_record"


class ResearchInputStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class ResearchDocumentAvailability(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ResearchEvidenceType(StrEnum):
    DOCUMENT = "document"
    TRAJECTORY_SOURCE = "trajectory_source"
    OBSERVER_CONTEXT = "observer_context"
    OBSERVATION = "observation"
    TELEMETRY = "telemetry"
    SENSOR_READING = "sensor_reading"
    PROVIDER_RECORD = "provider_record"
    SIMULATION_RESULT = "simulation_result"


class EvidenceReliabilityStatus(StrEnum):
    ACCEPTED = "accepted"
    CONFLICTING = "conflicting"
    UNVERIFIED = "unverified"


class ResearchGapType(StrEnum):
    SOURCE_UNAVAILABLE = "source_unavailable"
    INVALID_CHECKSUM = "invalid_checksum"
    MISSING_CONTENT = "missing_content"
    MISSING_SOURCE_METADATA = "missing_source_metadata"
    MISSING_TIME_RANGE = "missing_time_range"
    CONFLICTING_IDENTITY = "conflicting_identity"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    UNSUPPORTED_FORMAT = "unsupported_format"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    RIGHTS_UNCONFIRMED = "rights_unconfirmed"


class ResearchClaimType(StrEnum):
    COMMUNICATION_WINDOW = "communication_window"
    EVIDENCE_CONFLICT = "evidence_conflict"


class ConfidenceLabel(StrEnum):
    SUPPORTED = "supported"
    LIMITED = "limited"
    INDETERMINATE = "indeterminate"


class ClaimVerifierStatus(StrEnum):
    NOT_RUN = "not_run"
    SUPPORTED = "supported"
    SUPPORTED_WITH_GAPS = "supported_with_gaps"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    REJECTED = "rejected"


class ResearchLearningStatus(StrEnum):
    RECORDED = "recorded"
    PARTIAL = "partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ResearchMetadataItem(FrozenResearchModel):
    """One bounded metadata item with deterministic tuple ordering."""

    key: str = Field(min_length=1, max_length=120)
    value: str = Field(max_length=1_000)


class ResearchRequest(FrozenResearchModel):
    """One bounded research question submitted to the learning cycle."""

    topic: str = Field(min_length=1, max_length=160)
    question: str = Field(min_length=1, max_length=1_000)
    mission_id: str | None = Field(default=None, max_length=160)


class NormalizedResearchDocument(FrozenResearchModel):
    """Authorized normalized input used transiently by one research cycle.

    ``content`` is checksum-validated but is never copied into ``ResearchInput``,
    ``ResearchEvidence``, ``ResearchCycleRecord``, or ``UserResearchResult``.
    """

    source_identifier: str = Field(min_length=1, max_length=500)
    source_type: ResearchSourceType = ResearchSourceType.LOCAL_FIXTURE
    input_type: ResearchInputType = ResearchInputType.DOCUMENT
    availability: ResearchDocumentAvailability = ResearchDocumentAvailability.AVAILABLE
    content: str | None = Field(default=None, max_length=MAX_RESEARCH_DOCUMENT_CHARS)
    declared_checksum: str | None = Field(default=None, max_length=128)
    captured_at: UtcDateTime | None = None
    evidence_type: ResearchEvidenceType = ResearchEvidenceType.DOCUMENT
    reliability_status: EvidenceReliabilityStatus = EvidenceReliabilityStatus.ACCEPTED
    provenance_reference: str | None = Field(default=None, max_length=500)
    usage_restrictions: tuple[str, ...] = ()
    consent_scope: ConsentScope = ConsentScope.INTERNAL_TEST
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL
    retention_class: RetentionClass = RetentionClass.RESEARCH_RECORD
    mission_id: str | None = Field(default=None, max_length=160)
    metadata: tuple[ResearchMetadataItem, ...] = ()

    @model_validator(mode="after")
    def _metadata_keys_are_unique(self) -> NormalizedResearchDocument:
        keys = tuple(item.key for item in self.metadata)
        if len(keys) != len(set(keys)):
            raise ValueError("research document metadata keys must be unique")
        if self.availability is ResearchDocumentAvailability.UNAVAILABLE and self.content:
            raise ValueError("unavailable research documents may not carry content")
        return self


class ResearchInput(FrozenResearchModel):
    """Traceable handling record for every authorized received input."""

    input_id: str
    input_type: ResearchInputType
    received_at: UtcDateTime
    source_type: ResearchSourceType
    source_identifier: str
    content_checksum: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    consent_scope: ConsentScope
    privacy_class: PrivacyClass
    retention_class: RetentionClass
    handling_status: ResearchInputStatus
    mission_id: str | None = None
    metadata: tuple[ResearchMetadataItem, ...] = ()


class ResearchEvidence(FrozenResearchModel):
    """Accepted evidence metadata; raw source content is deliberately excluded."""

    evidence_id: str
    input_id: str
    source_identifier: str
    captured_at: UtcDateTime
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_type: ResearchEvidenceType
    reliability_status: EvidenceReliabilityStatus
    provenance_reference: str
    usage_restrictions: tuple[str, ...]
    metadata: tuple[ResearchMetadataItem, ...] = ()


class ResearchGap(FrozenResearchModel):
    """Explicit missing, invalid, unavailable, or unresolved research information."""

    gap_id: str
    gap_type: ResearchGapType
    description: str = Field(min_length=1, max_length=500)
    detected_at: UtcDateTime
    related_input_id: str | None = None
    effect_on_result: str = Field(min_length=1, max_length=500)
    recoverable: bool
    metadata: tuple[ResearchMetadataItem, ...] = ()


class DerivedResearchClaim(FrozenResearchModel):
    """A bounded conclusion linked to evidence or explicitly marked hypothesis."""

    claim_id: str
    claim_type: ResearchClaimType
    statement: str = Field(min_length=1, max_length=2_000)
    epistemic_status: EpistemicStatus
    confidence_label: ConfidenceLabel
    evidence_ids: tuple[str, ...]
    gap_ids: tuple[str, ...] = ()
    created_at: UtcDateTime
    verifier_status: ClaimVerifierStatus = ClaimVerifierStatus.NOT_RUN
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def _require_evidence_or_hypothesis(self) -> DerivedResearchClaim:
        if not self.evidence_ids and self.epistemic_status is not EpistemicStatus.HYPOTHESIS:
            raise ValueError("a derived claim requires evidence unless explicitly a hypothesis")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("derived claim evidence references must be unique")
        if len(self.gap_ids) != len(set(self.gap_ids)):
            raise ValueError("derived claim gap references must be unique")
        return self


class ResearchLearningRecord(FrozenResearchModel):
    """Structured memory update produced by a governed research cycle."""

    learning_id: str
    cycle_id: str
    topic: str
    supporting_evidence_ids: tuple[str, ...]
    contradicted_evidence_ids: tuple[str, ...]
    resulting_claim_ids: tuple[str, ...]
    unresolved_gap_ids: tuple[str, ...]
    created_at: UtcDateTime
    status: ResearchLearningStatus


class UserResearchResult(FrozenResearchModel):
    """Safe concise projection returned to the requesting user."""

    request_summary: str
    answer: str
    confidence_label: ConfidenceLabel
    important_limitation: str
    recommended_next_step: str
    evidence_count: int = Field(ge=0)
    unresolved_gap_count: int = Field(ge=0)
    method_and_evidence_reference: str


class ResearchCycleRecord(FrozenResearchModel):
    """Atomic internal write contract for a complete governed research cycle.

    ``new_evidence`` excludes evidence deduplicated against an earlier cycle. The
    complete evidence set used by the claim is recorded by ``referenced_evidence_ids``.
    """

    schema_version: Literal["governed-research-learning-v1"] = RESEARCH_LEARNING_SCHEMA_VERSION
    cycle_id: str
    request_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: UtcDateTime
    inputs: tuple[ResearchInput, ...]
    new_evidence: tuple[ResearchEvidence, ...]
    referenced_evidence_ids: tuple[str, ...]
    gaps: tuple[ResearchGap, ...]
    claim: DerivedResearchClaim
    learning: ResearchLearningRecord


class OpenResearchActivation(FrozenResearchModel):
    """Explicit dual gate for future adapter-backed open-source research."""

    system_active: bool = False
    open_research_enabled: bool = False
