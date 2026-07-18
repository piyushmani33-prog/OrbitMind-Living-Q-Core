"""Read-only Laboratory catalog API tests (deterministic, offline)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from orbitmind.api.routers.laboratory import router as laboratory_router

_LIST_PATH = "/api/v1/laboratories"
_DETAIL_PATH = "/api/v1/laboratories/development-laboratory"


def test_list_is_deterministic_and_registry_backed(client: TestClient) -> None:
    first = client.get(_LIST_PATH)
    second = client.get(_LIST_PATH)
    assert first.status_code == 200
    assert first.json() == second.json()
    payload = first.json()
    assert payload["schema_version"] == "laboratory-catalog-v1"
    assert payload["generated_from"] == "deterministic-laboratory-registry"
    assert [lab["laboratory_id"] for lab in payload["laboratories"]] == ["development-laboratory"]
    assert "does not grant permission" in payload["capability_principle"]
    for planned in payload["planned_laboratories"]:
        assert planned["status"] == "planned — no runtime implementation"


def test_list_exact_top_level_schema(client: TestClient) -> None:
    payload = client.get(_LIST_PATH).json()
    assert set(payload) == {
        "schema_version",
        "generated_from",
        "capability_principle",
        "laboratories",
        "planned_laboratories",
        "mission_flow",
        "evidence_chain",
        "safety_boundaries",
        "offline_boundary_statements",
    }


def test_detail_exact_manifest_schema(client: TestClient) -> None:
    response = client.get(_DETAIL_PATH)
    assert response.status_code == 200
    manifest = response.json()
    assert set(manifest) == {
        "schema_version",
        "laboratory_id",
        "display_name",
        "laboratory_version",
        "domain",
        "description",
        "implementation_status",
        "capabilities",
        "accepted_goal_categories",
        "required_deterministic_services",
        "adapters",
        "produced_artifact_categories",
        "produced_evidence_categories",
        "network_posture",
        "hardware_posture",
        "persistence_posture",
        "approval_gates",
        "replay_support",
        "verification_requirements",
        "resource_boundaries",
        "compatibility",
        "limitations",
        "deprecation_state",
    }
    for declaration in manifest["capabilities"]:
        assert declaration["tool_connected"] is False
        assert declaration["adapter_connected"] is False
        assert declaration["execution_authority"] == "none"


def test_unknown_laboratory_is_a_safe_404(client: TestClient) -> None:
    response = client.get("/api/v1/laboratories/no-such-laboratory")
    assert response.status_code == 404
    assert response.json() == {"code": "unknown_laboratory", "message": "laboratory not found"}
    oversized = client.get("/api/v1/laboratories/" + "a" * 200)
    assert oversized.status_code == 404


def test_no_sensitive_paths_or_secrets_in_responses(client: TestClient) -> None:
    list_text = client.get(_LIST_PATH).text
    detail_text = client.get(_DETAIL_PATH).text
    for body in (list_text, detail_text):
        for marker in (
            "E:\\\\",
            "C:\\\\",
            "src/orbitmind",
            "site-packages",
            ".venv",
            "sqlite:",
            "secret",
            "token",
            "password",
            "Authorization",
        ):
            assert marker not in body, marker


def test_laboratory_surface_has_no_write_or_execution_route() -> None:
    routes = list(laboratory_router.routes)
    paths = sorted(getattr(route, "path", "") for route in routes)
    assert paths == [
        "/api/v1/laboratories",
        "/api/v1/laboratories/{laboratory_id}",
        "/assets/laboratory.js",
        "/workbench/laboratory",
    ]
    for route in routes:
        methods = getattr(route, "methods", set()) or set()
        assert methods <= {"GET", "HEAD"}, (
            f"non-read method on {getattr(route, 'path', route)}: {methods}"
        )
        path = getattr(route, "path", "")
        for forbidden in ("activate", "execute", "run", "agent", "provider"):
            assert forbidden not in path


def test_laboratory_routes_are_served_by_the_app(client: TestClient) -> None:
    assert client.get(_LIST_PATH).status_code == 200
    assert client.get("/workbench/laboratory").status_code == 200
    assert client.get("/assets/laboratory.js").status_code == 200
