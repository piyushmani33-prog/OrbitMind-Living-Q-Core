"""Live PostgreSQL integration tests for scientific memory (Phase 3B closure).

These exercise the REAL PostgreSQL path (full-text candidate selection, GIN index,
dialect labelling) that SQLite cannot cover. They skip cleanly unless a PostgreSQL
service is configured via ``ORBITMIND_TEST_POSTGRES_URL`` (a DISPOSABLE test database,
never a production/personal one). The test DB must already be migrated to head. Let
``URL=postgresql+psycopg://orbitmind:orbitmind@127.0.0.1:55432/orbitmind_test``; then::

    docker compose --profile postgres up -d
    ORBITMIND_DATABASE_URL=$URL python -m alembic upgrade head
    ORBITMIND_TEST_POSTGRES_URL=$URL python -m pytest -m postgres -v

On Windows use 127.0.0.1 (NOT localhost) to avoid a slow IPv6 fallback.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from orbitmind.api.container import AppContainer
from orbitmind.core.config import PROJECT_ROOT, Settings
from orbitmind.memory.evaluation import GoldItem
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
    RetrievalBackend,
    ScientificClaim,
    ScientificConcept,
)
from orbitmind.memory.repository import SqlAlchemyMemoryRepository
from orbitmind.memory.retrieval import MemorySearchRequest

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(
        not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB) to run"
    ),
]

_MEMORY_TABLES = (
    "evidence_links",
    "citation_records",
    "contradiction_records",
    "scientific_claims",
    "document_chunks",
    "document_sections",
    "document_versions",
    "scientific_documents",
    "memory_sources",
    "concept_terms",
    "concept_senses",
    "concept_relationships",
    "scientific_concepts",
    "memory_graph_edges",
    "ingestion_runs",
    "retrieval_runs",
)

_ADR = "docs/architecture/decisions/ADR-0005-quantum-boundary.md"
_GLOSSARY = "data/samples/memory/glossary.md"


@pytest.fixture
def pg_container(tmp_path: Path) -> AppContainer:
    """A container backed by the migrated PostgreSQL test DB, with memory data cleaned."""
    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "art",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
    )
    container = AppContainer(settings=settings)
    container.init_storage()
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_MEMORY_TABLES) + " RESTART IDENTITY CASCADE"))
    return container


def _exec(container: AppContainer, sql: str) -> list:
    with container.database.engine.connect() as conn:
        return list(conn.execute(text(sql)))


# --- schema / connection -------------------------------------------------
def test_connection_and_dialect(pg_container: AppContainer) -> None:
    assert pg_container.database.is_postgres
    assert _exec(pg_container, "SELECT 1")[0][0] == 1


def test_migrations_at_head_and_memory_tables_exist(pg_container: AppContainer) -> None:
    head = _exec(pg_container, "SELECT version_num FROM alembic_version")[0][0]
    assert head == "k6e7f8a9b0c2"  # current Alembic head (Phase 4B provenance link persistence)
    present = {
        r[0]
        for r in _exec(
            pg_container,
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'",
        )
    }
    for table in _MEMORY_TABLES:
        assert table in present


def test_tsvector_and_gin_index_exist(pg_container: AppContainer) -> None:
    idx = _exec(
        pg_container,
        "SELECT indexdef FROM pg_indexes WHERE indexname='ix_document_chunks_fts'",
    )
    assert idx, "FTS GIN index missing"
    indexdef = idx[0][0].lower()
    assert "gin" in indexdef and "to_tsvector" in indexdef and "search_text" in indexdef
    # tsvector matching physically works against the configuration.
    matched = _exec(
        pg_container,
        "SELECT to_tsvector('english','heliocentric asteroid') "
        "@@ plainto_tsquery('english','asteroid')",
    )
    assert matched[0][0] is True


# --- ingestion -----------------------------------------------------------
def test_ingestion_dedup_and_versioning(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    run, outcomes = svc.ingest(IngestionRequest(source_id="repo-docs", paths=[_ADR]))
    assert run.documents == 1 and run.chunks >= 1 and outcomes[0].status == "created"
    # Unchanged re-ingest -> duplicate, no new version.
    run2, _ = svc.ingest(IngestionRequest(source_id="repo-docs", paths=[_ADR]))
    assert run2.duplicates == 1 and run2.versions == 0


def test_unicode_and_scientific_notation_preserved(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    svc.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    session = pg_container.database.session()
    repo = SqlAlchemyMemoryRepository(session)
    docs = repo.list_documents(20, 0)
    joined = ""
    for doc in docs:
        for chunk in repo.get_chunks(doc.id):
            joined += chunk.original_text
    session.close()
    # Identifiers, Unicode symbols, and scientific notation survive round-trip.
    assert "1P/Halley" in joined and "NORAD 25544" in joined
    assert "≈ 0.05 au" in joined


# --- retrieval (real PostgreSQL FTS) -------------------------------------
def test_full_text_search_uses_postgres_backend(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    svc.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    result = svc.search(
        MemorySearchRequest(query_text="why is SGP4 not used for asteroids", limit=5)
    )
    assert result.backend is RetrievalBackend.POSTGRES_FTS  # NOT the SQLite fallback
    assert not result.zero_result and result.returned >= 1
    top = result.results[0]
    assert top.explanation.backend is RetrievalBackend.POSTGRES_FTS
    assert "heliocentric" in top.excerpt.lower() or "sgp4" in top.excerpt.lower()


def test_exact_identifier_search(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    svc.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    result = svc.search(MemorySearchRequest(query_text="25544", limit=5))
    assert any("25544" in r.explanation.matched_terms for r in result.results)


def test_metadata_and_epistemic_filtering(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    svc.ingest(IngestionRequest(source_id="repo-docs", paths=[_ADR]))
    svc.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    fixtures = svc.search(
        MemorySearchRequest(query_text="heliocentric orbits", document_types=["fixture"], limit=10)
    )
    assert fixtures.returned >= 1 and all(r.document_type == "fixture" for r in fixtures.results)
    none = svc.search(
        MemorySearchRequest(query_text="orbit", epistemic_statuses=["verified-fact"], limit=5)
    )
    assert none.zero_result


def test_citation_version_pinning(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    svc.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    result = svc.search(MemorySearchRequest(query_text="close approach impact", limit=3))
    top = result.results[0]
    assert top.citation.chunk_id == top.chunk_id
    assert top.citation.version_no == 1 and top.citation.checksum
    assert top.citation.char_end > top.citation.char_start


def test_gold_evaluation_on_postgres(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    svc.ingest(IngestionRequest(source_id="repo-docs", paths=[_ADR]))
    svc.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    gold_data = json.loads(
        (PROJECT_ROOT / "data" / "samples" / "memory" / "eval" / "gold.json").read_text("utf-8")
    )
    gold = [GoldItem(**item) for item in gold_data["items"]]
    report = svc.evaluate(gold, k=5)
    assert report.queries == 5
    assert report.recall_at_k >= 0.8
    assert report.citation_completeness == 1.0
    assert report.zero_result_rate == 0.0
    assert report.reproducible


# --- claims / evidence / graph -------------------------------------------
def test_claims_evidence_and_graph_persist(pg_container: AppContainer) -> None:
    svc = pg_container.memory_service
    svc.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    session = pg_container.database.session()
    chunk_id = (
        SqlAlchemyMemoryRepository(session)
        .get_chunks(SqlAlchemyMemoryRepository(session).list_documents(5, 0)[0].id)[0]
        .id
    )
    session.close()

    concept = svc.register_concept(
        ScientificConcept(
            canonical_name="Heliocentric orbit",
            domain=ConceptDomain.ORBITAL_MECHANICS,
            terms=[ConceptTerm(term="heliocentric", is_canonical=True)],
        )
    )
    claim = svc.register_claim(
        ScientificClaim(
            subject=ClaimSubject(value="SGP4"),
            predicate=ClaimPredicate(value="is-not-used-for"),
            object=ClaimObject(value="asteroids"),
            chunk_id=chunk_id,
        )
    )
    link = svc.link_evidence(
        EvidenceLink(
            claim_id=claim.id,
            chunk_id=chunk_id,
            support_type=EvidenceSupportType.SUPPORTS,
            source="samples",
            explanation="The glossary asserts SGP4 is never used for heliocentric bodies.",
        )
    )
    assert concept.id and claim.id and link.id

    # Graph edges + bounded, cycle-safe traversal.
    session = pg_container.database.session()
    repo = SqlAlchemyMemoryRepository(session)
    for a, b in (("A", "B"), ("B", "A"), ("B", "C")):
        repo.add_graph_edge(
            GraphEdge(
                from_ref=EntityReference(kind=EntityKind.DOCUMENT, entity_id=a),
                edge_kind=GraphEdgeKind.RELATED_TO,
                to_ref=EntityReference(kind=EntityKind.DOCUMENT, entity_id=b),
            )
        )
    session.commit()
    session.close()
    neighbors = svc.graph_neighbors("A", depth=10, limit=50)
    assert neighbors.depth == 3
    reached = {n.entity.entity_id for n in neighbors.neighbors}
    assert "B" in reached and "C" in reached

    detail_session = pg_container.database.session()
    evidence = SqlAlchemyMemoryRepository(detail_session).get_evidence_for_claim(claim.id)
    detail_session.close()
    assert len(evidence) == 1


# --- transaction safety & existing-domain integrity ----------------------
def test_transaction_rollback(pg_container: AppContainer) -> None:
    engine = pg_container.database.engine
    with engine.connect() as conn:
        trans = conn.begin()
        conn.execute(
            text(
                "INSERT INTO memory_sources (id, source_id, name, kind, rights, created_at) "
                "VALUES ('rollback-1','rollback-src','x','local-document','{}', now())"
            )
        )
        trans.rollback()
    remaining = _exec(pg_container, "SELECT count(*) FROM memory_sources WHERE id='rollback-1'")[0][
        0
    ]
    assert remaining == 0


def test_existing_satellite_and_small_body_tables_intact(pg_container: AppContainer) -> None:
    # Memory operations must not disturb existing domain schema/data. init_storage seeds
    # source definitions (satellite/CelesTrak/JPL); they survive memory ingestion.
    before = _exec(pg_container, "SELECT count(*) FROM source_definitions")[0][0]
    pg_container.memory_service.ingest(IngestionRequest(source_id="samples", paths=[_GLOSSARY]))
    after = _exec(pg_container, "SELECT count(*) FROM source_definitions")[0][0]
    assert after == before and before >= 1
    # The satellite mission + small-body tables exist and remain queryable.
    for table in ("missions", "space_objects", "small_body_orbits", "close_approaches"):
        _exec(pg_container, f"SELECT count(*) FROM {table}")
