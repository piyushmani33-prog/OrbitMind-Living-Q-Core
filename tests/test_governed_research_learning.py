"""Offline tests for the governed research-learning foundation."""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.checksums import sha256_text
from orbitmind.core.config import Settings
from orbitmind.core.errors import ValidationError
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.research.models import (
    ClaimVerifierStatus,
    ConfidenceLabel,
    DerivedResearchClaim,
    EvidenceReliabilityStatus,
    NormalizedResearchDocument,
    OpenResearchActivation,
    ResearchClaimType,
    ResearchCycleRecord,
    ResearchDocumentAvailability,
    ResearchEvidence,
    ResearchEvidenceType,
    ResearchGapType,
    ResearchInputStatus,
    ResearchLearningStatus,
    ResearchMetadataItem,
    ResearchRequest,
)
from orbitmind.research.service import GovernedResearchLearningService

NOW = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
REQUEST = ResearchRequest(
    topic="offline communication planning fixture",
    question="What is the predicted next communication window?",
)
TRAJECTORY_CONTENT = (
    "Fixture trajectory source for a bounded communication-window example. "
    "Local-only marker C:\\private\\fixture-source.txt is not persisted."
)
OBSERVER_CONTENT = "Fixture observer coordinates for the bounded example."


class SequentialIds:
    def __init__(self) -> None:
        self._values = itertools.count(1)

    def __call__(self) -> str:
        return f"research-id-{next(self._values):04d}"


class RecordingResearchRepository:
    """Test-only adapter; it is intentionally not production persistence."""

    def __init__(self) -> None:
        self.cycles: list[ResearchCycleRecord] = []
        self.evidence: dict[tuple[str, str], ResearchEvidence] = {}

    def find_evidence(self, *, source_identifier: str, checksum: str) -> ResearchEvidence | None:
        return self.evidence.get((source_identifier, checksum))

    def save_cycle(self, cycle: ResearchCycleRecord) -> None:
        for item in cycle.new_evidence:
            self.evidence[(item.source_identifier, item.checksum)] = item
        known_ids = {item.evidence_id for item in self.evidence.values()}
        assert set(cycle.referenced_evidence_ids).issubset(known_ids)
        self.cycles.append(cycle)

    @property
    def saved_cycle(self) -> ResearchCycleRecord:
        assert self.cycles
        return self.cycles[-1]


class RecordingFixtureAdapter:
    def __init__(self, documents: Sequence[NormalizedResearchDocument]) -> None:
        self.documents = tuple(documents)
        self.called = False

    def collect(self, request: ResearchRequest) -> Sequence[NormalizedResearchDocument]:
        self.called = True
        assert request == REQUEST
        return self.documents


def _metadata(**values: str) -> tuple[ResearchMetadataItem, ...]:
    return tuple(ResearchMetadataItem(key=key, value=value) for key, value in values.items())


def _document(
    source_identifier: str,
    content: str,
    evidence_type: ResearchEvidenceType,
    *,
    declared_checksum: str | None = None,
    reliability: EvidenceReliabilityStatus = EvidenceReliabilityStatus.ACCEPTED,
    metadata: tuple[ResearchMetadataItem, ...] = (),
) -> NormalizedResearchDocument:
    return NormalizedResearchDocument(
        source_identifier=source_identifier,
        content=content,
        declared_checksum=declared_checksum or sha256_text(content),
        captured_at=NOW,
        evidence_type=evidence_type,
        reliability_status=reliability,
        provenance_reference=f"fixture:{source_identifier}",
        usage_restrictions=("offline test fixture only",),
        metadata=metadata,
    )


def _trajectory_document(
    *,
    source_identifier: str = "trajectory-source",
    content: str = TRAJECTORY_CONTENT,
    start: str = "2026-07-10T12:30:00Z",
    end: str = "2026-07-10T12:40:00Z",
    reliability: EvidenceReliabilityStatus = EvidenceReliabilityStatus.ACCEPTED,
) -> NormalizedResearchDocument:
    return _document(
        source_identifier,
        content,
        ResearchEvidenceType.TRAJECTORY_SOURCE,
        reliability=reliability,
        metadata=_metadata(
            window_start_utc=start,
            window_end_utc=end,
            internal_note="private-review-only",
        ),
    )


def _observer_document() -> NormalizedResearchDocument:
    return _document(
        "observer-source",
        OBSERVER_CONTENT,
        ResearchEvidenceType.OBSERVER_CONTEXT,
        metadata=_metadata(observer_label="fixture-observer"),
    )


def _invalid_checksum_document() -> NormalizedResearchDocument:
    return _document(
        "invalid-source",
        "Checksum-invalid fixture content.",
        ResearchEvidenceType.DOCUMENT,
        declared_checksum="0" * 64,
    )


def _unavailable_document() -> NormalizedResearchDocument:
    return NormalizedResearchDocument(
        source_identifier="unavailable-source",
        availability=ResearchDocumentAvailability.UNAVAILABLE,
        evidence_type=ResearchEvidenceType.DOCUMENT,
    )


