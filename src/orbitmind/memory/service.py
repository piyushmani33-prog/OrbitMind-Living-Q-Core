"""Scientific-memory service facade: session management + audit around the modules.

Retrieval returns ranked, citable evidence — never a generated answer (deferred).
"""

from __future__ import annotations

import time

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.config import Settings
from orbitmind.core.logging import get_logger
from orbitmind.governance.audit import AuditAction, AuditEvent
from orbitmind.memory.claims import ClaimService
from orbitmind.memory.concepts import ConceptService
from orbitmind.memory.evaluation import EvaluationReport, GoldItem, RetrievalEvaluator
from orbitmind.memory.evidence import EvidenceService
from orbitmind.memory.graph import GraphService
from orbitmind.memory.ingestion import FileOutcome, IngestionRequest, IngestionService
from orbitmind.memory.models import (
    EvidenceLink,
    GraphNeighborsResult,
    IngestionRun,
    RetrievalResult,
    ScientificClaim,
    ScientificConcept,
)
from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.memory.retrieval import MemorySearchRequest, MemorySearchService
from orbitmind.persistence.database import Database
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository

_log = get_logger("memory.service")


class MemoryService:
    """Coordinates ingestion, retrieval, concepts, claims, evidence, and graph."""

    def __init__(self, *, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._db = database
        self._ingestion = IngestionService(settings)
        self._search = MemorySearchService()
        self._concepts = ConceptService()
        self._claims = ClaimService()
        self._evidence = EvidenceService()
        self._graph = GraphService()
        self._evaluator = RetrievalEvaluator(self._search)

    def ingest(self, request: IngestionRequest) -> tuple[IngestionRun, list[FileOutcome]]:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyMemoryRepository(session)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.INGESTION_REQUESTED,
                    detail={"source": request.source_id, "requested": len(request.paths)},
                )
            )
            audit.add_audit_event(AuditEvent(action=AuditAction.INGESTION_STARTED))
            run, outcomes = self._ingestion.ingest(request, repo)
            for outcome in outcomes:
                if outcome.status == "rejected":
                    action = AuditAction.FILE_REJECTED
                elif outcome.status == "duplicate":
                    action = AuditAction.DUPLICATE_DETECTED
                else:
                    action = AuditAction.FILE_ACCEPTED
                audit.add_audit_event(AuditEvent(action=action, detail={"label": outcome.label}))
                if outcome.status in ("created", "updated"):
                    audit.add_audit_event(
                        AuditEvent(
                            action=AuditAction.DOCUMENT_VERSION_CREATED,
                            detail={"label": outcome.label, "chunks": outcome.chunks},
                        )
                    )
            audit.add_audit_event(
                AuditEvent(action=AuditAction.CHUNKING_COMPLETED, detail={"chunks": run.chunks})
            )
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.INGESTION_COMPLETED,
                    detail={"status": run.status.value, "documents": run.documents},
                )
            )
            session.commit()
        _log.info("memory.ingested", documents=run.documents, chunks=run.chunks)
        return run, outcomes

    def search(self, request: MemorySearchRequest) -> RetrievalResult:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyMemoryRepository(session)
            audit.add_audit_event(AuditEvent(action=AuditAction.RETRIEVAL_REQUESTED))
            started = time.perf_counter()
            result = self._search.search(
                request,
                repo,
                is_postgres=self._db.is_postgres,
                language=self._settings.memory_fts_language,
            )
            latency_ms = (time.perf_counter() - started) * 1000.0
            repo.add_retrieval_run(
                result,
                latency_ms,
                sha256_canonical_json(request.model_dump(mode="json")),
            )
            if result.truncated:
                audit.add_audit_event(
                    AuditEvent(
                        action=AuditAction.MEMORY_RESULT_TRUNCATED,
                        detail={"returned": result.returned, "total": result.total_candidates},
                    )
                )
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.RETRIEVAL_COMPLETED,
                    detail={"backend": result.backend.value, "returned": result.returned},
                )
            )
            session.commit()
        return result

    def register_concept(self, concept: ScientificConcept) -> ScientificConcept:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyMemoryRepository(session)
            registered = self._concepts.register(concept, repo)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.CONCEPT_REGISTERED,
                    detail={
                        "concept": registered.canonical_name,
                        "domain": registered.domain.value,
                    },
                )
            )
            session.commit()
        return registered

    def register_claim(self, claim: ScientificClaim) -> ScientificClaim:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyMemoryRepository(session)
            registered = self._claims.register(claim, repo)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.CLAIM_REGISTERED,
                    detail={"claim_id": registered.id, "status": registered.status.value},
                )
            )
            session.commit()
        return registered

    def link_evidence(self, link: EvidenceLink) -> EvidenceLink:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyMemoryRepository(session)
            registered = self._evidence.link(link, repo)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.EVIDENCE_LINKED,
                    detail={
                        "claim_id": registered.claim_id,
                        "support": registered.support_type.value,
                    },
                )
            )
            session.commit()
        return registered

    def graph_neighbors(self, entity_id: str, *, depth: int, limit: int) -> GraphNeighborsResult:
        with self._db.session() as session:
            audit = SqlAlchemyMissionRepository(session)
            repo = SqlAlchemyMemoryRepository(session)
            audit.add_audit_event(
                AuditEvent(
                    action=AuditAction.GRAPH_TRAVERSAL_REQUESTED,
                    detail={"entity_id": entity_id, "depth": depth},
                )
            )
            result = self._graph.neighbors(entity_id, repo, depth=depth, limit=limit)
            session.commit()
        return result

    def evaluate(self, gold: list[GoldItem], *, k: int = 5) -> EvaluationReport:
        with self._db.session() as session:
            repo = SqlAlchemyMemoryRepository(session)
            return self._evaluator.evaluate(
                gold,
                repo,
                k=k,
                is_postgres=self._db.is_postgres,
                language=self._settings.memory_fts_language,
            )
