"""Fail-closed safety policy for structured governed-research persistence.

Raw research content is intentionally transient, but structured identifiers,
references, metadata, and descriptive fields are durable. This module prevents
those structured channels from becoming an accidental credential or local-path
store. Rejected values are never included in the raised error.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from orbitmind.core.errors import SecurityError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from orbitmind.research.models import (
        DerivedResearchClaim,
        NormalizedResearchDocument,
        ResearchCycleRecord,
        ResearchEvidence,
        ResearchGap,
        ResearchInput,
        ResearchLearningRecord,
        ResearchMetadataItem,
        ResearchRequest,
    )


class ResearchPersistenceSafetyError(SecurityError):
    """A durable research field contains prohibited sensitive material."""

    code = "research_persistence_policy"

    def __init__(self, field_name: str) -> None:
        super().__init__(f"research persistence policy rejected field '{field_name}'")
        self.field_name = field_name


_SENSITIVE_METADATA_KEYS = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "api_key",
        "access_token",
        "refresh_token",
        "authorization",
        "cookie",
        "private_key",
        "client_secret",
        "credential",
        "credentials",
    }
)

_WINDOWS_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s<>\"|?*]+")
_UNC_PATH = re.compile(r"(?:^|(?<=[\s\"'(=]))\\\\[^\\/\s]+[\\/][^\s<>\"']+")
_POSIX_ABSOLUTE_PATH = re.compile(r"(?:^|(?<=[\s\"'(=:]))/(?!/)[A-Za-z0-9._~+-]+(?:/[^\s<>\"']*)?")
_FILE_URI = re.compile(r"(?i)\bfile://")
_URL = re.compile(r"(?i)\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>\"']+")
_AUTHORIZATION_HEADER = re.compile(r"(?i)\bauthorization\s*:\s*\S+")
_COOKIE_HEADER = re.compile(r"(?i)\bcookie\s*:\s*[^\s=;]+\s*=\s*\S+")
_BEARER_TOKEN = re.compile(
    r"(?i)(?<![\w-])bearer\s+(?=[A-Za-z0-9._~+/=-]{6,})(?=\S*(?:\d|[._~-]))"
    r"[A-Za-z0-9._~+/=-]{6,}"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)
_GITHUB_TOKEN = re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_OPENAI_TOKEN = re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")
_AWS_ACCESS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GOOGLE_API_KEY = re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b")
_SLACK_TOKEN = re.compile(r"\bxox[bpars]-[A-Za-z0-9-]{10,}\b")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)(?<![\w-])(?:password|passwd|api[_-]?key|access[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|private[_-]?key|credentials?|secret)"
    r"\s*[:=]\s*(?!\s*(?:none|null|redacted|masked)\b)\S+"
)

_SENSITIVE_VALUE_PATTERNS = (
    _WINDOWS_ABSOLUTE_PATH,
    _UNC_PATH,
    _POSIX_ABSOLUTE_PATH,
    _FILE_URI,
    _AUTHORIZATION_HEADER,
    _COOKIE_HEADER,
    _BEARER_TOKEN,
    _PRIVATE_KEY,
    _GITHUB_TOKEN,
    _OPENAI_TOKEN,
    _AWS_ACCESS_KEY,
    _GOOGLE_API_KEY,
    _SLACK_TOKEN,
    _SECRET_ASSIGNMENT,
)


def validate_persisted_identifier(value: str | None, field_name: str) -> None:
    """Validate a durable owner, object, source, mission, or association identifier."""

    _validate_persisted_text(value, field_name)


def validate_persisted_reference(value: str | None, field_name: str) -> None:
    """Validate a durable provenance, request, result, or evidence reference."""

    _validate_persisted_text(value, field_name)


def validate_persisted_description(value: str | None, field_name: str) -> None:
    """Validate bounded descriptive or user-generated text stored durably."""

    _validate_persisted_text(value, field_name)


def validate_research_metadata_item_persistence_safety(item: ResearchMetadataItem) -> None:
    normalized_key = re.sub(r"[^a-z0-9]+", "_", item.key.casefold()).strip("_")
    if normalized_key in _SENSITIVE_METADATA_KEYS:
        raise ResearchPersistenceSafetyError("research_metadata.key")
    validate_persisted_description(item.value, "research_metadata.value")


def validate_research_request_persistence_safety(request: ResearchRequest) -> None:
    validate_persisted_description(request.topic, "research_request.topic")
    validate_persisted_identifier(request.mission_id, "research_request.mission_id")


def validate_normalized_document_persistence_safety(
    document: NormalizedResearchDocument,
) -> None:
    validate_persisted_identifier(
        document.source_identifier, "normalized_document.source_identifier"
    )
    validate_persisted_reference(
        document.provenance_reference, "normalized_document.provenance_reference"
    )
    validate_persisted_identifier(document.mission_id, "normalized_document.mission_id")
    _validate_descriptions(document.usage_restrictions, "normalized_document.usage_restrictions")
    _validate_metadata(document.metadata)


def validate_research_input_persistence_safety(item: ResearchInput) -> None:
    validate_persisted_identifier(item.input_id, "research_input.input_id")
    validate_persisted_identifier(item.source_identifier, "research_input.source_identifier")
    validate_persisted_identifier(item.mission_id, "research_input.mission_id")
    validate_persisted_identifier(
        item.duplicate_evidence_id, "research_input.duplicate_evidence_id"
    )
    _validate_metadata(item.metadata)


def validate_research_evidence_persistence_safety(item: ResearchEvidence) -> None:
    validate_persisted_identifier(item.evidence_id, "research_evidence.evidence_id")
    validate_persisted_identifier(item.input_id, "research_evidence.input_id")
    validate_persisted_identifier(item.source_identifier, "research_evidence.source_identifier")
    validate_persisted_reference(
        item.provenance_reference, "research_evidence.provenance_reference"
    )
    _validate_descriptions(item.usage_restrictions, "research_evidence.usage_restrictions")
    _validate_metadata(item.metadata)


def validate_research_gap_persistence_safety(item: ResearchGap) -> None:
    validate_persisted_identifier(item.gap_id, "research_gap.gap_id")
    validate_persisted_description(item.description, "research_gap.description")
    validate_persisted_identifier(item.related_input_id, "research_gap.related_input_id")
    validate_persisted_description(item.effect_on_result, "research_gap.effect_on_result")
    _validate_metadata(item.metadata)


def validate_research_claim_persistence_safety(item: DerivedResearchClaim) -> None:
    validate_persisted_identifier(item.claim_id, "research_claim.claim_id")
    validate_persisted_description(item.statement, "research_claim.statement")
    _validate_identifiers(item.evidence_ids, "research_claim.evidence_ids")
    _validate_identifiers(item.gap_ids, "research_claim.gap_ids")
    _validate_descriptions(item.limitations, "research_claim.limitations")


def validate_research_learning_persistence_safety(item: ResearchLearningRecord) -> None:
    validate_persisted_identifier(item.learning_id, "research_learning.learning_id")
    validate_persisted_identifier(item.cycle_id, "research_learning.cycle_id")
    validate_persisted_description(item.topic, "research_learning.topic")
    _validate_identifiers(item.supporting_evidence_ids, "research_learning.supporting_evidence_ids")
    _validate_identifiers(
        item.contradicted_evidence_ids, "research_learning.contradicted_evidence_ids"
    )
    _validate_identifiers(item.resulting_claim_ids, "research_learning.resulting_claim_ids")
    _validate_identifiers(item.unresolved_gap_ids, "research_learning.unresolved_gap_ids")


def validate_research_cycle_persistence_safety(cycle: ResearchCycleRecord) -> None:
    """Audit every non-enum, non-checksum string that the U4.0B schema persists."""

    validate_persisted_identifier(cycle.cycle_id, "research_cycle.cycle_id")
    validate_persisted_reference(cycle.request_reference, "research_cycle.request_reference")
    validate_persisted_reference(cycle.result_reference, "research_cycle.result_reference")
    for research_input in cycle.inputs:
        validate_research_input_persistence_safety(research_input)
    for evidence in cycle.new_evidence:
        validate_research_evidence_persistence_safety(evidence)
    _validate_identifiers(cycle.referenced_evidence_ids, "research_cycle.referenced_evidence_ids")
    for gap in cycle.gaps:
        validate_research_gap_persistence_safety(gap)
    validate_research_claim_persistence_safety(cycle.claim)
    validate_research_learning_persistence_safety(cycle.learning)


def _validate_metadata(items: Sequence[ResearchMetadataItem]) -> None:
    for item in items:
        validate_research_metadata_item_persistence_safety(item)


def _validate_identifiers(values: Sequence[str], field_name: str) -> None:
    for value in values:
        validate_persisted_identifier(value, field_name)


def _validate_descriptions(values: Sequence[str], field_name: str) -> None:
    for value in values:
        validate_persisted_description(value, field_name)


def _validate_persisted_text(value: str | None, field_name: str) -> None:
    if value is None:
        return
    if any(pattern.search(value) is not None for pattern in _SENSITIVE_VALUE_PATTERNS):
        raise ResearchPersistenceSafetyError(field_name)
    if _contains_credential_bearing_url(value):
        raise ResearchPersistenceSafetyError(field_name)


def _contains_credential_bearing_url(value: str) -> bool:
    for match in _URL.finditer(value):
        parsed = urlsplit(match.group(0).rstrip(".,);]"))
        if parsed.username is not None or parsed.password is not None:
            return True
    return False
