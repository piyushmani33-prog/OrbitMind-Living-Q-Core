"""HTTP API tests for provenance-anchored observation-planning execution."""

from __future__ import annotations

import builtins
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

import orbitmind.api.routers.observation_planning as observation_planning_router
import orbitmind.observation_planning.orchestration as orchestration_module
from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.core.checksums import sha256_text
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
    ObservationEligibilityWindowRow,
    ObservationEligibilityWindowSetRow,
    ObservationInputProvenanceRow,
    ObservationPlanningProvenanceLinkRow,
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
    ObservationPlanRow,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
    StoredEligibilityWindowSet,
)

BASE = "/api/v1/observation-planning"


def _owner_client(container: AppContainer, owner_id: str) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app)


def _owner_client_no_raise(container: AppContainer, owner_id: str) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app, raise_server_exceptions=False)


def _checksum(label: str) -> str:
    return sha256_text(label)


def _rights(status: InputRightsStatus = InputRightsStatus.DECLARED) -> InputRightsDeclaration:
    return InputRightsDeclaration(
        rights_status=status,
        redistribution=InputRightsPermission.UNKNOWN,
        commercial_use=InputRightsPermission.UNKNOWN,
        attribution_required=status == InputRightsStatus.VERIFIED,
        user_responsibility="caller retains responsibility for declared input rights",
        limitations=("recorded declaration only",),
    )


def _artifact(label: str) -> PinnedInputArtifact:
    return PinnedInputArtifact(
        artifact_id=f"artifact-{label}",
        content_checksum=_checksum(label),
        media_type="application/json",
        record_count=2,
    )


def _provenance(
    source_type: PinnedInputSourceType = PinnedInputSourceType.FIXTURE,
    *,
    label: str = "api-fixture",
    parent: PinnedInputProvenance | None = None,
) -> PinnedInputProvenance:
    if source_type == PinnedInputSourceType.USER_DECLARED:
        return PinnedInputProvenance(
            source=InputSourceIdentity(
                source_id=f"{label}-source",
                source_type=source_type,
                source_mode=PinnedInputSourceMode.USER_DECLARED,
            ),
            artifact=_artifact(label),
            declared_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
            rights=_rights(InputRightsStatus.DECLARED),
            verification_status=ScientificInputVerificationStatus.USER_DECLARED,
        )
    if source_type == PinnedInputSourceType.DERIVED:
        assert parent is not None
        return PinnedInputProvenance(
            source=InputSourceIdentity(
                source_id=f"{label}-source",
                source_type=source_type,
                source_mode=PinnedInputSourceMode.DERIVED_FROM_DECLARED_INPUT,
                dataset_name="api-derived-eligibility",
                dataset_version="v1",
            ),
            artifact=_artifact(label),
            retrieved_at=dt.datetime(2026, 6, 21, 9, 5, tzinfo=dt.UTC),
            rights=_rights(InputRightsStatus.DECLARED),
            verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
            parent_provenance_checksums=(parent.checksum,),
        )
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=source_type,
            source_mode=PinnedInputSourceMode.FIXTURE_BACKED,
            publisher="OrbitMind",
            dataset_name="api-fixture-eligibility",
            dataset_version="v1",
        ),
        artifact=_artifact(label),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.VERIFIED),
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _window(
    window_id: str,
    provenance: PinnedInputProvenance,
    *,
    start_minute: int = 0,
    end_minute: int = 30,
    asset_id: str = "SAT-A",
    target_id: str = "T1",
) -> EligibilityWindow:
    mode = (
        EligibilityDeclarationMode.FIXTURE_BACKED
        if provenance.source.source_type == PinnedInputSourceType.FIXTURE
        else EligibilityDeclarationMode.USER_DECLARED
        if provenance.source.source_type == PinnedInputSourceType.USER_DECLARED
        else EligibilityDeclarationMode.DERIVED_FROM_DECLARED_INPUT
    )
    status = (
        ScientificInputVerificationStatus.FIXTURE_VERIFIED
        if mode == EligibilityDeclarationMode.FIXTURE_BACKED
        else ScientificInputVerificationStatus.USER_DECLARED
        if mode == EligibilityDeclarationMode.USER_DECLARED
        else ScientificInputVerificationStatus.DERIVED_FROM_DECLARED
    )
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return EligibilityWindow(
        id=window_id,
        asset_id=asset_id,
        target_id=target_id,
        start=base + dt.timedelta(minutes=start_minute),
        end=base + dt.timedelta(minutes=end_minute),
        source_provenance_checksum=provenance.checksum,
        declaration_mode=mode,
        eligibility_reason="declared-candidate",
        verification_status=status,
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
        if provenance.source.source_type == PinnedInputSourceType.DERIVED:
            for checksum in provenance.parent_provenance_checksums:
                if repo.get_provenance_by_checksum(checksum, owner_id=owner_id) is None:
                    raise AssertionError("derived parent must be persisted first")
        repo.create_provenance(provenance, owner_id=owner_id)
        stored = repo.create_eligibility_window_set(
            EligibilityWindowSet(
                source_provenance=provenance,
                windows=windows if windows is not None else (_window("W1", provenance),),
            ),
            owner_id=owner_id,
        )
        session.commit()
        return stored


def _execute_payload(
    stored: StoredEligibilityWindowSet,
    *,
    by_checksum: bool = False,
    requested_by: str = "analyst-a",
    selected_window_ids: tuple[str, ...] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "requested_by": requested_by,
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
        limitations="deterministic timeout for anchored API test",
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
        limitations=("deterministic timeout for anchored API test",),
        authoritative_result=solver_result,
    )


def _count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _assert_no_internal_leak(text: str) -> None:
    for forbidden in (
        "SELECT",
        "IntegrityError",
        "uq_",
        "postgresql://",
        "Traceback",
        "E:\\",
        ".py",
        "link_json",
        "link_identity",
    ):
        assert forbidden not in text


def test_successful_fixture_declared_and_derived_anchored_execution(
    container: AppContainer,
) -> None:
    fixture_set = _persist_set(container, _provenance(label="fixture-api"))
    declared_set = _persist_set(
        container,
        _provenance(PinnedInputSourceType.USER_DECLARED, label="declared-api"),
    )
    parent = _provenance(PinnedInputSourceType.USER_DECLARED, label="api-parent")
    _persist_set(container, parent)
    derived_set = _persist_set(
        container,
        _provenance(PinnedInputSourceType.DERIVED, label="api-derived", parent=parent),
    )

    with _owner_client(container, "owner-a") as client:
        fixture = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(fixture_set),
        )
        declared = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(declared_set),
        )
        derived = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(derived_set),
        )

    assert fixture.status_code == 201
    assert fixture.json()["source_type"] == "fixture"
    assert fixture.json()["verification_status"] == "fixture_verified"
    assert declared.json()["source_type"] == "user_declared"
    assert derived.json()["source_type"] == "derived"
    for response in (fixture, declared, derived):
        body = response.json()
        assert body["planning_status"] == "verified-feasible"
        assert body["observation_plan_id"] is not None
        assert "link_json" not in body
        assert "orbital visibility" in body["disclaimer"]
        assert "signed receipt" in body["disclaimer"]
        assert "quantum" in body["disclaimer"]


