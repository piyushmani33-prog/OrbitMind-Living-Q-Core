"""Read-only API tests for persisted observation geometry."""

from __future__ import annotations

import ast
import copy
import datetime as dt
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.deps import get_current_owner_id
from orbitmind.api.observation_geometry_schemas import (
    GEOMETRY_DERIVED_ELIGIBILITY_DISCLAIMER,
    OBSERVATION_GEOMETRY_DISCLAIMER,
)
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_geometry.queries import get_geometry_run_for_request
from orbitmind.persistence.observation_geometry_models import (
    ObservationGeometryRequestRow,
    ObservationGeometryRunRow,
)
from orbitmind.sources.registry import SourceRegistry

BASE = "/api/v1/observation-geometry"
UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC)


def _owner_client(
    container: AppContainer,
    owner_id: str,
    *,
    raise_server_exceptions: bool = True,
) -> TestClient:
    app = create_app(container)
    app.dependency_overrides[get_current_owner_id] = lambda: owner_id
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _request(
    *,
    site_id: str = "SITE-A",
    start: dt.datetime = START,
    end: dt.datetime = START + dt.timedelta(minutes=25),
) -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} ground site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=start,
        end=end,
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _persist(
    container: AppContainer,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-A",
    start: dt.datetime = START,
) -> tuple[str, str, str, str]:
    request = _request(site_id=site_id, start=start, end=start + dt.timedelta(minutes=25))
    with container.database.session() as session:
        execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=request,
            idempotency_key=f"{owner_id}-{site_id}-{start.isoformat()}",
        )
    return (
        execution.request_id,
        execution.run_id,
        execution.request_checksum,
        execution.geometry_checksum,
    )


def _assert_no_raw_geometry_payload(payload: dict[str, Any]) -> None:
    assert "request_json" not in payload
    assert "result_json" not in payload
    assert "samples" not in payload
    assert "intervals" not in payload
    assert "tle_line1" not in payload
    assert "tle_line2" not in payload


def _assert_no_raw_geometry_text(text: str) -> None:
    lowered = text.lower()
    for forbidden in (
        '"request_json"',
        '"result_json"',
        '"samples"',
        '"intervals"',
        '"tle_line1"',
        '"tle_line2"',
        "'request_json'",
        "'result_json'",
        "'samples'",
        "'intervals'",
        "'tle_line1'",
        "'tle_line2'",
        "select ",
        "insert ",
        "sqlite",
        "postgres",
        "constraint",
        "traceback",
        "e:\\",
    ):
        assert forbidden not in lowered


def _assert_safe_error(response: Any) -> None:
    body = response.json()
    assert set(body) == {"code", "message"}
    _assert_no_raw_geometry_text(response.text)


def _assert_derived_response_is_safe(
    payload: dict[str, Any],
    *,
    run_id: str,
    expected_status: tuple[bool, bool],
) -> None:
    expected_keys = {
        "owner_id",
        "geometry_run_id",
        "geometry_request_id",
        "geometry_checksum",
        "geometry_request_checksum",
        "element_checksum",
        "source_identity_checksum",
        "provenance_record_id",
        "provenance_checksum",
        "eligibility_set_id",
        "eligibility_set_checksum",
        "derivation_checksum",
        "derivation_rule_version",
        "derivation_label",
        "minimum_peak_elevation_deg",
        "window_count",
        "provenance_created",
        "provenance_reused",
        "eligibility_set_created",
        "eligibility_set_reused",
        "derived_source_type",
        "derived_source_mode",
        "derived_verification_status",
        "limitations",
        "disclaimer",
    }
    assert set(payload) == expected_keys
    assert payload["owner_id"] == "owner-a"
    assert payload["geometry_run_id"] == run_id
    assert payload["provenance_created"] is expected_status[0]
    assert payload["eligibility_set_created"] is expected_status[1]
    assert payload["provenance_reused"] is (not expected_status[0])
    assert payload["eligibility_set_reused"] is (not expected_status[1])
    assert payload["derived_source_type"] == "derived"
    assert payload["derived_source_mode"] == "derived_from_geometry"
    assert payload["derived_verification_status"] == "geometry_derived"
    assert payload["window_count"] >= 0
    assert payload["limitations"]
    assert payload["disclaimer"] == GEOMETRY_DERIVED_ELIGIBILITY_DISCLAIMER
    _assert_no_raw_geometry_text(str(payload))


