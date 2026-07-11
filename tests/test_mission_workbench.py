"""Browser-route coverage for the deterministic offline Mission Workbench."""

from __future__ import annotations

import re
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from orbitmind.api.container import AppContainer
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.sources.celestrak.connector import CelestrakConnector
from orbitmind.sources.registry import SourceRegistry


def _iss_tle() -> tuple[str, str]:
    return SourceRegistry().get_tle("ISS")


def _catalog_form(**updates: str) -> dict[str, str]:
    form = {
        "source_mode": "catalog",
        "catalog_sample_id": "iss",
        "custom_label": "",
        "tle_line1": "",
        "tle_line2": "",
        "observer_latitude_deg": "0",
        "observer_longitude_deg": "0",
        "observer_altitude_metres": "0",
        "start_time_utc": "2019-12-09T19:40:00Z",
        "duration_hours": "1",
        "minimum_elevation_deg": "0",
    }
    form.update(updates)
    return form


def _custom_form(**updates: str) -> dict[str, str]:
    line1, line2 = _iss_tle()
    form = _catalog_form(
        source_mode="custom",
        catalog_sample_id="",
        custom_label="Review ISS",
        tle_line1=line1,
        tle_line2=line2,
    )
    form.update(updates)
    return form


def test_workbench_get_renders_complete_accessible_offline_form(client: TestClient) -> None:
    response = client.get("/workbench")

    assert response.status_code == 200
    body = response.text
    for expected in (
        "OrbitMind Mission Workbench",
        "Satellite or spacecraft",
        "Offline catalog",
        "Custom offline TLE",
        "observer_latitude_deg",
        "observer_longitude_deg",
        "observer_altitude_metres",
        "start_time_utc",
        "duration_hours",
        "minimum_elevation_deg",
        "Calculate Mission Windows",
        "Back to reviewer sandbox",
        "not live tracking",
    ):
        assert expected in body
    assert "cdn" not in body.lower()
    assert "<script" not in body.lower()


def test_valid_catalog_request_renders_useful_result_before_evidence(
    client: TestClient,
    container: AppContainer,
) -> None:
    response = client.post("/workbench/run", data=_catalog_form())

    assert response.status_code == 200
    body = response.text
    assert "Next predicted pass/contact window" in body
    assert "Complete window within analysis interval" in body
    assert "Maximum elevation" in body
    assert "Rise direction" in body
    assert "Source epoch" in body
    assert "Source age at start" in body
    assert "Offline orbital source" in body
    assert "Predicted geometry" in body
    assert body.index("Next predicted pass/contact window") < body.index("Method and evidence")
    _assert_no_mission_persisted(container)


def test_valid_custom_tle_request_escapes_label_and_never_renders_tle_lines(
    client: TestClient,
    container: AppContainer,
) -> None:
    line1, line2 = _iss_tle()
    response = client.post(
        "/workbench/run",
        data=_custom_form(custom_label="Alpha & Beta"),
    )

    assert response.status_code == 200
    body = response.text
    assert "Alpha &amp; Beta" in body
    assert "User-provided offline TLE" in body
    assert line1 not in body
    assert line2 not in body
    assert "Next predicted pass/contact window" in body
    _assert_no_mission_persisted(container)


@pytest.mark.parametrize(
    ("form_factory", "updates"),
    [
        (_catalog_form, {"tle_line1": _iss_tle()[0], "tle_line2": _iss_tle()[1]}),
        (_catalog_form, {"source_mode": "", "catalog_sample_id": ""}),
    ],
)
def test_source_mode_must_be_exactly_one(
    client: TestClient,
    form_factory: Callable[..., dict[str, str]],
    updates: dict[str, str],
) -> None:
    response = client.post("/workbench/run", data=form_factory(**updates))

    assert response.status_code == 422
    assert "Choose exactly one offline source mode" in response.text
    assert "Traceback" not in response.text


def test_unknown_catalog_id_fails_without_fallback(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        data=_catalog_form(catalog_sample_id="unknown"),
    )

    assert response.status_code == 422
    assert "could not be validated" in response.text
    assert "Next predicted pass/contact window" not in response.text
    assert "unknown" not in response.text


@pytest.mark.parametrize(
    "updates",
    [
        {"tle_line1": "not a TLE"},
        {"tle_line2": "not a TLE"},
        {"tle_line1": ""},
        {"tle_line2": ""},
    ],
)
def test_malformed_custom_tle_fails_safely(
    client: TestClient,
    updates: dict[str, str],
) -> None:
    response = client.post("/workbench/run", data=_custom_form(**updates))

    assert response.status_code == 422
    assert "Traceback" not in response.text
    assert "not a TLE" not in response.text
    assert _iss_tle()[0] not in response.text


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("observer_latitude_deg", "91", "latitude must be between"),
        ("observer_longitude_deg", "181", "longitude must be between"),
        ("observer_altitude_metres", "9001", "altitude must be between"),
        ("start_time_utc", "2019-12-09T19:40:00", "explicit UTC offset"),
        ("start_time_utc", "not-a-time", "ISO UTC timestamp"),
        ("duration_hours", "25", "between 1 and 24"),
        ("minimum_elevation_deg", "90", "below 90 degrees"),
        ("observer_latitude_deg", "nan", "must be finite"),
        ("minimum_elevation_deg", "inf", "must be finite"),
    ],
)
def test_invalid_scalar_inputs_fail_with_safe_specific_messages(
    client: TestClient,
    field: str,
    value: str,
    message: str,
) -> None:
    response = client.post("/workbench/run", data=_catalog_form(**{field: value}))

    assert response.status_code == 422
    assert message in response.text
    assert "Traceback" not in response.text


