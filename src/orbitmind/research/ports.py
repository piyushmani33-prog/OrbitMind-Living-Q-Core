"""Dependency-injection ports for governed research learning."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from orbitmind.research.models import (
    DerivedResearchClaim,
    NormalizedResearchDocument,
    ResearchCycleRecord,
    ResearchEvidence,
    ResearchGap,
    ResearchRequest,
    UserResearchResult,
)


class ResearchMemoryRepository(Protocol):
    """Persistence port; durable implementations must save each cycle atomically."""

    def find_evidence(
        self, *, source_identifier: str, checksum: str
    ) -> ResearchEvidence | None: ...

    def save_cycle(self, cycle: ResearchCycleRecord) -> None: ...


class ResearchSourceAdapter(Protocol):
    """Future allowlisted source adapter returning normalized bounded documents."""

    def collect(self, request: ResearchRequest) -> Sequence[NormalizedResearchDocument]: ...


class ResearchClaimGenerator(Protocol):
    """Generate one claim from accepted evidence without controlling persistence."""

    def generate(
        self,
        *,
        request: ResearchRequest,
        evidence: tuple[ResearchEvidence, ...],
        gaps: tuple[ResearchGap, ...],
        claim_id: str,
        created_at: datetime,
    ) -> DerivedResearchClaim: ...


class ResearchClaimVerifier(Protocol):
    """Verify claim-to-evidence consistency and return a new immutable claim."""

    def verify(
        self,
        *,
        claim: DerivedResearchClaim,
        evidence: tuple[ResearchEvidence, ...],
        gaps: tuple[ResearchGap, ...],
    ) -> DerivedResearchClaim: ...


class UserResearchResultProjector(Protocol):
    """Project internal records into the bounded user-facing result."""

    def project(
        self,
        *,
        cycle_id: str,
        request: ResearchRequest,
        claim: DerivedResearchClaim,
        gaps: tuple[ResearchGap, ...],
    ) -> UserResearchResult: ...
