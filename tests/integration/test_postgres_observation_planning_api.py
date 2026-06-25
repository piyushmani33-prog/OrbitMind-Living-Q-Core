"""Live PostgreSQL API tests for bounded observation planning."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.core.checksums import sha256_text
from orbitmind.core.config import Settings
from orbitmind.observation_planning import (
    ObservationPlanningRequest,
    PlanningResultStatus,
    translate_request_to_problem,
)
from orbitmind.observation_planning.provenance import (
    EligibilityDeclarationMode,
    EligibilityWindow,
    EligibilityWindowSet,
    InputRightsDeclaration,
    InputRightsPermission,
    InputRightsStatus,
    InputSourceIdentity,
    PinnedInputArtifact,
    PinnedInputProvenance,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.optimization.models import (
    ExperimentStatus,
    OptimalityStatus,
    SolverConfiguration,
    SolverKind,
)
from orbitmind.optimization.solvers.base import build_result
from orbitmind.persistence.observation_planning_link_repository import (
    SqlAlchemyObservationPlanningLinkRepository,
)
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowSetRow,
    ObservationPlanningProvenanceLinkRow,
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
    ObservationPlanRow,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
    StoredEligibilityWindowSet,
)

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

BASE = "/api/v1/observation-planning"
_TABLES = (
    "observation_planning_provenance_links",
    "observation_eligibility_windows",
    "observation_eligibility_window_sets",
    "observation_input_provenance_parents",
    "observation_input_provenance",
    "observation_plans",
    "observation_planning_runs",
    "observation_planning_requests",
)


@pytest.fixture
def pg_container(tmp_path: Path) -> AppContainer:
    """A container on the migrated PostgreSQL schema; do not call create_all()."""

    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
    )
    container = AppContainer(settings=settings)
    container.init_storage = lambda: None  # type: ignore[method-assign]
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield container
    container.database.engine.dispose()


def _client(
    container: AppContainer,
    owner_id: str = "local-owner",
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _exec(container: AppContainer, sql: str) -> list:
    with container.database.engine.connect() as conn:
        return list(conn.execute(text(sql)))


def _horizon() -> dict[str, str]:
    return {"start": "2026-06-21T09:00:00Z", "end": "2026-06-21T12:00:00Z"}


def _opportunity(oid: str = "OPP-A", *, start_min: int = 60, end_min: int = 90) -> dict:
    return {
        "id": oid,
        "satellite_id": "SAT-A",
        "target_id": "T1",
        "start": f"2026-06-21T{9 + start_min // 60:02d}:{start_min % 60:02d}:00Z",
        "end": f"2026-06-21T{9 + end_min // 60:02d}:{end_min % 60:02d}:00Z",
        "mission_value": 5.0,
        "energy_cost": 1.0,
        "storage_cost": 1.0,
    }


def _payload(
    *,
    name: str = "postgres api declared",
    idempotency_key: str | None = None,
    constraints: dict[str, object] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "horizon": _horizon(),
        "source_mode": "declared",
        "fixture_name": None,
        "opportunities": [_opportunity()],
        "satellites": [{"id": "SAT-A", "energy_capacity": 20.0, "storage_capacity": 20.0}],
        "targets": [{"id": "T1"}],
    }
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    if constraints is not None:
        payload["constraints"] = constraints
    return payload


def _infeasible_payload() -> dict[str, object]:
    payload = _payload(name="postgres api infeasible", idempotency_key="pg-api-infeasible")
    payload["opportunities"] = [
        _opportunity("OPP-A", start_min=60, end_min=90),
        _opportunity("OPP-B", start_min=70, end_min=100),
    ]
    payload["constraints"] = {"mandatory": ["OPP-A", "OPP-B"]}
    return payload


def _invalid_payload() -> dict[str, object]:
    payload = _payload(name="postgres api invalid", idempotency_key="pg-api-invalid")
    opportunity = dict(payload["opportunities"][0])  # type: ignore[index]
    opportunity["satellite_id"] = "SAT-MISSING"
    payload["opportunities"] = [opportunity]
    return payload


def _sha(label: str) -> str:
    return sha256_text(label)


def _rights() -> InputRightsDeclaration:
    return InputRightsDeclaration(
        rights_status=InputRightsStatus.DECLARED,
        redistribution=InputRightsPermission.UNKNOWN,
        commercial_use=InputRightsPermission.UNKNOWN,
        user_responsibility="caller retains responsibility for declared input rights",
        limitations=("recorded declaration only",),
    )


def _artifact(label: str) -> PinnedInputArtifact:
    return PinnedInputArtifact(
        artifact_id=f"{label}-artifact",
        content_checksum=_sha(label),
        media_type="application/json",
        record_count=1,
    )


def _provenance(label: str = "pg-api-anchored") -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=PinnedInputSourceType.FIXTURE,
            source_mode=PinnedInputSourceMode.FIXTURE_BACKED,
            publisher="OrbitMind",
            dataset_name="postgres-api-fixture-eligibility",
            dataset_version="v1",
        ),
        artifact=_artifact(label),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        rights=_rights(),
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _window(
    provenance: PinnedInputProvenance,
    *,
    window_id: str = "PG-API-W1",
    asset_id: str = "SAT-A",
    start_minute: int = 0,
    end_minute: int = 30,
) -> EligibilityWindow:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return EligibilityWindow(
        id=window_id,
        asset_id=asset_id,
        target_id="T1",
        start=base + dt.timedelta(minutes=start_minute),
        end=base + dt.timedelta(minutes=end_minute),
        source_provenance_checksum=provenance.checksum,
        declaration_mode=EligibilityDeclarationMode.FIXTURE_BACKED,
        eligibility_reason="postgres-api-fixture-candidate",
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _persist_set(
    container: AppContainer,
    provenance: PinnedInputProvenance,
    *,
    owner_id: str = "owner-a",
    windows: tuple[EligibilityWindow, ...] | None = None,
) -> StoredEligibilityWindowSet:
    with container.database.session() as session:
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        repo.create_provenance(provenance, owner_id=owner_id)
        stored = repo.create_eligibility_window_set(
            EligibilityWindowSet(
                source_provenance=provenance,
                windows=windows if windows is not None else (_window(provenance),),
            ),
            owner_id=owner_id,
        )
        session.commit()
        return stored


def _anchored_payload(
    stored: StoredEligibilityWindowSet,
    *,
    by_checksum: bool = False,
    selected_window_ids: tuple[str, ...] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "requested_by": "pg-api-analyst",
        "eligibility_set_checksum" if by_checksum else "eligibility_set_id": (
            stored.eligibility_set_checksum if by_checksum else stored.id
        ),
    }
    if selected_window_ids is not None:
        payload["selected_window_ids"] = list(selected_window_ids)
    if idempotency_key is not None:
        payload["idempotency_key"] = idempotency_key
    return payload


def _timed_out_planner(request: ObservationPlanningRequest) -> object:
    translation = translate_request_to_problem(request)
    config = SolverConfiguration(solver_kind=SolverKind.EXACT)
    solver_result = build_result(
        solver_kind=SolverKind.EXACT,
        solver_name="fake-timeout",
        solver_version="test",
        problem_checksum=translation.problem.checksum,
        config=config,
        evaluation=None,
        status=ExperimentStatus.TIMED_OUT,
        optimality=OptimalityStatus.UNKNOWN,
        known_optimum=None,
        runtime_seconds=0.0,
        evaluated_candidates=0,
        limitations="deterministic timeout for PostgreSQL anchored API test",
    )
    from orbitmind.observation_planning import (
        AuthoritativePlanningSolver,
        ObservationPlanningResult,
        PlanningOptimalityLabel,
    )

    return ObservationPlanningResult(
        request_checksum=translation.request_checksum,
        problem_checksum=translation.problem.checksum,
        source_mode=request.source_mode,
        selected_solver=AuthoritativePlanningSolver.EXACT,
        solver_execution_status=ExperimentStatus.TIMED_OUT,
        status=PlanningResultStatus.TIMED_OUT,
        optimality_label=PlanningOptimalityLabel.UNKNOWN,
        limitations=("deterministic timeout for PostgreSQL anchored API test",),
        authoritative_result=solver_result,
    )


def _row_count(container: AppContainer, table: type[object]) -> int:
    with container.database.session() as session:
        return int(session.scalar(select(func.count()).select_from(table)) or 0)


def test_postgres_api_executes_and_retrieves_plan(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        created = client.post(f"{BASE}/executions", json=_payload(idempotency_key="pg-api-ok"))
        assert created.status_code == 201
        body = created.json()

        assert client.get(f"{BASE}/requests/{body['request_id']}").status_code == 200
        run = client.get(f"{BASE}/runs/{body['run_id']}")
        plan = client.get(f"{BASE}/plans/{body['plan_id']}")

    assert run.status_code == 200
    assert run.json()["plan"]["id"] == body["plan_id"]
    assert plan.status_code == 200
    assert plan.json()["id"] == body["plan_id"]


def test_postgres_api_idempotent_replay_conflict_and_owner_isolation(
    pg_container: AppContainer,
) -> None:
    with _client(pg_container, "owner-a") as owner_a:
        first = owner_a.post(
            f"{BASE}/executions", json=_payload(idempotency_key="pg-api-key")
        ).json()
        second = owner_a.post(f"{BASE}/executions", json=_payload(idempotency_key="pg-api-key"))
        conflict = owner_a.post(
            f"{BASE}/executions",
            json=_payload(name="different", idempotency_key="pg-api-key"),
        )

    with _client(pg_container, "owner-b") as owner_b:
        hidden_request = owner_b.get(f"{BASE}/requests/{first['request_id']}")
        hidden_run = owner_b.get(f"{BASE}/runs/{first['run_id']}")
        hidden_plan = owner_b.get(f"{BASE}/plans/{first['plan_id']}")
        hidden_request_runs = owner_b.get(f"{BASE}/requests/{first['request_id']}/runs")
        independent = owner_b.post(
            f"{BASE}/executions",
            json=_payload(name="owner b", idempotency_key="pg-api-key"),
        )

    assert second.status_code == 200
    assert second.json()["run_id"] == first["run_id"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    for response in (hidden_request, hidden_run, hidden_plan, hidden_request_runs):
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
        for field in ("request_id", "run_id", "plan_id", "request_checksum", "problem_checksum"):
            value = first.get(field)
            if isinstance(value, str):
                assert value not in response.text
        assert "verified-feasible" not in response.text
        assert "objective" not in response.text
    assert independent.status_code == 201
    assert independent.json()["request_id"] != first["request_id"]


def test_postgres_api_lists_filter_and_paginate(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        first = client.post(
            f"{BASE}/executions", json=_payload(name="first", idempotency_key="pg-api-first")
        ).json()
        second = client.post(
            f"{BASE}/executions", json=_payload(name="second", idempotency_key="pg-api-second")
        ).json()
        page = client.get(f"{BASE}/requests?limit=1&offset=0")
        next_page = client.get(f"{BASE}/requests?limit=1&offset=1")
        runs = client.get(
            f"{BASE}/requests/{first['request_id']}/runs"
            "?status=verified-feasible&source_mode=declared&authoritative_solver=exact"
        )
        plans = client.get(
            f"{BASE}/plans?created-from=2026-01-01T00:00:00Z&created-to=2999-01-01T00:00:00Z"
        )

    assert page.status_code == 200
    assert page.json()["has_next"] is True
    assert page.json()["items"][0]["id"] != next_page.json()["items"][0]["id"]
    assert runs.status_code == 200
    assert runs.json()["items"][0]["request_id"] == first["request_id"]
    assert plans.status_code == 200
    assert {item["id"] for item in plans.json()["items"]} == {first["plan_id"], second["plan_id"]}


def test_postgres_api_non_success_run_without_plan(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        created = client.post(f"{BASE}/executions", json=_infeasible_payload())
        run = client.get(f"{BASE}/runs/{created.json()['run_id']}")

    assert created.status_code == 201
    assert created.json()["final_status"] == "infeasible"
    assert created.json()["plan_id"] is None
    assert run.status_code == 200
    assert run.json()["plan"] is None


def test_postgres_api_tamper_detection_maps_to_safe_error(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        created = client.post(
            f"{BASE}/executions", json=_payload(idempotency_key="pg-api-tamper")
        ).json()

    with pg_container.database.session() as session:
        row = session.get(ObservationPlanningRequestRow, created["request_id"])
        assert row is not None
        tampered = dict(row.request_json)
        tampered["name"] = "tampered"
        session.execute(
            update(ObservationPlanningRequestRow)
            .where(ObservationPlanningRequestRow.id == created["request_id"])
            .values(request_json=tampered)
        )
        session.commit()

    with _client(pg_container) as client:
        response = client.get(f"{BASE}/requests/{created['request_id']}")

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "checksum" in response.json()["message"]


def test_postgres_api_invalid_execution_rolls_back(pg_container: AppContainer) -> None:
    with _client(pg_container) as client:
        response = client.post(f"{BASE}/executions", json=_invalid_payload())

    assert response.status_code == 422
    assert _exec(pg_container, "SELECT count(*) FROM observation_planning_requests")[0][0] == 0
    assert _exec(pg_container, "SELECT count(*) FROM observation_planning_runs")[0][0] == 0
    assert _exec(pg_container, "SELECT count(*) FROM observation_plans")[0][0] == 0


def test_postgres_api_provenance_anchored_execution_replay_conflict_and_link_detail(
    pg_container: AppContainer,
) -> None:
    provenance = _provenance("pg-api-anchor")
    stored = _persist_set(
        pg_container,
        provenance,
        windows=(
            _window(provenance, window_id="PG-API-A", asset_id="SAT-A"),
            _window(
                provenance,
                window_id="PG-API-B",
                asset_id="SAT-B",
                start_minute=40,
                end_minute=70,
            ),
        ),
    )

    with _client(pg_container, "owner-a") as owner_a:
        first = owner_a.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(stored, selected_window_ids=("PG-API-B", "PG-API-A")),
        )
        replay = owner_a.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(stored, selected_window_ids=("PG-API-A", "PG-API-B")),
        )
        keyed = owner_a.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(
                stored,
                selected_window_ids=("PG-API-A",),
                idempotency_key="pg-api-anchor-key",
            ),
        )
        conflict = owner_a.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(
                stored,
                selected_window_ids=("PG-API-B",),
                idempotency_key="pg-api-anchor-key",
            ),
        )
        changed = owner_a.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(stored, selected_window_ids=("PG-API-B",)),
        )
        link = owner_a.get(f"{BASE}/provenance-links/{first.json()['link_id']}")

    with _client(pg_container, "owner-b") as owner_b:
        hidden_link = owner_b.get(f"{BASE}/provenance-links/{first.json()['link_id']}")
        hidden_set = owner_b.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(stored, by_checksum=True),
        )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.json()["selected_window_ids"] == ["PG-API-A", "PG-API-B"]
    assert replay.json()["link_id"] == first.json()["link_id"]
    assert replay.json()["planning_run_id"] == first.json()["planning_run_id"]
    assert changed.status_code == 201
    assert changed.json()["link_id"] != first.json()["link_id"]
    assert keyed.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert link.status_code == 200
    assert link.json()["id"] == first.json()["link_id"]
    assert "link_json" not in link.text
    assert hidden_link.status_code == 404
    assert first.json()["link_checksum"] not in hidden_link.text
    assert hidden_set.status_code == 404
    assert stored.eligibility_set_checksum not in hidden_set.text


def test_postgres_api_provenance_anchored_non_success_without_plan(
    pg_container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _persist_set(pg_container, _provenance("pg-api-timeout"))
    monkeypatch.setattr(
        "orbitmind.observation_planning.orchestration.plan_observation_request",
        _timed_out_planner,
    )

    with _client(pg_container, "owner-a") as client:
        response = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(stored),
        )
        run = client.get(f"{BASE}/runs/{response.json()['planning_run_id']}")

    assert response.status_code == 201
    assert response.json()["planning_status"] == "timed-out"
    assert response.json()["observation_plan_id"] is None
    assert run.status_code == 200
    assert run.json()["plan"] is None


def test_postgres_api_provenance_anchored_tamper_and_link_failure_rollback(
    pg_container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _persist_set(pg_container, _provenance("pg-api-link-tamper"))
    with _client(pg_container, "owner-a") as client:
        created = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(stored),
        ).json()

    with pg_container.database.session() as session:
        session.execute(
            update(ObservationPlanningProvenanceLinkRow)
            .where(ObservationPlanningProvenanceLinkRow.id == created["link_id"])
            .values(objective_value=999.0)
        )
        session.commit()

    with _client(pg_container, "owner-a") as client:
        tampered_link = client.get(f"{BASE}/provenance-links/{created['link_id']}")

    assert tampered_link.status_code == 422
    assert tampered_link.json()["code"] == "validation_error"
    for forbidden in ("SELECT", "uq_", "postgresql://", "Traceback", "link_json"):
        assert forbidden not in tampered_link.text

    set_tamper = _persist_set(pg_container, _provenance("pg-api-set-tamper"))
    with pg_container.database.session() as session:
        session.execute(
            update(ObservationEligibilityWindowSetRow)
            .where(ObservationEligibilityWindowSetRow.id == set_tamper.id)
            .values(window_count=0)
        )
        session.commit()
    with _client(pg_container, "owner-a") as client:
        tampered_set = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(set_tamper),
        )
    assert tampered_set.status_code == 422
    assert "window count" in tampered_set.json()["message"]

    before = (
        _row_count(pg_container, ObservationPlanningRequestRow),
        _row_count(pg_container, ObservationPlanningRunRow),
        _row_count(pg_container, ObservationPlanRow),
        _row_count(pg_container, ObservationPlanningProvenanceLinkRow),
    )
    failing = _persist_set(pg_container, _provenance("pg-api-link-failure"))

    def fail_link(self: object, **kwargs: object) -> object:
        raise RuntimeError("link insert failed with SELECT postgresql://secret")

    monkeypatch.setattr(
        SqlAlchemyObservationPlanningLinkRepository,
        "create_provenance_planning_link",
        fail_link,
    )
    with _client(pg_container, "owner-a", raise_server_exceptions=False) as client:
        failed = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_anchored_payload(failing),
        )
    after = (
        _row_count(pg_container, ObservationPlanningRequestRow),
        _row_count(pg_container, ObservationPlanningRunRow),
        _row_count(pg_container, ObservationPlanRow),
        _row_count(pg_container, ObservationPlanningProvenanceLinkRow),
    )

    assert failed.status_code == 500
    assert failed.json() == {"code": "internal_error", "message": "an internal error occurred"}
    assert "SELECT" not in failed.text
    assert "postgresql://" not in failed.text
    assert after == before