def test_execution_by_checksum_subset_canonical_order_and_replay(
    container: AppContainer,
) -> None:
    provenance = _provenance(label="subset-api")
    stored = _persist_set(
        container,
        provenance,
        windows=(
            _window("W-B", provenance, asset_id="SAT-B", start_minute=0, end_minute=30),
            _window("W-A", provenance, asset_id="SAT-A", start_minute=40, end_minute=70),
            _window("W-C", provenance, asset_id="SAT-C", start_minute=80, end_minute=110),
        ),
    )
    with _owner_client(container, "owner-a") as client:
        first = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(
                stored,
                by_checksum=True,
                selected_window_ids=("W-C", "W-A"),
            ),
        )
        replay = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(
                stored,
                by_checksum=True,
                selected_window_ids=("W-A", "W-C"),
            ),
        )
        changed = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored, by_checksum=True, selected_window_ids=("W-A", "W-B")),
        )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert first.json()["selected_window_ids"] == ["W-A", "W-C"]
    assert replay.json()["link_id"] == first.json()["link_id"]
    assert replay.json()["request_created"] is False
    assert replay.json()["run_created"] is False
    assert changed.status_code == 201
    assert changed.json()["link_id"] != first.json()["link_id"]
    assert changed.json()["preparation_checksum"] != first.json()["preparation_checksum"]