def test_non_utc_offset_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        data=_catalog_form(start_time_utc="2019-12-10T01:10:00+05:30"),
    )

    assert response.status_code == 422
    assert "must use UTC" in response.text


def test_unexpected_and_duplicate_fields_fail_closed(client: TestClient) -> None:
    unexpected = client.post(
        "/workbench/run",
        data={**_catalog_form(), "provider_url": "https://example.test"},
    )
    duplicate = client.post(
        "/workbench/run",
        content=(
            "source_mode=catalog&source_mode=custom&catalog_sample_id=iss&custom_label="
            "&tle_line1=&tle_line2=&observer_latitude_deg=0&observer_longitude_deg=0"
            "&observer_altitude_metres=0&start_time_utc=2019-12-09T19%3A40%3A00Z"
            "&duration_hours=1&minimum_elevation_deg=0"
        ),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert unexpected.status_code == 422
    assert "unexpected field" in unexpected.text
    assert duplicate.status_code == 422
    assert "supplied once" in duplicate.text


def test_oversized_form_is_rejected_before_parsing(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        content=b"source_mode=catalog&padding=" + (b"x" * 5_000),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 413
    assert "4096-byte limit" in response.text
    assert "x" * 100 not in response.text


def test_multiple_windows_render_in_deterministic_order(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        data=_catalog_form(
            start_time_utc="2019-12-09T17:00:00Z",
            duration_hours="24",
        ),
    )

    assert response.status_code == 200
    body = response.text
    assert "All qualifying windows" in body
    assert "4 qualifying window(s)" in body
    rise_times = re.findall(r"<td>\d+</td>\s*<td>(2019-[^<]+Z)</td>", body)
    assert len(rise_times) == 4
    assert rise_times == sorted(rise_times)


def test_no_pass_is_a_successful_useful_empty_state(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        data=_catalog_form(minimum_elevation_deg="89"),
    )

    assert response.status_code == 200
    body = response.text
    assert "No qualifying geometric window was found in the requested interval." in body
    assert "lowering the minimum elevation threshold" in body
    assert "2019-12-09T19:40:00.000Z" in body
    assert "89.00°" in body


def test_clipped_at_start_uses_honest_boundary_wording(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        data=_catalog_form(start_time_utc="2019-12-09T20:00:00Z"),
    )

    assert response.status_code == 200
    body = response.text
    assert "Active at analysis start" in body
    assert "Rise / boundary" in body
    assert "2019-12-09T20:00:00.000Z" in body


def test_clipped_at_end_uses_honest_boundary_wording(client: TestClient) -> None:
    response = client.post(
        "/workbench/run",
        data=_catalog_form(start_time_utc="2019-12-09T19:00:00Z"),
    )

    assert response.status_code == 200
    body = response.text
    assert "Continues after analysis end" in body
    assert "Set / boundary" in body
    assert "2019-12-09T20:00:00.000Z" in body


def test_accuracy_language_and_collapsed_evidence_are_complete(client: TestClient) -> None:
    response = client.post("/workbench/run", data=_catalog_form())

    assert response.status_code == 200
    body = response.text
    for expected in (
        "Predicted from the identified orbital element set using the pinned propagation",
        "Geometric window only; optical visibility is not assessed.",
        "Not live tracking and no guaranteed visibility.",
        "Not certified for command, collision, or safety decisions.",
        "UTC is used as a UT1 approximation",
        "full Earth-orientation and polar-motion corrections are not applied",
        "Propagator",
        "Geometry model",
        "Event tolerance",
        "Coarse sample step",
        "Input reference",
        "Result reference",
        "Source checksum",
    ):
        assert expected in body
    assert re.search(r"<details class=\"section-gap\">\s*<summary>", body)
    assert "<details open" not in body
    assert "100% accurate" not in body


def test_custom_label_path_marker_is_rejected_without_reflection(client: TestClient) -> None:
    marker = "C:\\private\\secret-orbit.txt"
    response = client.post(
        "/workbench/run",
        data=_custom_form(custom_label=marker),
    )

    assert response.status_code == 422
    assert marker not in response.text
    assert "unsupported characters" in response.text


def test_route_never_calls_celestrak(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Mission Workbench must not call CelesTrak")

    monkeypatch.setattr(CelestrakConnector, "get_element_record", fail_network)
    response = client.post("/workbench/run", data=_catalog_form())

    assert response.status_code == 200


def test_fixed_request_has_stable_visible_scientific_values(client: TestClient) -> None:
    first = client.post("/workbench/run", data=_catalog_form())
    second = client.post("/workbench/run", data=_catalog_form())

    assert first.status_code == second.status_code == 200
    assert first.text == second.text


def test_existing_reviewer_navigation_and_offline_surfaces_remain_available(
    client: TestClient,
    container: AppContainer,
) -> None:
    review = client.get("/review")

    assert review.status_code == 200
    assert 'href="/workbench"' in review.text
    assert client.get("/review/custom-tle").status_code == 200
    assert client.get("/review/catalog").status_code == 200
    assert client.get("/observe").status_code == 200
    assert container.settings.network_enabled is False
    assert container.settings.celestrak_enabled is False
    assert container.settings.open_research_enabled is False


def _assert_no_mission_persisted(container: AppContainer) -> None:
    with container.database.session() as session:
        assert SqlAlchemyMissionRepository(session).list_missions(limit=1, offset=0) == []
