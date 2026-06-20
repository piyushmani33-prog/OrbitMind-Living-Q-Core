"""Evidence-link service. Evidence may not reference nonexistent claims/records."""

from __future__ import annotations

from orbitmind.core.errors import ValidationError
from orbitmind.memory.models import EvidenceLink
from orbitmind.memory.repository import SqlAlchemyMemoryRepository


class EvidenceService:
    """Validates and registers typed evidence links."""

    def link(self, link: EvidenceLink, repo: SqlAlchemyMemoryRepository) -> EvidenceLink:
        if not repo.claim_exists(link.claim_id):
            raise ValidationError("evidence references a nonexistent claim")
        if link.chunk_id is None and not link.record_ref:
            raise ValidationError("evidence must reference a chunk or a structured record")
        if link.chunk_id is not None and not repo.chunk_exists(link.chunk_id):
            raise ValidationError("evidence references a nonexistent chunk")
        repo.add_evidence(link)
        return link
