"""Claims, evidence, concepts, and the bounded knowledge graph."""

from __future__ import annotations

import pytest

from orbitmind.api.container import AppContainer
from orbitmind.core.errors import ValidationError
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.memory.graph import GraphService
from orbitmind.memory.models import (
    ClaimObject,
    ClaimPredicate,
    ClaimStatus,
    ClaimSubject,
    ConceptDomain,
    ConceptTerm,
    EntityKind,
    EntityReference,
    EvidenceLink,
    EvidenceSupportType,
    GraphEdge,
    GraphEdgeKind,
    ScientificClaim,
    ScientificConcept,
)
from orbitmind.memory.repository import SqlAlchemyMemoryRepository


def _a_chunk_id(container: AppContainer) -> str:
    session = container.database.session()
    repo = SqlAlchemyMemoryRepository(session)
    docs = repo.list_documents(10, 0)
    chunks = repo.get_chunks(docs[0].id)
    session.close()
    return chunks[0].id


def test_register_claim_defaults_to_source_asserted_with_provenance(
    memory_corpus: AppContainer,
) -> None:
    chunk_id = _a_chunk_id(memory_corpus)
    claim = ScientificClaim(
        subject=ClaimSubject(value="SGP4"),
        predicate=ClaimPredicate(value="is-not-used-for"),
        object=ClaimObject(value="asteroids"),
        chunk_id=chunk_id,
    )
    registered = memory_corpus.memory_service.register_claim(claim)
    assert registered.status == ClaimStatus.SOURCE_ASSERTED
    assert registered.epistemic_status == EpistemicStatus.ASSUMPTION  # never verified-fact
    assert (
        registered.chunk_id == chunk_id and "not independently verified" in registered.limitations
    )


def test_incomplete_or_dangling_claim_is_rejected(memory_corpus: AppContainer) -> None:
    with pytest.raises(ValidationError):
        memory_corpus.memory_service.register_claim(
            ScientificClaim(
                subject=ClaimSubject(value=""),
                predicate=ClaimPredicate(value="p"),
                object=ClaimObject(value="o"),
            )
        )
    with pytest.raises(ValidationError):
        memory_corpus.memory_service.register_claim(
            ScientificClaim(
                subject=ClaimSubject(value="s"),
                predicate=ClaimPredicate(value="p"),
                object=ClaimObject(value="o"),
                chunk_id="does-not-exist",
            )
        )


def test_evidence_validation(memory_corpus: AppContainer) -> None:
    chunk_id = _a_chunk_id(memory_corpus)
    claim = memory_corpus.memory_service.register_claim(
        ScientificClaim(
            subject=ClaimSubject(value="close approach"),
            predicate=ClaimPredicate(value="is-not"),
            object=ClaimObject(value="impact"),
            chunk_id=chunk_id,
        )
    )
    link = memory_corpus.memory_service.link_evidence(
        EvidenceLink(
            claim_id=claim.id,
            chunk_id=chunk_id,
            support_type=EvidenceSupportType.SUPPORTS,
            source="repo-docs",
            explanation="The glossary states a close approach is not an impact.",
        )
    )
    assert link.id

    # Dangling claim reference rejected.
    with pytest.raises(ValidationError):
        memory_corpus.memory_service.link_evidence(
            EvidenceLink(
                claim_id="missing",
                chunk_id=chunk_id,
                support_type=EvidenceSupportType.SUPPORTS,
                source="x",
                explanation="y",
            )
        )
    # Neither chunk nor record reference rejected.
    with pytest.raises(ValidationError):
        memory_corpus.memory_service.link_evidence(
            EvidenceLink(
                claim_id=claim.id,
                support_type=EvidenceSupportType.SUPPORTS,
                source="x",
                explanation="y",
            )
        )


def test_register_and_query_concept(container: AppContainer) -> None:
    concept = ScientificConcept(
        canonical_name="Two-Line Element set",
        domain=ConceptDomain.ORBITAL_MECHANICS,
        definition="Encodes orbital elements at an epoch.",
        terms=[
            ConceptTerm(term="TLE", is_canonical=True),
            ConceptTerm(term="Two-Line Element"),
        ],
    )
    registered = container.memory_service.register_concept(concept)
    session = container.database.session()
    repo = SqlAlchemyMemoryRepository(session)
    assert registered.id in repo.find_concept_ids_by_term("tle")
    listed = repo.list_concepts(10, 0, ConceptDomain.ORBITAL_MECHANICS.value)
    session.close()
    assert any(c.canonical_name == "Two-Line Element set" for c in listed)


def _edge(a: str, b: str) -> GraphEdge:
    return GraphEdge(
        from_ref=EntityReference(kind=EntityKind.DOCUMENT, entity_id=a),
        edge_kind=GraphEdgeKind.RELATED_TO,
        to_ref=EntityReference(kind=EntityKind.DOCUMENT, entity_id=b),
    )


def test_graph_traversal_is_bounded_and_cycle_safe(container: AppContainer) -> None:
    session = container.database.session()
    repo = SqlAlchemyMemoryRepository(session)
    graph = GraphService()
    graph.add_edge(_edge("A", "B"), repo)
    graph.add_edge(_edge("B", "A"), repo)  # cycle
    graph.add_edge(_edge("B", "C"), repo)
    session.commit()

    result = graph.neighbors("A", repo, depth=10, limit=50)  # depth clamped to 3
    session.close()
    assert result.depth == 3  # clamped, no error, terminates despite the cycle
    reached = {n.entity.entity_id for n in result.neighbors}
    assert "B" in reached and "C" in reached