def _service(
    repository: RecordingResearchRepository,
    *,
    source_adapter: RecordingFixtureAdapter | None = None,
    activation: OpenResearchActivation | None = None,
) -> GovernedResearchLearningService:
    return GovernedResearchLearningService(
        repository=repository,
        source_adapter=source_adapter,
        activation=activation,
        id_factory=SequentialIds(),
        clock=lambda: NOW,
    )


def test_bounded_cycle_separates_inputs_evidence_gaps_claim_and_learning() -> None:
    repository = RecordingResearchRepository()
    trajectory = _trajectory_document()
    result = _service(repository).run_cycle(
        REQUEST,
        (
            trajectory,
            _observer_document(),
            trajectory,
            _invalid_checksum_document(),
            _unavailable_document(),
        ),
    )
    cycle = repository.saved_cycle

    assert len(cycle.inputs) == 6  # user command plus five document handling records
    assert tuple(item.handling_status for item in cycle.inputs[1:]) == (
        ResearchInputStatus.ACCEPTED,
        ResearchInputStatus.ACCEPTED,
        ResearchInputStatus.DUPLICATE,
        ResearchInputStatus.REJECTED,
        ResearchInputStatus.UNAVAILABLE,
    )
    assert len(cycle.new_evidence) == 2
    assert {item.source_identifier for item in cycle.new_evidence} == {
        "trajectory-source",
        "observer-source",
    }
    assert cycle.new_evidence[0].checksum == sha256_text(TRAJECTORY_CONTENT)
    assert {gap.gap_type for gap in cycle.gaps} == {
        ResearchGapType.INVALID_CHECKSUM,
        ResearchGapType.SOURCE_UNAVAILABLE,
    }
    assert set(cycle.claim.evidence_ids) == {item.evidence_id for item in cycle.new_evidence}
    assert cycle.claim.verifier_status is ClaimVerifierStatus.SUPPORTED_WITH_GAPS
    assert cycle.learning.resulting_claim_ids == (cycle.claim.claim_id,)
    assert cycle.learning.unresolved_gap_ids == tuple(gap.gap_id for gap in cycle.gaps)
    assert cycle.learning.status is ResearchLearningStatus.PARTIAL

    assert result.evidence_count == 2
    assert result.unresolved_gap_count == 2
    assert result.confidence_label is ConfidenceLabel.LIMITED
    assert "2026-07-10T12:30:00Z" in result.answer
    assert result.method_and_evidence_reference == f"research-cycle:{cycle.cycle_id}"


def test_duplicate_evidence_is_deduplicated_across_cycles_by_source_and_checksum() -> None:
    repository = RecordingResearchRepository()
    first_service = _service(repository)
    first_service.run_cycle(REQUEST, (_trajectory_document(), _observer_document()))
    first_count = len(repository.evidence)

    second_service = _service(repository)
    second_service.run_cycle(REQUEST, (_trajectory_document(), _observer_document()))
    second_cycle = repository.saved_cycle

    assert first_count == 2
    assert len(repository.evidence) == 2
    assert second_cycle.new_evidence == ()
    assert all(
        item.handling_status is ResearchInputStatus.DUPLICATE for item in second_cycle.inputs[1:]
    )
    assert len(second_cycle.referenced_evidence_ids) == 2


def test_invalid_and_unavailable_inputs_never_become_claim_evidence() -> None:
    repository = RecordingResearchRepository()
    _service(repository).run_cycle(
        REQUEST,
        (
            _trajectory_document(),
            _observer_document(),
            _invalid_checksum_document(),
            _unavailable_document(),
        ),
    )
    cycle = repository.saved_cycle
    rejected_input_ids = {
        item.input_id
        for item in cycle.inputs
        if item.handling_status in {ResearchInputStatus.REJECTED, ResearchInputStatus.UNAVAILABLE}
    }

    assert rejected_input_ids
    assert not any(item.input_id in rejected_input_ids for item in cycle.new_evidence)
    assert set(cycle.claim.evidence_ids) == {item.evidence_id for item in cycle.new_evidence}


def test_claim_without_evidence_must_be_an_explicit_hypothesis() -> None:
    with pytest.raises(PydanticValidationError, match="requires evidence"):
        DerivedResearchClaim(
            claim_id="claim-without-evidence",
            claim_type=ResearchClaimType.COMMUNICATION_WINDOW,
            statement="Unsupported conclusion.",
            epistemic_status=EpistemicStatus.MODEL_ESTIMATE,
            confidence_label=ConfidenceLabel.SUPPORTED,
            evidence_ids=(),
            created_at=NOW,
            limitations=("No evidence.",),
        )

    hypothesis = DerivedResearchClaim(
        claim_id="explicit-hypothesis",
        claim_type=ResearchClaimType.COMMUNICATION_WINDOW,
        statement="A communication window might exist.",
        epistemic_status=EpistemicStatus.HYPOTHESIS,
        confidence_label=ConfidenceLabel.INDETERMINATE,
        evidence_ids=(),
        created_at=NOW,
        limitations=("No supporting evidence is available.",),
    )
    assert hypothesis.evidence_ids == ()