def test_body_validation_rejects_lookup_selection_and_unknown_fields(
    container: AppContainer,
) -> None:
    stored = _persist_set(container, _provenance(label="validation-api"))
    with _owner_client(container, "owner-a") as client:
        neither = client.post(
            f"{BASE}/provenance-anchored-executions",
            json={"requested_by": "analyst"},
        )
        both = client.post(
            f"{BASE}/provenance-anchored-executions",
            json={
                "requested_by": "analyst",
                "eligibility_set_id": stored.id,
                "eligibility_set_checksum": stored.eligibility_set_checksum,
            },
        )
        padded = client.post(
            f"{BASE}/provenance-anchored-executions",
            json={"requested_by": "analyst", "eligibility_set_id": f" {stored.id}"},
        )
        duplicate = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored, selected_window_ids=("W1", "W1")),
        )
        empty_selection = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored, selected_window_ids=()),
        )
        oversized = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(
                stored,
                selected_window_ids=tuple(f"W-{index:02d}" for index in range(25)),
            ),
        )
        spoofed = client.post(
            f"{BASE}/provenance-anchored-executions",
            json={**_execute_payload(stored), "owner_id": "owner-b"},
        )

    for response in (neither, both, padded, duplicate, empty_selection, oversized, spoofed):
        assert response.status_code == 422


def test_owner_isolation_by_id_checksum_and_requested_by_not_authority(
    container: AppContainer,
) -> None:
    provenance = _provenance(label="owner-api")
    owner_a_set = _persist_set(container, provenance, owner_id="owner-a")
    owner_b_set = _persist_set(
        container,
        _provenance(label="owner-b-api"),
        owner_id="owner-b",
    )

    with _owner_client(container, "owner-b") as owner_b:
        hidden_by_id = owner_b.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(owner_a_set, requested_by="owner-a"),
        )
        hidden_by_checksum = owner_b.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(owner_a_set, by_checksum=True, requested_by="owner-a"),
        )
        independent = owner_b.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(owner_b_set, requested_by="owner-a"),
        )

    assert hidden_by_id.status_code == 404
    assert hidden_by_checksum.status_code == 404
    for response in (hidden_by_id, hidden_by_checksum):
        assert response.json()["code"] == "not_found"
        assert owner_a_set.id not in response.text
        assert owner_a_set.eligibility_set_checksum not in response.text
    assert independent.status_code == 201
    assert independent.json()["owner_id"] == "owner-b"


def test_idempotency_conflict_happens_before_solver(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provenance = _provenance(label="conflict-api")
    stored = _persist_set(
        container,
        provenance,
        windows=(
            _window("W1", provenance, asset_id="SAT-A"),
            _window("W2", provenance, asset_id="SAT-B", start_minute=40, end_minute=70),
        ),
    )
    with _owner_client(container, "owner-a") as client:
        first = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(
                stored,
                selected_window_ids=("W1",),
                idempotency_key="same-key",
            ),
        )

        def forbidden_planner(_: ObservationPlanningRequest) -> object:
            raise AssertionError("solver should not run after idempotency conflict")

        monkeypatch.setattr(orchestration_module, "plan_observation_request", forbidden_planner)
        conflict = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(
                stored,
                selected_window_ids=("W2",),
                idempotency_key="same-key",
            ),
        )

    assert first.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json() == {
        "code": "idempotency_conflict",
        "message": "idempotency key reused with a different request",
    }
    _assert_no_internal_leak(conflict.text)


def test_link_detail_retrieval_cross_owner_and_tamper_are_sanitized(
    container: AppContainer,
) -> None:
    stored = _persist_set(container, _provenance(label="link-api"))
    with _owner_client(container, "owner-a") as owner_a:
        created = owner_a.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored),
        ).json()
        detail = owner_a.get(f"{BASE}/provenance-links/{created['link_id']}")

    with _owner_client(container, "owner-b") as owner_b:
        hidden = owner_b.get(f"{BASE}/provenance-links/{created['link_id']}")

    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == created["link_id"]
    assert body["link_checksum"] == created["link_checksum"]
    assert "link_json" not in body
    assert "link_identity" not in body
    assert hidden.status_code == 404
    assert created["link_id"] not in hidden.text
    assert created["link_checksum"] not in hidden.text

    with container.database.session() as session:
        row = session.get(ObservationPlanningProvenanceLinkRow, created["link_id"])
        assert row is not None
        row.objective_value = 999.0
        session.commit()

    with _owner_client(container, "owner-a") as owner_a:
        tampered = owner_a.get(f"{BASE}/provenance-links/{created['link_id']}")

    assert tampered.status_code == 422
    assert tampered.json()["code"] == "validation_error"
    _assert_no_internal_leak(tampered.text)


