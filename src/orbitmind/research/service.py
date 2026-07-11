"""Offline governed research-learning application service.

The default workflow uses deterministic fixture metadata only. It contains no LLM,
network client, scheduler, API wiring, durable repository implementation, or code/
permission modification behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import datetime

from orbitmind.core.checksums import sha256_canonical_json, sha256_text
from orbitmind.core.errors import ValidationError
from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import ensure_utc, isoformat_utc, utcnow
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.research.models import (
    MAX_RESEARCH_DOCUMENTS,
    ClaimVerifierStatus,
    ConfidenceLabel,
    ConsentScope,
    DerivedResearchClaim,
    EvidenceReliabilityStatus,
    NormalizedResearchDocument,
    OpenResearchActivation,
    PrivacyClass,
    ResearchClaimType,
    ResearchCycleRecord,
    ResearchDocumentAvailability,
    ResearchEvidence,
    ResearchEvidenceType,
    ResearchGap,
    ResearchGapType,
    ResearchInput,
    ResearchInputStatus,
    ResearchInputType,
    ResearchLearningRecord,
    ResearchLearningStatus,
    ResearchMetadataItem,
    ResearchRequest,
    ResearchSourceType,
    RetentionClass,
    UserResearchResult,
)
from orbitmind.research.ports import (
    ResearchClaimGenerator,
    ResearchClaimVerifier,
    ResearchMemoryRepository,
    ResearchSourceAdapter,
    UserResearchResultProjector,
)

IdFactory = Callable[[], str]
Clock = Callable[[], datetime]

_WINDOW_START_KEY = "window_start_utc"
_WINDOW_END_KEY = "window_end_utc"
_REQUIRED_EVIDENCE_TYPES = frozenset(
    {ResearchEvidenceType.TRAJECTORY_SOURCE, ResearchEvidenceType.OBSERVER_CONTEXT}
)
_RESOLUTION_BLOCKING_GAPS = frozenset(
    {
        ResearchGapType.MISSING_TIME_RANGE,
        ResearchGapType.CONFLICTING_EVIDENCE,
        ResearchGapType.INSUFFICIENT_EVIDENCE,
    }
)


class DeterministicFixtureClaimGenerator:
    """Generate only the bounded communication-window fixture claim."""

    def generate(
        self,
        *,
        request: ResearchRequest,
        evidence: tuple[ResearchEvidence, ...],
        gaps: tuple[ResearchGap, ...],
        claim_id: str,
        created_at: datetime,
    ) -> DerivedResearchClaim:
        relevant = tuple(
            item for item in evidence if item.evidence_type in _REQUIRED_EVIDENCE_TYPES
        )
        blocking = any(gap.gap_type in _RESOLUTION_BLOCKING_GAPS for gap in gaps)
        windows = _valid_window_signatures(evidence)
        if blocking or len(windows) != 1:
            return DerivedResearchClaim(
                claim_id=claim_id,
                claim_type=ResearchClaimType.COMMUNICATION_WINDOW,
                statement=(
                    "Available fixture evidence is insufficient to resolve a predicted "
                    "communication window."
                ),
                epistemic_status=EpistemicStatus.HYPOTHESIS,
                confidence_label=ConfidenceLabel.INDETERMINATE,
                evidence_ids=tuple(item.evidence_id for item in relevant),
                gap_ids=tuple(gap.gap_id for gap in gaps),
                created_at=created_at,
                limitations=(
                    "Hypothesis only; unresolved evidence requirements prevent a derived result.",
                ),
            )

        start, end = next(iter(windows))
        return DerivedResearchClaim(
            claim_id=claim_id,
            claim_type=ResearchClaimType.COMMUNICATION_WINDOW,
            statement=(
                f"The accepted fixture evidence supports a predicted communication window "
                f"from {start} to {end}."
            ),
            epistemic_status=EpistemicStatus.MODEL_ESTIMATE,
            confidence_label=ConfidenceLabel.LIMITED,
            evidence_ids=tuple(item.evidence_id for item in relevant),
            gap_ids=tuple(gap.gap_id for gap in gaps),
            created_at=created_at,
            limitations=(
                "Deterministic fixture-derived claim; not a live or operational "
                "communication window.",
            ),
        )


class DeterministicResearchClaimVerifier:
    """Verify reference integrity and bounded fixture prerequisites."""

    def verify(
        self,
        *,
        claim: DerivedResearchClaim,
        evidence: tuple[ResearchEvidence, ...],
        gaps: tuple[ResearchGap, ...],
    ) -> DerivedResearchClaim:
        evidence_by_id = {item.evidence_id: item for item in evidence}
        referenced = tuple(evidence_by_id.get(evidence_id) for evidence_id in claim.evidence_ids)
        if any(item is None for item in referenced):
            return claim.model_copy(
                update={
                    "verifier_status": ClaimVerifierStatus.REJECTED,
                    "confidence_label": ConfidenceLabel.INDETERMINATE,
                    "limitations": (*claim.limitations, "Claim references missing evidence."),
                }
            )
        if claim.epistemic_status is EpistemicStatus.HYPOTHESIS:
            return claim.model_copy(
                update={"verifier_status": ClaimVerifierStatus.INSUFFICIENT_EVIDENCE}
            )

        referenced_types = {item.evidence_type for item in referenced if item is not None}
        if not _REQUIRED_EVIDENCE_TYPES.issubset(referenced_types):
            return claim.model_copy(
                update={
                    "verifier_status": ClaimVerifierStatus.REJECTED,
                    "confidence_label": ConfidenceLabel.INDETERMINATE,
                    "limitations": (
                        *claim.limitations,
                        "Claim does not reference all required evidence types.",
                    ),
                }
            )
        if any(gap.gap_type in _RESOLUTION_BLOCKING_GAPS for gap in gaps):
            return claim.model_copy(
                update={
                    "verifier_status": ClaimVerifierStatus.INSUFFICIENT_EVIDENCE,
                    "confidence_label": ConfidenceLabel.INDETERMINATE,
                }
            )
        status = ClaimVerifierStatus.SUPPORTED_WITH_GAPS if gaps else ClaimVerifierStatus.SUPPORTED
        confidence = ConfidenceLabel.LIMITED if gaps else ConfidenceLabel.SUPPORTED
        return claim.model_copy(update={"verifier_status": status, "confidence_label": confidence})


class ConciseUserResearchResultProjector:
    """Expose only the relevant answer and bounded aggregate evidence information."""

    def project(
        self,
        *,
        cycle_id: str,
        request: ResearchRequest,
        claim: DerivedResearchClaim,
        gaps: tuple[ResearchGap, ...],
    ) -> UserResearchResult:
        if gaps:
            limitation = (
                f"This result has {len(gaps)} unresolved research gap(s); stronger use "
                "requires resolving the separately recorded gaps."
            )
            next_step = "Resolve the recorded gaps, then rerun the governed research cycle."
        else:
            limitation = claim.limitations[0]
            next_step = "Review the linked method and evidence before relying on the result."
        return UserResearchResult(
            request_summary=request.question,
            answer=claim.statement,
            confidence_label=claim.confidence_label,
            important_limitation=limitation,
            recommended_next_step=next_step,
            evidence_count=len(claim.evidence_ids),
            unresolved_gap_count=len(gaps),
            method_and_evidence_reference=f"research-cycle:{cycle_id}",
        )


class GovernedResearchLearningService:
    """Run one bounded offline research cycle and return only its safe projection."""

    def __init__(
        self,
        *,
        repository: ResearchMemoryRepository,
        owner_id: str,
        claim_generator: ResearchClaimGenerator | None = None,
        verifier: ResearchClaimVerifier | None = None,
        result_projector: UserResearchResultProjector | None = None,
        source_adapter: ResearchSourceAdapter | None = None,
        activation: OpenResearchActivation | None = None,
        id_factory: IdFactory = new_id,
        clock: Clock = utcnow,
    ) -> None:
        if not owner_id or owner_id.strip() != owner_id or len(owner_id) > 120:
            raise ValidationError(
                "owner_id must be non-empty, unpadded, and at most 120 characters"
            )
        self._repository = repository
        self._owner_id = owner_id
        self._claim_generator = claim_generator or DeterministicFixtureClaimGenerator()
        self._verifier = verifier or DeterministicResearchClaimVerifier()
        self._result_projector = result_projector or ConciseUserResearchResultProjector()
        self._source_adapter = source_adapter
        self._activation = activation or OpenResearchActivation()
        self._id_factory = id_factory
        self._clock = clock

    def run_cycle(
        self,
        request: ResearchRequest,
        documents: Sequence[NormalizedResearchDocument],
    ) -> UserResearchResult:
        """Process explicit authorized documents without invoking a source adapter."""

        bounded_documents = tuple(documents)
        if len(bounded_documents) > MAX_RESEARCH_DOCUMENTS:
            raise ValidationError(
                f"research cycle accepts at most {MAX_RESEARCH_DOCUMENTS} documents"
            )

        cycle_id = self._id_factory()
        now = ensure_utc(self._clock())
        request_checksum = sha256_canonical_json(request.model_dump(mode="json"))
        inputs: list[ResearchInput] = [
            ResearchInput(
                input_id=self._id_factory(),
                input_type=ResearchInputType.USER_COMMAND,
                received_at=now,
                source_type=ResearchSourceType.USER,
                source_identifier="authorized-user-request",
                content_checksum=request_checksum,
                consent_scope=ConsentScope.EXPLICIT_RESEARCH,
                privacy_class=PrivacyClass.INTERNAL,
                retention_class=RetentionClass.RESEARCH_RECORD,
                handling_status=ResearchInputStatus.ACCEPTED,
                mission_id=request.mission_id,
                metadata=(ResearchMetadataItem(key="topic", value=request.topic),),
            )
        ]
        new_evidence: list[ResearchEvidence] = []
        accepted_evidence: dict[tuple[str, str], ResearchEvidence] = {}
        gaps: list[ResearchGap] = []

        for document in bounded_documents:
            self._process_document(
                document=document,
                now=now,
                inputs=inputs,
                new_evidence=new_evidence,
                accepted_evidence=accepted_evidence,
                gaps=gaps,
            )

        ordered_evidence = tuple(accepted_evidence.values())
        self._add_claim_requirement_gaps(ordered_evidence, gaps, now)
        ordered_gaps = tuple(gaps)
        generated_claim = self._claim_generator.generate(
            request=request,
            evidence=ordered_evidence,
            gaps=ordered_gaps,
            claim_id=self._id_factory(),
            created_at=now,
        )
        claim = self._verifier.verify(
            claim=generated_claim,
            evidence=ordered_evidence,
            gaps=ordered_gaps,
        )
        learning = self._learning_record(
            cycle_id=cycle_id,
            request=request,
            claim=claim,
            evidence=ordered_evidence,
            gaps=ordered_gaps,
            now=now,
        )
        cycle = ResearchCycleRecord(
            cycle_id=cycle_id,
            request_checksum=request_checksum,
            request_reference=f"research-request:{request_checksum}",
            created_at=now,
            completed_at=now,
            status=learning.status,
            result_reference=f"research-cycle:{cycle_id}",
            inputs=tuple(inputs),
            new_evidence=tuple(new_evidence),
            referenced_evidence_ids=claim.evidence_ids,
            gaps=ordered_gaps,
            claim=claim,
            learning=learning,
        )
        persisted_cycle = self._repository.save_cycle(owner_id=self._owner_id, cycle=cycle)
        return self._result_projector.project(
            cycle_id=persisted_cycle.cycle_id,
            request=request,
            claim=persisted_cycle.claim,
            gaps=persisted_cycle.gaps,
        )

    def run_source_cycle(self, request: ResearchRequest) -> UserResearchResult:
        """Run an explicitly injected future adapter only when both gates are true."""

        if not (self._activation.system_active and self._activation.open_research_enabled):
            raise ValidationError("open research is disabled")
        if self._source_adapter is None:
            raise ValidationError("no approved research source adapter is configured")
        documents = tuple(self._source_adapter.collect(request))
        return self.run_cycle(request, documents)

    def _process_document(
        self,
        *,
        document: NormalizedResearchDocument,
        now: datetime,
        inputs: list[ResearchInput],
        new_evidence: list[ResearchEvidence],
        accepted_evidence: dict[tuple[str, str], ResearchEvidence],
        gaps: list[ResearchGap],
    ) -> None:
        input_id = self._id_factory()
        if document.availability is ResearchDocumentAvailability.UNAVAILABLE:
            inputs.append(
                self._input_record(document, input_id, now, None, ResearchInputStatus.UNAVAILABLE)
            )
            gaps.append(
                self._gap(
                    ResearchGapType.SOURCE_UNAVAILABLE,
                    "Authorized research source was unavailable for this cycle.",
                    "The unavailable source cannot support the derived result.",
                    now,
                    related_input_id=input_id,
                    recoverable=True,
                )
            )
            return

        content = document.content or ""
        actual_checksum = sha256_text(content)
        if not content.strip():
            inputs.append(
                self._input_record(
                    document, input_id, now, actual_checksum, ResearchInputStatus.REJECTED
                )
            )
            gaps.append(
                self._gap(
                    ResearchGapType.MISSING_CONTENT,
                    "Research document did not contain usable text.",
                    "The empty document cannot support the derived result.",
                    now,
                    related_input_id=input_id,
                    recoverable=True,
                )
            )
            return
        if document.declared_checksum is not None and document.declared_checksum != actual_checksum:
            inputs.append(
                self._input_record(
                    document, input_id, now, actual_checksum, ResearchInputStatus.REJECTED
                )
            )
            gaps.append(
                self._gap(
                    ResearchGapType.INVALID_CHECKSUM,
                    "Declared checksum did not match the received document content.",
                    "Unverified content was excluded from evidence and claim generation.",
                    now,
                    related_input_id=input_id,
                    recoverable=True,
                )
            )
            return
        if (
            document.captured_at is None
            or not document.provenance_reference
            or not document.usage_restrictions
        ):
            inputs.append(
                self._input_record(
                    document, input_id, now, actual_checksum, ResearchInputStatus.REJECTED
                )
            )
            gaps.append(
                self._gap(
                    ResearchGapType.MISSING_SOURCE_METADATA,
                    "Research document lacked required provenance, capture time, or "
                    "usage metadata.",
                    "The document was excluded because its source context was incomplete.",
                    now,
                    related_input_id=input_id,
                    recoverable=True,
                )
            )
            return

        evidence_identity = (document.source_identifier, actual_checksum)
        existing = accepted_evidence.get(evidence_identity)
        if existing is None:
            existing = self._repository.find_evidence(
                owner_id=self._owner_id,
                source_identifier=document.source_identifier,
                checksum=actual_checksum,
            )
        if existing is not None and existing.source_identifier == document.source_identifier:
            inputs.append(
                self._input_record(
                    document,
                    input_id,
                    now,
                    actual_checksum,
                    ResearchInputStatus.DUPLICATE,
                    duplicate_evidence_id=existing.evidence_id,
                )
            )
            accepted_evidence.setdefault(evidence_identity, existing)
            return

        research_input = self._input_record(
            document, input_id, now, actual_checksum, ResearchInputStatus.ACCEPTED
        )
        evidence = ResearchEvidence(
            evidence_id=self._id_factory(),
            input_id=input_id,
            source_identifier=document.source_identifier,
            captured_at=document.captured_at,
            checksum=actual_checksum,
            evidence_type=document.evidence_type,
            reliability_status=document.reliability_status,
            provenance_reference=document.provenance_reference,
            usage_restrictions=document.usage_restrictions,
            metadata=_ordered_metadata(document.metadata),
        )
        inputs.append(research_input)
        new_evidence.append(evidence)
        accepted_evidence[evidence_identity] = evidence

    def _add_claim_requirement_gaps(
        self,
        evidence: tuple[ResearchEvidence, ...],
        gaps: list[ResearchGap],
        now: datetime,
    ) -> None:
        evidence_types = {item.evidence_type for item in evidence}
        if not _REQUIRED_EVIDENCE_TYPES.issubset(evidence_types):
            gaps.append(
                self._gap(
                    ResearchGapType.INSUFFICIENT_EVIDENCE,
                    "Trajectory and observer evidence are both required for this fixture claim.",
                    "A communication-window claim cannot be resolved.",
                    now,
                    recoverable=True,
                )
            )
            return
        trajectories = tuple(
            item
            for item in evidence
            if item.evidence_type is ResearchEvidenceType.TRAJECTORY_SOURCE
        )
        windows = _valid_window_signatures(trajectories)
        if len(windows) == 0:
            gaps.append(
                self._gap(
                    ResearchGapType.MISSING_TIME_RANGE,
                    "Accepted trajectory evidence did not contain one valid UTC window.",
                    "A communication-window claim cannot be resolved.",
                    now,
                    recoverable=True,
                )
            )
        elif len(windows) > 1:
            gaps.append(
                self._gap(
                    ResearchGapType.CONFLICTING_EVIDENCE,
                    "Accepted trajectory evidence contains conflicting communication windows.",
                    "Conflicting windows are preserved and the result remains unresolved.",
                    now,
                    recoverable=True,
                )
            )

    def _input_record(
        self,
        document: NormalizedResearchDocument,
        input_id: str,
        now: datetime,
        checksum: str | None,
        status: ResearchInputStatus,
        *,
        duplicate_evidence_id: str | None = None,
    ) -> ResearchInput:
        return ResearchInput(
            input_id=input_id,
            input_type=document.input_type,
            received_at=now,
            source_type=document.source_type,
            source_identifier=document.source_identifier,
            content_checksum=checksum,
            consent_scope=document.consent_scope,
            privacy_class=document.privacy_class,
            retention_class=document.retention_class,
            handling_status=status,
            mission_id=document.mission_id,
            duplicate_evidence_id=duplicate_evidence_id,
            metadata=_ordered_metadata(document.metadata),
        )

    def _gap(
        self,
        gap_type: ResearchGapType,
        description: str,
        effect_on_result: str,
        now: datetime,
        *,
        related_input_id: str | None = None,
        recoverable: bool,
    ) -> ResearchGap:
        return ResearchGap(
            gap_id=self._id_factory(),
            gap_type=gap_type,
            description=description,
            detected_at=now,
            related_input_id=related_input_id,
            effect_on_result=effect_on_result,
            recoverable=recoverable,
        )

    def _learning_record(
        self,
        *,
        cycle_id: str,
        request: ResearchRequest,
        claim: DerivedResearchClaim,
        evidence: tuple[ResearchEvidence, ...],
        gaps: tuple[ResearchGap, ...],
        now: datetime,
    ) -> ResearchLearningRecord:
        if claim.verifier_status in (
            ClaimVerifierStatus.INSUFFICIENT_EVIDENCE,
            ClaimVerifierStatus.REJECTED,
        ):
            status = ResearchLearningStatus.INSUFFICIENT_EVIDENCE
        elif gaps:
            status = ResearchLearningStatus.PARTIAL
        else:
            status = ResearchLearningStatus.RECORDED
        return ResearchLearningRecord(
            learning_id=self._id_factory(),
            cycle_id=cycle_id,
            topic=request.topic,
            supporting_evidence_ids=claim.evidence_ids,
            contradicted_evidence_ids=tuple(
                item.evidence_id
                for item in evidence
                if item.reliability_status is EvidenceReliabilityStatus.CONFLICTING
            ),
            resulting_claim_ids=(claim.claim_id,),
            unresolved_gap_ids=tuple(gap.gap_id for gap in gaps),
            created_at=now,
            status=status,
        )


def _ordered_metadata(
    metadata: Sequence[ResearchMetadataItem],
) -> tuple[ResearchMetadataItem, ...]:
    return tuple(sorted(metadata, key=lambda item: (item.key, item.value)))


def _metadata_map(evidence: ResearchEvidence) -> dict[str, str]:
    return {item.key: item.value for item in evidence.metadata}


def _valid_window_signatures(
    evidence: Sequence[ResearchEvidence],
) -> set[tuple[str, str]]:
    windows: set[tuple[str, str]] = set()
    for item in evidence:
        if item.evidence_type is not ResearchEvidenceType.TRAJECTORY_SOURCE:
            continue
        metadata = _metadata_map(item)
        start_text = metadata.get(_WINDOW_START_KEY)
        end_text = metadata.get(_WINDOW_END_KEY)
        if start_text is None or end_text is None:
            continue
        try:
            start = ensure_utc(datetime.fromisoformat(start_text.replace("Z", "+00:00")))
            end = ensure_utc(datetime.fromisoformat(end_text.replace("Z", "+00:00")))
        except ValueError:
            continue
        if end <= start:
            continue
        windows.add(
            (isoformat_utc(start).replace("+00:00", "Z"), isoformat_utc(end).replace("+00:00", "Z"))
        )
    return windows