def test_conflicting_evidence_is_preserved_and_result_remains_unresolved() -> None:
    repository = RecordingResearchRepository()
    _service(repository).run_cycle(
        REQUEST,
        (
            _trajectory_document(),
            _trajectory_document(
                source_identifier="conflicting-trajectory-source",
                content="A conflicting fixture trajectory window.",
                start="2026-07-10T13:00:00Z",
                end="2026-07-10T13:10:00Z",
                reliability=EvidenceReliabilityStatus.CONFLICTING,
            ),
            _observer_document(),
        ),
    )
    cycle = repository.saved_cycle
    trajectory_evidence = tuple(
        item
        for item in cycle.new_evidence
        if item.evidence_type is ResearchEvidenceType.TRAJECTORY_SOURCE
    )

    assert len(trajectory_evidence) == 2
    assert len({item.checksum for item in trajectory_evidence}) == 2
    assert ResearchGapType.CONFLICTING_EVIDENCE in {gap.gap_type for gap in cycle.gaps}
    assert cycle.claim.epistemic_status is EpistemicStatus.HYPOTHESIS
    assert cycle.claim.verifier_status is ClaimVerifierStatus.INSUFFICIENT_EVIDENCE
    assert cycle.learning.contradicted_evidence_ids == (trajectory_evidence[1].evidence_id,)


def test_missing_required_evidence_fails_closed_as_hypothesis() -> None:
    repository = RecordingResearchRepository()
    result = _service(repository).run_cycle(REQUEST, (_trajectory_document(),))
    cycle = repository.saved_cycle

    assert ResearchGapType.INSUFFICIENT_EVIDENCE in {gap.gap_type for gap in cycle.gaps}
    assert cycle.claim.epistemic_status is EpistemicStatus.HYPOTHESIS
    assert cycle.claim.verifier_status is ClaimVerifierStatus.INSUFFICIENT_EVIDENCE
    assert result.confidence_label is ConfidenceLabel.INDETERMINATE


def test_user_result_is_bounded_and_does_not_expose_internal_material() -> None:
    repository = RecordingResearchRepository()
    result = _service(repository).run_cycle(
        REQUEST,
        (_trajectory_document(), _observer_document()),
    )
    result_json = result.model_dump_json()
    cycle_json = repository.saved_cycle.model_dump_json()

    assert set(result.model_dump()) == {
        "request_summary",
        "answer",
        "confidence_label",
        "important_limitation",
        "recommended_next_step",
        "evidence_count",
        "unresolved_gap_count",
        "method_and_evidence_reference",
    }
    for forbidden in (
        TRAJECTORY_CONTENT,
        "C:\\private\\fixture-source.txt",
        "private-review-only",
        "raw provider body",
        "secret-value",
    ):
        assert forbidden not in result_json
    assert TRAJECTORY_CONTENT not in cycle_json
    assert "C:\\private\\fixture-source.txt" not in cycle_json


def test_injected_ids_and_clock_make_the_fixture_cycle_deterministic() -> None:
    first_repository = RecordingResearchRepository()
    second_repository = RecordingResearchRepository()
    documents = (_trajectory_document(), _observer_document())

    first_result = _service(first_repository).run_cycle(REQUEST, documents)
    second_result = _service(second_repository).run_cycle(REQUEST, documents)

    assert first_result == second_result
    assert first_repository.saved_cycle == second_repository.saved_cycle
    assert first_repository.saved_cycle.created_at.tzinfo is UTC


def test_open_research_is_disabled_by_default_and_adapter_is_not_called() -> None:
    assert Settings.model_fields["open_research_enabled"].default is False
    repository = RecordingResearchRepository()
    adapter = RecordingFixtureAdapter((_trajectory_document(), _observer_document()))
    service = _service(repository, source_adapter=adapter)

    with pytest.raises(ValidationError, match="open research is disabled"):
        service.run_source_cycle(REQUEST)
    assert adapter.called is False

    service.run_cycle(REQUEST, (_trajectory_document(), _observer_document()))
    assert adapter.called is False


def test_source_cycle_requires_dual_activation_and_an_injected_adapter() -> None:
    repository = RecordingResearchRepository()
    enabled = OpenResearchActivation(system_active=True, open_research_enabled=True)
    service_without_adapter = _service(repository, activation=enabled)

    with pytest.raises(ValidationError, match="no approved research source adapter"):
        service_without_adapter.run_source_cycle(REQUEST)

    adapter = RecordingFixtureAdapter((_trajectory_document(), _observer_document()))
    enabled_service = _service(repository, source_adapter=adapter, activation=enabled)
    result = enabled_service.run_source_cycle(REQUEST)

    assert adapter.called is True
    assert result.evidence_count == 2


def test_document_count_is_bounded_before_any_cycle_is_saved() -> None:
    repository = RecordingResearchRepository()
    documents = tuple(_observer_document() for _ in range(17))

    with pytest.raises(ValidationError, match="at most 16"):
        _service(repository).run_cycle(REQUEST, documents)
    assert repository.cycles == []
