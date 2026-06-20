"""Scientific-memory routers: ingestion, retrieval, concepts, claims, evidence, graph.

Retrieval returns ranked, citable evidence — never a generated answer.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from orbitmind.api.deps import get_memory_repository, get_memory_service
from orbitmind.api.memory_schemas import (
    ChunkListResponse,
    ClaimDetailResponse,
    ClaimListResponse,
    ConceptListResponse,
    DocumentListResponse,
    EvaluationRequest,
    IngestionResponse,
    MemorySearchResponse,
)
from orbitmind.core.errors import NotFoundError
from orbitmind.memory.evaluation import EvaluationReport
from orbitmind.memory.ingestion import IngestionRequest
from orbitmind.memory.models import (
    EvidenceLink,
    GraphNeighborsResult,
    IngestionRun,
    IngestionStatus,
    ScientificClaim,
    ScientificConcept,
    ScientificDocument,
)
from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.memory.retrieval import MemorySearchRequest
from orbitmind.memory.service import MemoryService

router = APIRouter(prefix="/api/v1/memory", tags=["memory"])

ServiceDep = Annotated[MemoryService, Depends(get_memory_service)]
RepoDep = Annotated[SqlAlchemyMemoryRepository, Depends(get_memory_repository)]


# --- ingestion -----------------------------------------------------------
@router.post("/ingestion-runs", response_model=IngestionResponse)
def ingest(payload: IngestionRequest, service: ServiceDep) -> IngestionResponse:
    """Ingest approved documents (allowlisted paths only; contents never executed)."""
    run, outcomes = service.ingest(payload)
    return IngestionResponse(run=run, outcomes=outcomes)


@router.get("/ingestion-runs/{run_id}", response_model=IngestionRun)
def get_ingestion_run(run_id: str, repo: RepoDep) -> IngestionRun:
    row = repo.get_ingestion_run(run_id)
    if row is None:
        raise NotFoundError("ingestion run not found")
    return IngestionRun(
        id=row.id,
        status=IngestionStatus(row.status),
        roots=list(row.roots or []),
        requested=row.requested,
        accepted=row.accepted,
        rejected=row.rejected,
        duplicates=row.duplicates,
        documents=row.documents,
        versions=row.versions,
        chunks=row.chunks,
        errors=list(row.errors or []),
        started_at=row.started_at,
        finished_at=row.finished_at,
    )


# --- documents -----------------------------------------------------------
@router.get("/documents", response_model=DocumentListResponse)
def list_documents(
    repo: RepoDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentListResponse:
    return DocumentListResponse(
        total=repo.count_documents(),
        limit=limit,
        offset=offset,
        items=repo.list_documents(limit, offset),
    )


@router.get("/documents/{document_id}", response_model=ScientificDocument)
def get_document(document_id: str, repo: RepoDep) -> ScientificDocument:
    doc = repo.get_document(document_id)
    if doc is None:
        raise NotFoundError("document not found")
    return doc


@router.get("/documents/{document_id}/chunks", response_model=ChunkListResponse)
def get_document_chunks(document_id: str, repo: RepoDep) -> ChunkListResponse:
    if repo.get_document(document_id) is None:
        raise NotFoundError("document not found")
    return ChunkListResponse(document_id=document_id, chunks=repo.get_chunks(document_id))


# --- retrieval -----------------------------------------------------------
@router.post("/search", response_model=MemorySearchResponse)
def search(payload: MemorySearchRequest, service: ServiceDep) -> MemorySearchResponse:
    """Deterministic evidence retrieval (ranked, citable passages; not an answer)."""
    return MemorySearchResponse(result=service.search(payload))


# --- concepts ------------------------------------------------------------
@router.post("/concepts", response_model=ScientificConcept)
def register_concept(payload: ScientificConcept, service: ServiceDep) -> ScientificConcept:
    return service.register_concept(payload)


@router.get("/concepts", response_model=ConceptListResponse)
def list_concepts(
    repo: RepoDep,
    domain: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConceptListResponse:
    return ConceptListResponse(items=repo.list_concepts(limit, offset, domain))


@router.get("/concepts/{concept_id}", response_model=ScientificConcept)
def get_concept(concept_id: str, repo: RepoDep) -> ScientificConcept:
    concept = repo.get_concept(concept_id)
    if concept is None:
        raise NotFoundError("concept not found")
    return concept


# --- claims / evidence ---------------------------------------------------
@router.post("/claims", response_model=ScientificClaim)
def register_claim(payload: ScientificClaim, service: ServiceDep) -> ScientificClaim:
    return service.register_claim(payload)


@router.get("/claims", response_model=ClaimListResponse)
def list_claims(
    repo: RepoDep,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ClaimListResponse:
    return ClaimListResponse(items=repo.list_claims(limit, offset, status))


@router.get("/claims/{claim_id}", response_model=ClaimDetailResponse)
def get_claim(claim_id: str, repo: RepoDep) -> ClaimDetailResponse:
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise NotFoundError("claim not found")
    return ClaimDetailResponse(claim=claim, evidence=repo.get_evidence_for_claim(claim_id))


@router.post("/evidence", response_model=EvidenceLink)
def link_evidence(payload: EvidenceLink, service: ServiceDep) -> EvidenceLink:
    return service.link_evidence(payload)


# --- graph ---------------------------------------------------------------
@router.get("/graph/{entity_id}/neighbors", response_model=GraphNeighborsResult)
def graph_neighbors(
    entity_id: str,
    service: ServiceDep,
    depth: Annotated[int, Query(ge=1, le=3)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> GraphNeighborsResult:
    return service.graph_neighbors(entity_id, depth=depth, limit=limit)


# --- evaluation ----------------------------------------------------------
@router.post("/evaluations", response_model=EvaluationReport)
def evaluate(payload: EvaluationRequest, service: ServiceDep) -> EvaluationReport:
    """Run deterministic retrieval evaluation against a supplied gold dataset."""
    return service.evaluate(payload.gold, k=payload.k)