def test_provenance_set_and_window_tamper_propagate_through_execution(
    container: AppContainer,
) -> None:
    provenance = _provenance(label="tamper-api")
    stored = _persist_set(container, provenance)
    with container.database.session() as session:
        provenance_row = session.scalar(select(ObservationInputProvenanceRow))
        assert provenance_row is not None
        provenance_row.artifact_checksum = _checksum("wrong-artifact")
        session.commit()

    with _owner_client(container, "owner-a") as client:
        provenance_tamper = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored),
        )
    assert provenance_tamper.status_code == 422
    assert "artifact checksum" in provenance_tamper.json()["message"]

    stored_set_tamper = _persist_set(container, _provenance(label="set-tamper-api"))
    with container.database.session() as session:
        session.execute(
            update(ObservationEligibilityWindowSetRow)
            .where(ObservationEligibilityWindowSetRow.id == stored_set_tamper.id)
            .values(window_count=0)
        )
        session.commit()

    with _owner_client(container, "owner-a") as client:
        set_tamper = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored_set_tamper),
        )
    assert set_tamper.status_code == 422
    assert "window count" in set_tamper.json()["message"]

    stored_window_tamper = _persist_set(container, _provenance(label="window-tamper-api"))
    with container.database.session() as session:
        row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id == stored_window_tamper.id
            )
        )
        assert row is not None
        row.asset_id = "SAT-TAMPERED"
        session.commit()

    with _owner_client(container, "owner-a") as client:
        window_tamper = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored_window_tamper),
        )
    assert window_tamper.status_code == 422
    assert "asset" in window_tamper.json()["message"]


def test_non_success_execution_and_link_failure_do_not_create_partial_graph(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _persist_set(container, _provenance(label="timeout-api"))
    monkeypatch.setattr(orchestration_module, "plan_observation_request", _timed_out_planner)
    with _owner_client(container, "owner-a") as client:
        timed_out = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored),
        )
        run = client.get(f"{BASE}/runs/{timed_out.json()['planning_run_id']}")

    assert timed_out.status_code == 201
    assert timed_out.json()["planning_status"] == "timed-out"
    assert timed_out.json()["observation_plan_id"] is None
    assert run.json()["plan"] is None
    monkeypatch.undo()

    def fail_link(self: object, **kwargs: object) -> object:
        raise RuntimeError("link insert failed with SELECT postgresql://secret")

    failing = _persist_set(container, _provenance(label="link-fail-api"))
    monkeypatch.setattr(
        SqlAlchemyObservationPlanningLinkRepository,
        "create_provenance_planning_link",
        fail_link,
    )
    with _owner_client_no_raise(container, "owner-a") as client:
        failed = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(failing),
        )

    assert failed.status_code == 500
    assert failed.json() == {"code": "internal_error", "message": "an internal error occurred"}
    _assert_no_internal_leak(failed.text)
    with container.database.session() as session:
        assert _count(session, ObservationPlanningRequestRow) == 1
        assert _count(session, ObservationPlanningRunRow) == 1
        assert _count(session, ObservationPlanRow) == 0
        assert _count(session, ObservationPlanningProvenanceLinkRow) == 1


def test_openapi_and_router_boundary_for_provenance_anchored_routes(
    client: TestClient,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert f"{BASE}/provenance-anchored-executions" in paths
    assert f"{BASE}/provenance-links/{{link_id}}" in paths

    router_source = Path(observation_planning_router.__file__).read_text(encoding="utf-8")
    assert "execute_provenance_anchored_planning(" in router_source
    assert "prepare_eligibility_backed_planning_request(" not in router_source
    assert "_execute_observation_planning_in_transaction(" not in router_source
    assert ".begin(" not in router_source
    assert ".commit(" not in router_source
    assert ".rollback(" not in router_source


def test_provenance_anchored_api_uses_no_geometry_provider_or_quantum_path(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = _persist_set(container, _provenance(label="no-quantum-api"))
    original_import = builtins.__import__

    def guarded_import(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if (
            name.startswith("orbitmind.quantum")
            or name.startswith("orbitmind.optimization.quantum")
            or name.startswith("orbitmind.space")
            or name.startswith("orbitmind.sources")
        ):
            raise AssertionError(f"forbidden import attempted: {name}")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with _owner_client(container, "owner-a") as client:
        response = client.post(
            f"{BASE}/provenance-anchored-executions",
            json=_execute_payload(stored),
        )

    assert response.status_code == 201