def test_geometry_api_lists_reads_and_authenticates_requests_and_runs(
    container: AppContainer,
) -> None:
    first_request_id, first_run_id, first_request_checksum, _first_geometry = _persist(
        container,
        owner_id="owner-a",
        site_id="SITE-A",
        start=START,
    )
    second_request_id, second_run_id, _second_request_checksum, _second_geometry = _persist(
        container,
        owner_id="owner-a",
        site_id="SITE-B",
        start=START + dt.timedelta(minutes=30),
    )
    _persist(container, owner_id="owner-b", site_id="SITE-C")

    with _owner_client(container, "owner-a") as client:
        requests_response = client.get(f"{BASE}/requests")
        assert requests_response.status_code == 200
        requests_body = requests_response.json()
        assert requests_body["total"] == 2
        assert requests_body["limit"] == 25
        assert requests_body["disclaimer"] == OBSERVATION_GEOMETRY_DISCLAIMER
        request_ids = {item["id"] for item in requests_body["items"]}
        assert request_ids == {first_request_id, second_request_id}
        for item in requests_body["items"]:
            _assert_no_raw_geometry_payload(item)
            assert item["owner_id"] == "owner-a"
            assert item["site"]["site_id"] in {"SITE-A", "SITE-B"}

        request_response = client.get(f"{BASE}/requests/{first_request_id}")
        assert request_response.status_code == 200
        request_body = request_response.json()
        assert request_body["id"] == first_request_id
        assert request_body["request_checksum"] == first_request_checksum
        _assert_no_raw_geometry_payload(request_body)

        runs_response = client.get(f"{BASE}/runs")
        assert runs_response.status_code == 200
        runs_body = runs_response.json()
        assert runs_body["total"] == 2
        run_ids = {item["id"] for item in runs_body["items"]}
        assert run_ids == {first_run_id, second_run_id}
        for item in runs_body["items"]:
            _assert_no_raw_geometry_payload(item)
            assert item["sample_count"] > 0
            assert item["computation_version"] == "orbitmind-look-angle-geometry-1.0"

        filtered_runs = client.get(f"{BASE}/runs", params={"request_id": first_request_id})
        assert filtered_runs.status_code == 200
        assert filtered_runs.json()["total"] == 1
        assert filtered_runs.json()["items"][0]["id"] == first_run_id

        run_response = client.get(f"{BASE}/runs/{first_run_id}")
        assert run_response.status_code == 200
        run_body = run_response.json()
        assert run_body["id"] == first_run_id
        assert run_body["request_id"] == first_request_id
        assert run_body["sample_count"] > 0
        assert run_body["limitations"]
        _assert_no_raw_geometry_payload(run_body)

        samples_response = client.get(f"{BASE}/runs/{first_run_id}/samples")
        assert samples_response.status_code == 200
        samples_body = samples_response.json()
        assert samples_body["run_id"] == first_run_id
        assert samples_body["request_id"] == first_request_id
        assert samples_body["geometry_checksum"] == run_body["geometry_checksum"]
        assert samples_body["total"] == run_body["sample_count"]
        assert samples_body["limit"] == 25
        assert samples_body["disclaimer"] == OBSERVATION_GEOMETRY_DISCLAIMER
        first_sample = samples_body["items"][0]
        assert first_sample["sequence_index"] == 0
        assert first_sample["status"] == "ok"
        assert first_sample["azimuth_deg"] is not None
        assert first_sample["elevation_deg"] is not None
        assert first_sample["slant_range_km"] is not None
        assert first_sample["safe_error_code"] is None
        _assert_no_raw_geometry_payload(samples_body)
        _assert_no_raw_geometry_payload(first_sample)

        paged_samples = client.get(
            f"{BASE}/runs/{first_run_id}/samples",
            params={"limit": "2", "offset": "1"},
        )
        assert paged_samples.status_code == 200
        assert paged_samples.json()["has_next"] is True
        assert [item["sequence_index"] for item in paged_samples.json()["items"]] == [1, 2]

        intervals_response = client.get(f"{BASE}/runs/{first_run_id}/intervals")
        assert intervals_response.status_code == 200
        intervals_body = intervals_response.json()
        assert intervals_body["run_id"] == first_run_id
        assert intervals_body["request_id"] == first_request_id
        assert intervals_body["geometry_checksum"] == run_body["geometry_checksum"]
        assert intervals_body["total"] == run_body["interval_count"]
        assert intervals_body["disclaimer"] == OBSERVATION_GEOMETRY_DISCLAIMER
        first_interval = intervals_body["items"][0]
        assert first_interval["sequence_index"] == 0
        assert first_interval["rise_time"] <= first_interval["peak_time"]
        assert first_interval["peak_time"] <= first_interval["set_time"]
        assert first_interval["peak_elevation_deg"] is not None
        assert first_interval["rise_azimuth_deg"] is not None
        assert first_interval["set_azimuth_deg"] is not None
        assert isinstance(first_interval["rise_boundary_clipped"], bool)
        assert isinstance(first_interval["set_boundary_clipped"], bool)
        assert first_interval["refinement_status"] in {
            "refined",
            "sampled",
            "clipped",
            "refinement_failed",
        }
        _assert_no_raw_geometry_payload(intervals_body)
        _assert_no_raw_geometry_payload(first_interval)

    with container.database.session() as session:
        details = get_geometry_run_for_request(
            session,
            owner_id="owner-a",
            request_id=first_request_id,
        )
    assert details.summary.id == first_run_id


