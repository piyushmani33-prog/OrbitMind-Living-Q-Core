"""End-to-end API tests for the scientific-memory endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from orbitmind.api.memory_schemas import MEMORY_DISCLAIMER

_ADR = "docs/architecture/decisions/ADR-0005-quantum-boundary.md"


def _ingest(client: TestClient, paths: list[str], source: str = "repo-docs") -> dict:
    resp = client.post("/api/v1/memory/ingestion-runs", json={"source_id": source, "paths": paths})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_ingest_then_list_documents_and_chunks(client: TestClient) -> None:
    body = _ingest(client, [_ADR])
    assert body["run"]["documents"] == 1
    assert body["disclaimer"] == MEMORY_DISCLAIMER

    docs = client.get("/api/v1/memory/documents").json()
    assert docs["total"] >= 1
    doc_id = docs["items"][0]["id"]

    chunks = client.get(f"/api/v1/memory/documents/{doc_id}/chunks").json()
    assert chunks["document_id"] == doc_id and len(chunks["chunks"]) >= 1


def test_ingest_rejects_non_allowlisted_paths(client: TestClient) -> None:
    body = _ingest(client, ["pyproject.toml", ".env"])
    assert body["run"]["documents"] == 0 and body["run"]["rejected"] == 2


def test_search_returns_evidence_with_disclaimer(client: TestClient) -> None:
    _ingest(client, [_ADR])
    resp = client.post(
        "/api/v1/memory/search",
        json={"query_text": "quantum simulator classical baseline", "limit": 5},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["disclaimer"] == MEMORY_DISCLAIMER
    result = body["result"]
    assert result["backend"] == "deterministic-lexical"
    if result["returned"]:
        top = result["results"][0]
        assert top["citation"]["chunk_id"] == top["chunk_id"]
        assert top["epistemic_status"] == "assumption"


def test_search_validation_rejects_bad_filters(client: TestClient) -> None:
    bad_type = client.post(
        "/api/v1/memory/search",
        json={"query_text": "orbit", "document_types": ["not-a-type"]},
    )
    assert bad_type.status_code == 422
    bad_sort = client.post("/api/v1/memory/search", json={"query_text": "orbit", "sort": "wat"})
    assert bad_sort.status_code == 422


def test_concept_claim_evidence_flow(client: TestClient) -> None:
    _ingest(client, [_ADR])
    doc_id = client.get("/api/v1/memory/documents").json()["items"][0]["id"]
    chunk_id = client.get(f"/api/v1/memory/documents/{doc_id}/chunks").json()["chunks"][0]["id"]

    concept = client.post(
        "/api/v1/memory/concepts",
        json={
            "canonical_name": "Quantum boundary",
            "domain": "quantum-computing",
            "terms": [{"term": "quantum boundary", "is_canonical": True}],
        },
    )
    assert concept.status_code == 200, concept.text
    assert client.get("/api/v1/memory/concepts?domain=quantum-computing").json()["items"]

    claim = client.post(
        "/api/v1/memory/claims",
        json={
            "subject": {"value": "Quantum"},
            "predicate": {"value": "is-bounded-to"},
            "object": {"value": "simulator"},
            "chunk_id": chunk_id,
        },
    )
    assert claim.status_code == 200, claim.text
    claim_id = claim.json()["id"]
    assert claim.json()["status"] == "source-asserted"
    assert claim.json()["epistemic_status"] == "assumption"

    evidence = client.post(
        "/api/v1/memory/evidence",
        json={
            "claim_id": claim_id,
            "chunk_id": chunk_id,
            "support_type": "supports",
            "source": "repo-docs",
            "explanation": "ADR-0005 bounds quantum to a simulator off the mission path.",
        },
    )
    assert evidence.status_code == 200, evidence.text

    detail = client.get(f"/api/v1/memory/claims/{claim_id}").json()
    assert detail["claim"]["id"] == claim_id
    assert len(detail["evidence"]) == 1
    assert detail["disclaimer"] == MEMORY_DISCLAIMER


def test_dangling_claim_rejected_by_api(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/memory/claims",
        json={
            "subject": {"value": "x"},
            "predicate": {"value": "y"},
            "object": {"value": "z"},
            "chunk_id": "no-such-chunk",
        },
    )
    assert resp.status_code in (400, 422)


def test_graph_neighbors_endpoint(client: TestClient) -> None:
    resp = client.get("/api/v1/memory/graph/unknown-entity/neighbors?depth=2")
    assert resp.status_code == 200
    assert resp.json()["entity_id"] == "unknown-entity"


def test_evaluation_endpoint(client: TestClient) -> None:
    _ingest(client, ["data/samples/memory/glossary.md"], source="samples")
    resp = client.post(
        "/api/v1/memory/evaluations",
        json={
            "k": 5,
            "gold": [
                {
                    "query": "why is SGP4 not used for asteroids",
                    "relevant_markers": ["heliocentric"],
                },
                {"query": "is a close approach an impact", "relevant_markers": ["NOT an impact"]},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    report = resp.json()
    assert report["queries"] == 2 and report["reproducible"] is True


def test_document_not_found(client: TestClient) -> None:
    assert client.get("/api/v1/memory/documents/does-not-exist").status_code == 404
