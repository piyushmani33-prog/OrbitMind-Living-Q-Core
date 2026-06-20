"""API wire schemas for scientific memory (Phase 3B)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from orbitmind.memory.evaluation import GoldItem
from orbitmind.memory.ingestion import FileOutcome
from orbitmind.memory.models import (
    DocumentChunk,
    EvidenceLink,
    IngestionRun,
    RetrievalResult,
    ScientificClaim,
    ScientificConcept,
    ScientificDocument,
)

MEMORY_DISCLAIMER = (
    "Scientific memory returns source-asserted evidence and ranked, citable passages — "
    "NOT verified facts and NOT a generated answer. A source asserting a claim does not "
    "make it true; retrieval is not verification."
)


class IngestionResponse(BaseModel):
    run: IngestionRun
    outcomes: list[FileOutcome]
    disclaimer: str = MEMORY_DISCLAIMER


class MemorySearchResponse(BaseModel):
    result: RetrievalResult
    disclaimer: str = MEMORY_DISCLAIMER


class DocumentListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ScientificDocument]


class ChunkListResponse(BaseModel):
    document_id: str
    chunks: list[DocumentChunk]


class ConceptListResponse(BaseModel):
    items: list[ScientificConcept]


class ClaimDetailResponse(BaseModel):
    claim: ScientificClaim
    evidence: list[EvidenceLink]
    disclaimer: str = MEMORY_DISCLAIMER


class ClaimListResponse(BaseModel):
    items: list[ScientificClaim]
    disclaimer: str = MEMORY_DISCLAIMER


class EvaluationRequest(BaseModel):
    gold: list[GoldItem] = Field(min_length=1, max_length=200)
    k: int = Field(default=5, ge=1, le=50)


__all__ = [
    "MEMORY_DISCLAIMER",
    "ChunkListResponse",
    "ClaimDetailResponse",
    "ClaimListResponse",
    "ConceptListResponse",
    "DocumentListResponse",
    "EvaluationRequest",
    "IngestionResponse",
    "MemorySearchResponse",
]
