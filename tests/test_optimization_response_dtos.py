"""Schema-snapshot tests for optimization response DTOs (second Codex review, Medium #19).

Responses are explicit allowlists: a new internal domain field must NOT automatically become
public, and forbidden internals (mutable evidence object, raw samples, on-disk artifact paths,
execution limits, runtimes) must never appear in a response.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from orbitmind.api.optimization_schemas import BenchmarkEvidenceGraphResponse, EvidenceEdgeView
from orbitmind.api.optimization_views import (
    ArtifactView,
    BenchmarkView,
    ComparisonView,
    OpportunityView,
    ProblemView,
    QuantumExperimentView,
    RunSummaryView,
    SolverResultView,
)

# Pinned public field sets. Changing a public response surface must be a DELIBERATE edit here.
_SNAPSHOTS = {
    ProblemView: {
        "id",
        "name",
        "checksum",
        "num_variables",
        "source",
        "epistemic_status",
        "limitations",
        "opportunities",
    },
    OpportunityView: {
        "id",
        "satellite_id",
        "target_id",
        "window",
        "mission_value",
        "duration_seconds",
        "energy_cost",
        "storage_cost",
        "priority",
        "provenance",
    },
    SolverResultView: {
        "id",
        "solver_kind",
        "solver_name",
        "solver_version",
        "status",
        "optimality_status",
        "objective_value",
        "known_optimum",
        "objective_gap",
        "feasible",
        "selected_opportunity_ids",
    },
    QuantumExperimentView: {
        "id",
        "status",
        "qubits",
        "depth",
        "shots",
        "total_shots",
        "distinct_samples",
        "feasible_sample_ratio",
        "objective_gap",
        "exact_optimum_in_samples",
        "best_feasible_objective",
        "qubo_checksum",
        "manifest_checksum",
        "penalty_proof_status",
        "bit_order",
        "limitations",
    },
    ComparisonView: {
        "conclusion",
        "exact_objective",
        "greedy_objective",
        "quantum_objective",
        "known_optimum",
        "objective_gap",
        "policy_id",
        "policy_version",
        "competitive_relative_gap",
        "min_feasible_sample_ratio",
        "rationale",
        "epistemic_status",
        "limitations",
    },
    ArtifactView: {"id", "type", "checksum", "media_type", "created_at", "epistemic_status"},
    RunSummaryView: {
        "id",
        "problem_checksum",
        "verified",
        "integrity_failed",
        "conclusion",
        "created_at",
        "has_quantum",
        "receipt_status",
        "artifact_count",
    },
    EvidenceEdgeView: {
        "edge_kind",
        "direction",
        "entity_kind",
        "entity_id",
        "integrity_failed",
    },
    BenchmarkView: {
        "id",
        "problem_checksum",
        "conclusion",
        "verified",
        "solver_results",
        "quantum",
        "comparison",
        "artifacts",
    },
}


def test_response_dtos_match_pinned_snapshots() -> None:
    for view, expected in _SNAPSHOTS.items():
        assert set(view.model_fields) == expected, f"{view.__name__} public surface changed"


def _create(client: TestClient) -> str:
    resp = client.post("/api/v1/optimization/problems", json={"fixture": "default"})
    assert resp.status_code == 200
    return resp.json()["id"]


def test_benchmark_response_hides_internal_fields(client: TestClient) -> None:
    pid = _create(client)
    body = client.post(
        f"/api/v1/optimization/problems/{pid}/benchmark",
        json={"seed": 7, "run_quantum": False, "generate_artifacts": True},
    ).json()
    run = body["run"]
    # No mutable evidence object, no execution limits, no raw provenance dump at run level.
    assert "evidence" not in run and "limits" not in run
    # Artifacts never expose on-disk paths in any response.
    for art in run["artifacts"]:
        assert "path" not in art and "sidecar_path" not in art
    # Solver results expose the reviewed surface only (no resource_usage / runtimes / config).
    for r in run["solver_results"]:
        assert (
            "resource_usage" not in r and "configuration" not in r and "software_versions" not in r
        )
    # The dedicated artifacts endpoint is also path-free.
    arts = client.get(f"/api/v1/optimization/runs/{run['id']}/artifacts").json()["artifacts"]
    assert arts
    for art in arts:
        assert "path" not in art and "sidecar_path" not in art
        assert set(art) <= {
            "id",
            "type",
            "checksum",
            "media_type",
            "created_at",
            "epistemic_status",
        }


def test_problem_response_hides_limits(client: TestClient) -> None:
    pid = _create(client)
    got = client.get(f"/api/v1/optimization/problems/{pid}").json()
    assert "limits" not in got  # execution bounds are internal
    assert got["opportunities"][0]["window"]["start"]  # reviewed shape preserved


def test_openapi_pins_run_summary_and_evidence_edge_surface(client: TestClient) -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    # The run-list summary surface is the strict, path-free DTO (Low #2).
    assert set(schemas["RunSummaryView"]["properties"]) == set(RunSummaryView.model_fields)
    assert "path" not in schemas["RunSummaryView"]["properties"]
    # The evidence-graph edge surface carries integrity, never paths/config (finding #30).
    edge_props = set(schemas["EvidenceEdgeView"]["properties"])
    assert edge_props == set(EvidenceEdgeView.model_fields)
    assert {"path", "sidecar_path", "config"} & edge_props == set()
    assert "BenchmarkEvidenceGraphResponse" in schemas
    assert "integrity_failed" in schemas[BenchmarkEvidenceGraphResponse.__name__]["properties"]