def test_geometry_api_derives_eligibility_replay_and_changed_identity(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _request_id, run_id, _request_checksum, _geometry_checksum = _persist(container)

    def fail_if_computed(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("derive endpoint must not compute geometry")

    monkeypatch.setattr(
        "orbitmind.observation_geometry.persistence_service.compute_observation_geometry",
        fail_if_computed,
    )

    with _owner_client(container, "owner-a") as client:
        first = client.post(
            f"{BASE}/runs/{run_id}/derive-eligibility",
            json={"requested_by": "analyst-a"},
        )
        assert first.status_code == 201
        first_body = first.json()
        _assert_derived_response_is_safe(first_body, run_id=run_id, expected_status=(True, True))
        assert first_body["derivation_label"] == "geometry-derived-visibility"
        assert first_body["minimum_peak_elevation_deg"] is None

        replay = client.post(
            f"{BASE}/runs/{run_id}/derive-eligibility",
            json={"requested_by": "different-attribution"},
        )
        assert replay.status_code == 200
        replay_body = replay.json()
        _assert_derived_response_is_safe(
            replay_body,
            run_id=run_id,
            expected_status=(False, False),
        )
        assert replay_body["provenance_record_id"] == first_body["provenance_record_id"]
        assert replay_body["eligibility_set_id"] == first_body["eligibility_set_id"]
        assert replay_body["derivation_checksum"] == first_body["derivation_checksum"]

        changed_label = client.post(
            f"{BASE}/runs/{run_id}/derive-eligibility",
            json={"derivation_label": "geometry-derived-review"},
        )
        assert changed_label.status_code == 201
        changed_label_body = changed_label.json()
        assert changed_label_body["eligibility_set_id"] != first_body["eligibility_set_id"]
        assert (
            changed_label_body["eligibility_set_checksum"] != first_body["eligibility_set_checksum"]
        )

        changed_filter = client.post(
            f"{BASE}/runs/{run_id}/derive-eligibility",
            json={"minimum_peak_elevation_deg": 0.0},
        )
        assert changed_filter.status_code == 201
        changed_filter_body = changed_filter.json()
        assert changed_filter_body["minimum_peak_elevation_deg"] == 0.0
        assert changed_filter_body["eligibility_set_id"] != first_body["eligibility_set_id"]


def test_geometry_api_derive_eligibility_uses_owner_as_default_attribution(
    container: AppContainer,
) -> None:
    _request_id, run_id, _request_checksum, _geometry_checksum = _persist(
        container,
        site_id="SITE-ATTR",
    )

    with _owner_client(container, "owner-a") as client:
        response = client.post(f"{BASE}/runs/{run_id}/derive-eligibility", json={})
        assert response.status_code == 201
        body = response.json()
        assert body["owner_id"] == "owner-a"
        assert body["derived_source_mode"] == "derived_from_geometry"

        spoofed_attribution = client.post(
            f"{BASE}/runs/{run_id}/derive-eligibility",
            json={"requested_by": "owner-b", "derivation_label": "spoofed-attribution"},
        )
        assert spoofed_attribution.status_code == 201
        assert spoofed_attribution.json()["owner_id"] == "owner-a"


def test_geometry_api_derive_eligibility_rejects_invalid_body(
    container: AppContainer,
) -> None:
    _request_id, run_id, _request_checksum, _geometry_checksum = _persist(container)

    invalid_payloads: tuple[dict[str, object], ...] = (
        {"owner_id": "owner-a"},
        {"idempotency_key": "not-supported"},
        {"result_json": {}},
        {"request_json": {}},
        {"intervals": []},
        {"samples": []},
        {"tle_line1": "not accepted"},
        {"tle_line2": "not accepted"},
        {"derivation_label": ""},
        {"derivation_label": " padded"},
        {"derivation_label": "a" * 121},
        {"minimum_peak_elevation_deg": -1.0},
        {"minimum_peak_elevation_deg": 90.0},
        {"minimum_peak_elevation_deg": True},
    )

    with _owner_client(container, "owner-a") as client:
        for payload in invalid_payloads:
            response = client.post(f"{BASE}/runs/{run_id}/derive-eligibility", json=payload)
            assert response.status_code == 422, payload


def test_geometry_api_pagination_filters_and_openapi(container: AppContainer) -> None:
    first_request_id, _first_run_id, _checksum, _geometry = _persist(
        container,
        owner_id="owner-a",
        site_id="SITE-A",
        start=START,
    )
    second_request_id, _second_run_id, _checksum2, _geometry2 = _persist(
        container,
        owner_id="owner-a",
        site_id="SITE-B",
        start=START + dt.timedelta(minutes=30),
    )

    with _owner_client(container, "owner-a") as client:
        first_page = client.get(f"{BASE}/requests", params={"limit": "1", "offset": "0"})
        second_page = client.get(f"{BASE}/requests", params={"limit": "1", "offset": "1"})
        assert first_page.status_code == 200
        assert second_page.status_code == 200
        assert first_page.json()["has_next"] is True
        assert first_page.json()["items"][0]["id"] != second_page.json()["items"][0]["id"]

        site_filtered = client.get(f"{BASE}/requests", params={"site_id": "SITE-A"})
        assert site_filtered.status_code == 200
        assert site_filtered.json()["total"] == 1
        assert site_filtered.json()["items"][0]["id"] == first_request_id

        range_filtered = client.get(
            f"{BASE}/requests",
            params={
                "created-from": "2000-01-01T00:00:00Z",
                "created-to": "2999-01-01T00:00:00Z",
            },
        )
        assert range_filtered.status_code == 200
        assert {item["id"] for item in range_filtered.json()["items"]} == {
            first_request_id,
            second_request_id,
        }

        for params in (
            {"limit": "true"},
            {"limit": "1.5"},
            {"limit": "-1"},
            {"limit": "01"},
            {"limit": "101"},
            {"offset": "-1"},
            {"site_id": " SITE-A"},
            {"created-from": "2026-01-01T00:00:00"},
            {
                "created-from": "2999-01-01T00:00:00Z",
                "created-to": "2000-01-01T00:00:00Z",
            },
        ):
            assert client.get(f"{BASE}/requests", params=params).status_code == 422

        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        paths = openapi.json()["paths"]
        assert f"{BASE}/requests" in paths
        assert f"{BASE}/requests/{{request_id}}" in paths
        assert f"{BASE}/runs" in paths
        assert f"{BASE}/runs/{{run_id}}" in paths
        assert f"{BASE}/runs/{{run_id}}/derive-eligibility" in paths
        assert f"{BASE}/runs/{{run_id}}/samples" in paths
        assert f"{BASE}/runs/{{run_id}}/intervals" in paths
        mutation_routes = sorted(
            (path, method)
            for path, methods in paths.items()
            if path.startswith(BASE)
            for method in methods
            if method in {"post", "put", "patch", "delete"}
        )
        assert mutation_routes == [(f"{BASE}/runs/{{run_id}}/derive-eligibility", "post")]
        for path, methods in paths.items():
            if path.startswith(BASE):
                if path == f"{BASE}/runs/{{run_id}}/derive-eligibility":
                    assert {"put", "patch", "delete"}.isdisjoint(methods)
                else:
                    assert not ({"post", "put", "patch", "delete"} & set(methods))


def test_geometry_api_sample_interval_pagination_rejections(
    container: AppContainer,
) -> None:
    _request_id, run_id, _request_checksum, _geometry_checksum = _persist(container)

    with _owner_client(container, "owner-a") as client:
        empty_page = client.get(
            f"{BASE}/runs/{run_id}/samples",
            params={"limit": "25", "offset": "999"},
        )
        assert empty_page.status_code == 200
        assert empty_page.json()["items"] == []
        assert empty_page.json()["has_next"] is False

        for endpoint in ("samples", "intervals"):
            for params in (
                {"limit": "true"},
                {"limit": "1.5"},
                {"limit": "-1"},
                {"limit": "01"},
                {"limit": "101"},
                {"offset": "-1"},
                {"offset": ""},
            ):
                response = client.get(f"{BASE}/runs/{run_id}/{endpoint}", params=params)
                assert response.status_code == 422


def test_geometry_api_failed_sample_shape(
    container: AppContainer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_all(*_args: object, **_kwargs: object) -> tuple[int, None]:
        return (6, None)

    monkeypatch.setattr("orbitmind.observation_geometry.service._sgp4_position_km", fail_all)
    request = _request(end=START + dt.timedelta(minutes=5))
    with container.database.session() as session:
        execution = execute_and_persist_geometry(
            session=session,
            owner_id="owner-a",
            request=request,
        )

    with _owner_client(container, "owner-a") as client:
        response = client.get(f"{BASE}/runs/{execution.run_id}/samples")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    first_sample = body["items"][0]
    assert first_sample["sequence_index"] == 0
    assert first_sample["status"] == "error"
    assert first_sample["azimuth_deg"] is None
    assert first_sample["elevation_deg"] is None
    assert first_sample["slant_range_km"] is None
    assert first_sample["safe_error_code"] == "sgp4_status_6"


def test_geometry_api_owner_isolation_and_no_owner_override(container: AppContainer) -> None:
    request_id, run_id, request_checksum, geometry_checksum = _persist(
        container,
        owner_id="owner-a",
        site_id="SITE-A",
    )

    with _owner_client(container, "owner-b") as client:
        request_response = client.get(f"{BASE}/requests/{request_id}")
        run_response = client.get(f"{BASE}/runs/{run_id}")
        samples_response = client.get(f"{BASE}/runs/{run_id}/samples")
        intervals_response = client.get(f"{BASE}/runs/{run_id}/intervals")
        derive_response = client.post(f"{BASE}/runs/{run_id}/derive-eligibility", json={})
        runs_for_request = client.get(f"{BASE}/runs", params={"request_id": request_id})
        assert request_response.status_code == 404
        assert run_response.status_code == 404
        assert samples_response.status_code == 404
        assert intervals_response.status_code == 404
        assert derive_response.status_code == 404
        assert runs_for_request.status_code == 404
        for response in (
            request_response,
            run_response,
            samples_response,
            intervals_response,
            derive_response,
            runs_for_request,
        ):
            _assert_safe_error(response)
            assert request_id not in response.text
            assert run_id not in response.text
            assert request_checksum not in response.text
            assert geometry_checksum not in response.text

        spoofed_requests = client.get(f"{BASE}/requests", params={"owner_id": "owner-a"})
        spoofed_runs = client.get(f"{BASE}/runs", params={"owner_id": "owner-a"})
        assert spoofed_requests.status_code == 200
        assert spoofed_runs.status_code == 200
        assert spoofed_requests.json()["total"] == 0
        assert spoofed_runs.json()["total"] == 0


def test_geometry_api_tamper_errors_are_sanitized(container: AppContainer) -> None:
    request_id, _run_id, _request_checksum, _geometry_checksum = _persist(container)
    with container.database.session() as session:
        row = session.get(ObservationGeometryRequestRow, request_id)
        assert row is not None
        payload = copy.deepcopy(row.request_json)
        payload["site"]["site_id"] = "TAMPERED"
        row.request_json = payload
        session.commit()

    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        response = client.get(f"{BASE}/requests/{request_id}")
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        _assert_safe_error(response)

    _request_id, run_id, _request_checksum, _geometry_checksum = _persist(
        container,
        site_id="SITE-B",
    )
    with container.database.session() as session:
        row = session.get(ObservationGeometryRunRow, run_id)
        assert row is not None
        row.geometry_checksum = "0" * 64
        session.commit()

    with _owner_client(container, "owner-a", raise_server_exceptions=False) as client:
        response = client.get(f"{BASE}/runs/{run_id}")
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        _assert_safe_error(response)
        samples_response = client.get(f"{BASE}/runs/{run_id}/samples")
        assert samples_response.status_code == 422
        assert samples_response.json()["code"] == "validation_error"
        _assert_safe_error(samples_response)
        intervals_response = client.get(f"{BASE}/runs/{run_id}/intervals")
        assert intervals_response.status_code == 422
        assert intervals_response.json()["code"] == "validation_error"
        _assert_safe_error(intervals_response)
        derive_response = client.post(f"{BASE}/runs/{run_id}/derive-eligibility", json={})
        assert derive_response.status_code == 422
        assert derive_response.json()["code"] == "validation_error"
        _assert_safe_error(derive_response)


@pytest.mark.parametrize(
    "path",
    [
        "/requests/%20bad",
        "/runs/%20bad",
        "/runs/%20bad/derive-eligibility",
        "/runs/%20bad/samples",
        "/runs/%20bad/intervals",
    ],
)
def test_geometry_api_rejects_malformed_path_ids(container: AppContainer, path: str) -> None:
    with _owner_client(container, "owner-a") as client:
        response = (
            client.post(f"{BASE}{path}", json={})
            if path.endswith("derive-eligibility")
            else client.get(f"{BASE}{path}")
        )
    assert response.status_code == 422


def test_geometry_api_no_forbidden_architecture_imports() -> None:
    guarded_files = (
        Path("src/orbitmind/observation_geometry/queries.py"),
        Path("src/orbitmind/api/observation_geometry_schemas.py"),
        Path("src/orbitmind/api/routers/observation_geometry.py"),
    )
    forbidden_prefixes_by_file = {
        "queries.py": (
            "orbitmind.api",
            "orbitmind.observation_planning",
            "orbitmind.quantum",
            "httpx",
            "requests",
        ),
        "observation_geometry_schemas.py": (
            "orbitmind.observation_planning",
            "orbitmind.quantum",
            "httpx",
            "requests",
        ),
        "observation_geometry.py": (
            "orbitmind.observation_geometry.persistence_service",
            "orbitmind.observation_geometry.service",
            "orbitmind.observation_planning.orchestration",
            "orbitmind.observation_planning.provenance_execution",
            "orbitmind.optimization",
            "orbitmind.quantum",
            "httpx",
            "requests",
        ),
    }
    allowed_modules_by_file = {
        "observation_geometry.py": {"orbitmind.observation_planning.geometry_eligibility_adapter"}
    }
    for path in guarded_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_prefixes = forbidden_prefixes_by_file[path.name]
        allowed_modules = allowed_modules_by_file.get(path.name, set())
        for node in ast.walk(tree):
            module = _imported_module(node)
            if module is not None:
                if module in allowed_modules:
                    continue
                assert not module.startswith(forbidden_prefixes), (path, module)
                if module.startswith("orbitmind.observation_planning"):
                    raise AssertionError((path, module))


def test_geometry_api_router_does_not_own_transactions() -> None:
    path = Path("src/orbitmind/api/routers/observation_geometry.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden_attrs = {"begin", "commit", "rollback"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            raise AssertionError((path, node.attr))


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None
