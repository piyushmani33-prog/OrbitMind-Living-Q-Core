"""Populate a disposable PostgreSQL DB with a small memory corpus for the backup smoke
test (section 13): one document, concept, claim, evidence link, graph relationship, and
an existing-domain entity reference. Prints counts + a chunk checksum for comparison."""

from __future__ import annotations

from orbitmind.api.container import AppContainer
from orbitmind.memory.ingestion import IngestionRequest
from orbitmind.memory.models import (
    ClaimObject,
    ClaimPredicate,
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


def main() -> None:
    container = AppContainer()
    assert container.database.is_postgres
    svc = container.memory_service
    svc.ingest(IngestionRequest(source_id="samples", paths=["data/samples/memory/glossary.md"]))

    session = container.database.session()
    repo = SqlAlchemyMemoryRepository(session)
    doc = repo.list_documents(5, 0)[0]
    chunk = repo.get_chunks(doc.id)[0]
    session.close()

    svc.register_concept(
        ScientificConcept(
            canonical_name="Close approach",
            domain=ConceptDomain.CLOSE_APPROACH,
            terms=[ConceptTerm(term="close approach", is_canonical=True)],
        )
    )
    claim = svc.register_claim(
        ScientificClaim(
            subject=ClaimSubject(value="close approach"),
            predicate=ClaimPredicate(value="is-not"),
            object=ClaimObject(value="impact"),
            chunk_id=chunk.id,
        )
    )
    svc.link_evidence(
        EvidenceLink(
            claim_id=claim.id,
            chunk_id=chunk.id,
            support_type=EvidenceSupportType.SUPPORTS,
            source="samples",
            explanation="Glossary asserts a close approach is not an impact.",
        )
    )
    # Graph relationship + existing-domain entity reference (space-object -> document).
    session = container.database.session()
    repo = SqlAlchemyMemoryRepository(session)
    repo.add_graph_edge(
        GraphEdge(
            from_ref=EntityReference(kind=EntityKind.SPACE_OBJECT, entity_id="2P/Encke"),
            edge_kind=GraphEdgeKind.MENTIONS,
            to_ref=EntityReference(kind=EntityKind.DOCUMENT, entity_id=doc.id),
        )
    )
    session.commit()
    session.close()

    with container.database.engine.connect() as conn:
        from sqlalchemy import text

        def count(table: str) -> int:
            return int(conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())

        print(
            "COUNTS "
            f"documents={count('scientific_documents')} chunks={count('document_chunks')} "
            f"concepts={count('scientific_concepts')} claims={count('scientific_claims')} "
            f"evidence={count('evidence_links')} edges={count('memory_graph_edges')}"
        )
        print("CHUNK0_CHECKSUM " + chunk.checksum)


if __name__ == "__main__":
    main()
