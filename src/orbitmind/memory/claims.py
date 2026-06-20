"""Conservative claim-registration service (no open-ended LLM extraction).

A source asserting a claim is NOT a verified fact. Claims preserve provenance and an
explicit epistemic + verification status; incomplete claims are rejected.
"""

from __future__ import annotations

from orbitmind.core.errors import ValidationError
from orbitmind.memory.models import ScientificClaim
from orbitmind.memory.repository import SqlAlchemyMemoryRepository


class ClaimService:
    """Validates and registers typed scientific claims."""

    def register(self, claim: ScientificClaim, repo: SqlAlchemyMemoryRepository) -> ScientificClaim:
        if not claim.subject.value.strip():
            raise ValidationError("claim subject is required")
        if not claim.predicate.value.strip():
            raise ValidationError("claim predicate is required")
        if not claim.object.value.strip():
            raise ValidationError("claim object/value is required")
        if claim.chunk_id is not None and not repo.chunk_exists(claim.chunk_id):
            raise ValidationError("claim references a nonexistent chunk")
        repo.add_claim(claim)
        return claim
