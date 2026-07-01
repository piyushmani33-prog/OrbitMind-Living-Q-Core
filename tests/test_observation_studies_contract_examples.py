"""Executable contract examples for the documented observation study API flow."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fastapi.testclient import TestClient

import orbitmind.observation_planning.orchestration as orchestration_module
from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.api.observation_geometry_schemas import (
    GEOMETRY_DERIVED_ELIGIBILITY_DISCLAIMER,
)
from orbitmind.api.observation_planning_schemas import (
    PROVENANCE_ANCHORED_EXECUTION_DISCLAIMER,
)
from orbitmind.api.observation_studies_schemas import OBSERVATION_STUDY_DISCLAIMER
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_planning.models import ObservationPlanningRequest
from orbitmind.sources.registry import SourceRegistry

GEOMETRY_BASE = "/api/v1/observation-geometry"
PLANNING_BASE = "/api/v1/observation-planning"
STUDY_BASE = "/api/v1/observation-studies"
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=dt.UTC)


def _owner_client(container: AppContainer, owner_id: str) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app)


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _geometry_request(site_id: str) -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} contract example site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=START,
        end=START + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _seed_persisted_offline_geometry_run(
    container: AppContainer,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-CONTRACT-EXAMPLE",
) -> str:
    """Step 0 test setup: persist offline geometry without using a public compute endpoint."""

    with container.database.session() as session:
        execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=_geometry_request(site_id),
            idempotency_key=f"contract-example-geometry:{owner_id}:{site_id}",
        )
    return execution.run_id


def _assert_no_raw_internal_terms(*payloads: object) -> None:
    serialized = "\n".join(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).lower() for payload in payloads
    )
    for forbidden in (
        '"result_json"',
        '"request_json"',
        '"link_json"',
        "snapshot",
        '"tle_line1"',
        '"tle_line2"',
        '"samples"',
        '"intervals"',
        "select ",
        "insert ",
        "postgresql://",
        "sqlite",
        "traceback",
        ".py",
        "e:\\",
    ):
        assert forbidden not in serialized


def _assert_study_disclaimer_is_honest(disclaimer: str) -> None:
    assert disclaimer == OBSERVATION_STUDY_DISCLAIMER
    for phrase in (
        "read-only authenticated traceability",
        "pinned/offline geometry-derived eligibility",
        "does not prove live tracking",
        "operational access",
        "taskability",
        "command readiness",
        "approval",
        "signed receipt status",
        "quantum authority",
    ):
        assert phrase in disclaimer


def test_documented_observation_study_api_flow_is_executable(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry_run_id = _seed_persisted_offline_geometry_run(container)

    with _owner_client(container, "owner-a") as client:
        derived_response = client.post(
            f"{GEOMETRY_BASE}/runs/{geometry_run_id}/derive-eligibility",
            json={"requested_by": "contract-example-analyst"},
        )
        assert derived_response.status_code == 201
        derived_body = derived_response.json()
        assert derived_body["geometry_run_id"] == geometry_run_id
        assert derived_body["eligibility_set_id"]
        assert derived_body["disclaimer"] == GEOMETRY_DERIVED_ELIGIBILITY_DISCLAIMER

        planning_payload = {
            "requested_by": "contract-example-planner",
            "eligibility_set_id": derived_body["eligibility_set_id"],
        }
        planning_response = client.post(
            f"{PLANNING_BASE}/provenance-anchored-executions",
            json=planning_payload,
        )
        assert planning_response.status_code == 201
        planning_body = planning_response.json()
        assert planning_body["link_id"]
        assert planning_body["planning_request_id"]
        assert planning_body["planning_run_id"]
        assert planning_body["disclaimer"] == PROVENANCE_ANCHORED_EXECUTION_DISCLAIMER
        assert "geometry-derived eligibility" in planning_body["disclaimer"]

        def fail_planner(_: ObservationPlanningRequest) -> object:
            raise AssertionError("contract replay must reuse persisted planning records")

        monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)
        replay_response = client.post(
            f"{PLANNING_BASE}/provenance-anchored-executions",
            json=planning_payload,
        )
        assert replay_response.status_code == 200
        replay_body = replay_response.json()
        assert replay_body["planning_request_id"] == planning_body["planning_request_id"]
        assert replay_body["planning_run_id"] == planning_body["planning_run_id"]
        assert replay_body["observation_plan_id"] == planning_body["observation_plan_id"]
        assert replay_body["link_id"] == planning_body["link_id"]

        study_response = client.get(
            f"{STUDY_BASE}/geometry-planning-chain",
            params={
                "geometry_run_id": geometry_run_id,
                "provenance_link_id": planning_body["link_id"],
            },
        )
        assert study_response.status_code == 200
        study_body = study_response.json()

    assert study_body["geometry"]["run_id"] == geometry_run_id
    assert study_body["eligibility"]["eligibility_set_id"] == derived_body["eligibility_set_id"]
    assert study_body["planning"]["provenance_link_id"] == planning_body["link_id"]
    assert study_body["eligibility"]["source_type"] == "derived"
    assert study_body["eligibility"]["source_mode"] == "derived_from_geometry"
    assert study_body["eligibility"]["verification_status"] == "geometry_derived"
    assert study_body["planning"]["planning_request_source_mode"] == "declared"
    assert all(check["passed"] for check in study_body["checks"])
    _assert_study_disclaimer_is_honest(study_body["disclaimer"])
    _assert_no_raw_internal_terms(derived_body, planning_body, replay_body, study_body)


def test_documented_observation_study_api_flow_rejects_owner_id_input(
    container: AppContainer,
) -> None:
    geometry_run_id = _seed_persisted_offline_geometry_run(
        container,
        site_id="SITE-CONTRACT-OWNER-GUARD",
    )

    with _owner_client(container, "owner-a") as client:
        bad_derive = client.post(
            f"{GEOMETRY_BASE}/runs/{geometry_run_id}/derive-eligibility",
            json={"requested_by": "contract-example-analyst", "owner_id": "owner-b"},
        )
        assert bad_derive.status_code == 422

        derived = client.post(
            f"{GEOMETRY_BASE}/runs/{geometry_run_id}/derive-eligibility",
            json={"requested_by": "contract-example-analyst"},
        )
        assert derived.status_code == 201
        eligibility_set_id = derived.json()["eligibility_set_id"]

        bad_planning = client.post(
            f"{PLANNING_BASE}/provenance-anchored-executions",
            json={
                "requested_by": "contract-example-planner",
                "eligibility_set_id": eligibility_set_id,
                "owner_id": "owner-b",
            },
        )
        assert bad_planning.status_code == 422

        planning = client.post(
            f"{PLANNING_BASE}/provenance-anchored-executions",
            json={
                "requested_by": "contract-example-planner",
                "eligibility_set_id": eligibility_set_id,
            },
        )
        assert planning.status_code == 201

        bad_study = client.get(
            f"{STUDY_BASE}/geometry-planning-chain",
            params={
                "geometry_run_id": geometry_run_id,
                "provenance_link_id": planning.json()["link_id"],
                "owner_id": "owner-b",
            },
        )
        assert bad_study.status_code == 422
