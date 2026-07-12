"""Security and lifecycle coverage for the local custom-TLE replay handoff."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text

from orbitmind.api.app import SECURITY_HEADERS, WORKBENCH_REFERRER_POLICY, create_app
from orbitmind.api.container import AppContainer
from orbitmind.api.routers.workbench import (
    HandoffRequestError,
    _parse_handoff_id,
    run_mission_workbench,
)
from orbitmind.api.transient_handoff import (
    HANDOFF_TOKEN_PATTERN,
    SESSION_COOKIE_NAME,
    CustomTleTransientHandoffStore,
    DiagnosticReason,
    HandoffCapacityError,
    HandoffRecordError,
    HandoffUnavailableError,
    TransientHandoffInput,
    TransientHandoffLimits,
)
from orbitmind.core.config import Settings
from orbitmind.persistence.models import Base
from orbitmind.sample import resolve_custom_offline_tle
from orbitmind.sources.registry import SourceRegistry

ORIGIN = "http://127.0.0.1:8000"
CANONICAL_HEADERS = {"origin": ORIGIN, "sec-fetch-site": "same-origin"}
TOKEN_RE = re.compile(r'name="handoff_id"\s+value="([A-Za-z0-9_-]{43})"')


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _iss_tle() -> tuple[str, str]:
    return SourceRegistry().get_tle("ISS")


def _custom_form(**updates: str) -> dict[str, str]:
    line1, line2 = _iss_tle()
    form = {
        "source_mode": "custom",
        "catalog_sample_id": "",
        "custom_label": "Transient ISS",
        "tle_line1": line1,
        "tle_line2": line2,
        "observer_latitude_deg": "12.5",
        "observer_longitude_deg": "77.6",
        "observer_altitude_metres": "920",
        "start_time_utc": "2019-12-09T19:40:00Z",
        "duration_hours": "1",
        "minimum_elevation_deg": "0",
    }
    form.update(updates)
    return form


def _enabled_settings(tmp_path: Path, **updates: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": f"sqlite:///{(tmp_path / 'handoff.db').as_posix()}",
        "artifacts_dir": tmp_path / "artifacts",
        "cache_dir": tmp_path / "cache",
        "env": "test",
        "custom_tle_handoff_enabled": True,
    }
    values.update(updates)
    return Settings(**values)


@pytest.fixture
def enabled_context(tmp_path: Path) -> Any:
    container = AppContainer(_enabled_settings(tmp_path))
    with TestClient(create_app(container), base_url=ORIGIN) as client:
        yield client, container


def _create_handoff(client: TestClient, **updates: str) -> tuple[str, str]:
    response = client.post(
        "/workbench/run",
        data=_custom_form(**updates),
        headers=CANONICAL_HEADERS,
    )
    assert response.status_code == 200
    match = TOKEN_RE.search(response.text)
    assert match is not None
    cookie = client.cookies.get(SESSION_COOKIE_NAME)
    assert cookie is not None
    return match.group(1), cookie


def _store_input(**updates: Any) -> TransientHandoffInput:
    line1, line2 = _iss_tle()
    resolved = resolve_custom_offline_tle(
        satellite_label="Transient ISS",
        tle_line1=line1,
        tle_line2=line2,
    )
    values: dict[str, Any] = {
        "safe_source_label": resolved.elements.source.name,
        "source_checksum": resolved.elements.element_checksum,
        "stable_source_reference": f"custom-tle:{resolved.elements.element_checksum}",
        "tle_line1": resolved.elements.tle_line1,
        "tle_line2": resolved.elements.tle_line2,
        "observer_latitude_deg": 12.5,
        "observer_longitude_deg": 77.6,
        "observer_altitude_metres": 920.0,
        "start_time_utc": dt.datetime.fromisoformat("2019-12-09T19:40:00+00:00"),
        "end_time_utc": dt.datetime.fromisoformat("2019-12-09T20:40:00+00:00"),
        "sample_interval_seconds": 15,
        "maximum_samples": 2_001,
    }
    values.update(updates)
    return TransientHandoffInput(**values)


def _new_store(
    *,
    clock: _Clock | None = None,
    limits: TransientHandoffLimits | None = None,
    random_bytes: Any = None,
) -> CustomTleTransientHandoffStore:
    return CustomTleTransientHandoffStore(
        limits=limits,
        monotonic=clock or _Clock(),
        random_bytes=random_bytes or secrets.token_bytes,
        hmac_key=b"h" * 32,
    )


def _raw_request(
    body: bytes,
    *,
    content_type: bytes = b"application/x-www-form-urlencoded",
    content_length: bytes | None = None,
) -> Request:
    headers = [(b"content-type", content_type)]
    if content_length is not None:
        headers.append((b"content-length", content_length))
    delivered = False

    async def receive() -> dict[str, Any]:
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/workbench/replay/custom-handoff",
        "raw_path": b"/workbench/replay/custom-handoff",
        "query_string": b"",
        "headers": headers,
        "client": ("127.0.0.1", 1),
        "server": ("127.0.0.1", 8000),
    }
    return Request(scope, receive)


def test_feature_defaults_off_and_explicit_enablement_constructs_store(tmp_path: Path) -> None:
    disabled = AppContainer(
        Settings(
            database_url=f"sqlite:///{(tmp_path / 'off.db').as_posix()}",
            artifacts_dir=tmp_path / "off-artifacts",
        )
    )
    enabled = AppContainer(_enabled_settings(tmp_path))

    assert disabled.settings.custom_tle_handoff_enabled is False
    assert disabled.custom_tle_handoff_store is None
    assert enabled.custom_tle_handoff_store is not None


@pytest.mark.parametrize(
    "updates",
    [
        {"custom_tle_handoff_port": 1023},
        {"custom_tle_handoff_port": 65536},
        {"api_bind_host": "localhost"},
        {"api_workers": 2},
        {"api_reload_enabled": True},
        {"forwarded_header_trust_enabled": True},
    ],
)
def test_invalid_enabled_configuration_fails_before_container_construction(
    tmp_path: Path,
    updates: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        _enabled_settings(tmp_path, **updates)


def test_disabled_custom_result_preserves_honest_unavailable_behavior(
    client: TestClient,
    container: AppContainer,
) -> None:
    response = client.post("/workbench/run", data=_custom_form())

    assert response.status_code == 200
    assert "Direct replay handoff is unavailable" in response.text
    assert "/workbench/replay/custom-handoff" not in response.text
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")
    assert container.custom_tle_handoff_store is None


@pytest.mark.parametrize(
    "host",
    [
        "localhost:8000",
        "[::1]:8000",
        "0.0.0.0:8000",
        "127.1:8000",
        "2130706433:8000",
        "127.0.0.1.:8000",
        "example.test:8000",
        "127.0.0.1:8001",
        "user@127.0.0.1:8000",
        "http://127.0.0.1:8000",
        "127.0.0.1:8000,example.test",
        " 127.0.0.1:8000",
    ],
)
def test_noncanonical_host_rejected_before_state(
    enabled_context: Any,
    host: str,
) -> None:
    client, container = enabled_context
    response = client.post(
        "/workbench/run",
        data=_custom_form(),
        headers={**CANONICAL_HEADERS, "host": host},
    )

    assert response.status_code == 400
    assert "This local Workbench request is unavailable" in response.text
    assert container.custom_tle_handoff_store.record_count() == 0
    assert container.custom_tle_handoff_store.session_count() == 0


@pytest.mark.parametrize(
    "header",
    [
        "forwarded",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-for",
        "x-original-host",
        "x-original-proto",
        "x-original-url",
        "x-real-ip",
        "x-rewrite-url",
    ],
)
def test_forwarded_headers_fail_before_body_or_state(enabled_context: Any, header: str) -> None:
    client, container = enabled_context
    response = client.post(
        "/workbench/run",
        content=b"not-even-a-form",
        headers={**CANONICAL_HEADERS, header: "untrusted"},
    )

    assert response.status_code == 400
    assert container.custom_tle_handoff_store.record_count() == 0
    assert container.custom_tle_handoff_store.session_count() == 0


@pytest.mark.parametrize(
    "origin",
    [
        "null",
        "http://localhost:8000",
        "http://127.0.0.1:8001",
        "https://127.0.0.1:8000",
        "http://127.0.0.1:8000/path",
        "http://user@127.0.0.1:8000",
        "not-an-origin",
    ],
)
def test_mismatched_or_malformed_origin_rejected(enabled_context: Any, origin: str) -> None:
    client, container = enabled_context
    response = client.post(
        "/workbench/run",
        data=_custom_form(),
        headers={"origin": origin, "sec-fetch-site": "same-origin"},
    )

    assert response.status_code == 403
    assert container.custom_tle_handoff_store.record_count() == 0


def test_origin_and_fetch_metadata_are_both_required(enabled_context: Any) -> None:
    client, container = enabled_context
    missing_both = client.post("/workbench/run", data=_custom_form())
    missing_origin = client.post(
        "/workbench/run",
        data=_custom_form(),
        headers={"sec-fetch-site": "same-origin"},
    )
    missing_fetch_metadata = client.post(
        "/workbench/run",
        data=_custom_form(),
        headers={"origin": ORIGIN},
    )

    assert missing_both.status_code == 403
    assert missing_origin.status_code == 403
    assert missing_fetch_metadata.status_code == 403
    assert container.custom_tle_handoff_store.record_count() == 0
    assert container.custom_tle_handoff_store.session_count() == 0
    for response in (missing_both, missing_origin, missing_fetch_metadata):
        assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")


def test_duplicate_host_and_origin_headers_fail_closed(enabled_context: Any) -> None:
    client, container = enabled_context
    duplicate_host = client.post(
        "/workbench/run",
        content=b"unread",
        headers=[
            ("host", "127.0.0.1:8000"),
            ("host", "127.0.0.1:8000"),
            ("origin", ORIGIN),
            ("sec-fetch-site", "same-origin"),
        ],
    )
    duplicate_origin = client.post(
        "/workbench/run",
        content=b"unread",
        headers=[
            ("origin", ORIGIN),
            ("origin", ORIGIN),
            ("sec-fetch-site", "same-origin"),
        ],
    )

    assert duplicate_host.status_code == 400
    assert duplicate_origin.status_code == 403
    assert container.custom_tle_handoff_store.record_count() == 0
    assert container.custom_tle_handoff_store.session_count() == 0


@pytest.mark.parametrize(
    "value",
    ["none", "same-site", "cross-site", "SAME-ORIGIN", "same-origin, same-origin"],
)
def test_invalid_fetch_metadata_rejected(enabled_context: Any, value: str) -> None:
    client, container = enabled_context
    response = client.post(
        "/workbench/run",
        data=_custom_form(),
        headers={"origin": ORIGIN, "sec-fetch-site": value},
    )
    assert response.status_code == 403
    assert container.custom_tle_handoff_store.record_count() == 0
    assert container.custom_tle_handoff_store.session_count() == 0
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")


def test_duplicate_fetch_metadata_rejected_before_state(enabled_context: Any) -> None:
    client, container = enabled_context
    response = client.post(
        "/workbench/run",
        content=b"unread",
        headers=[
            ("origin", ORIGIN),
            ("sec-fetch-site", "same-origin"),
            ("sec-fetch-site", "same-origin"),
        ],
    )

    assert response.status_code == 403
    assert container.custom_tle_handoff_store.record_count() == 0
    assert container.custom_tle_handoff_store.session_count() == 0
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")


def test_protocol_rejection_precedes_body_read_and_state(enabled_context: Any) -> None:
    _client, container = enabled_context
    body_read = False

    async def receive() -> dict[str, Any]:
        nonlocal body_read
        body_read = True
        raise AssertionError("protocol rejection must not read the body")

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/workbench/run",
            "raw_path": b"/workbench/run",
            "query_string": b"",
            "headers": [
                (b"host", b"127.0.0.1:8000"),
                (b"sec-fetch-site", b"same-origin"),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("127.0.0.1", 8000),
        },
        receive,
    )

    response = asyncio.run(run_mission_workbench(request, container))

    assert response.status_code == 403
    assert body_read is False
    assert container.custom_tle_handoff_store.record_count() == 0
    assert container.custom_tle_handoff_store.session_count() == 0
    assert "set-cookie" not in response.headers


def test_enabled_creation_sets_exact_cookie_and_discloses_only_opaque_token(
    enabled_context: Any,
) -> None:
    client, container = enabled_context
    line1, line2 = _iss_tle()
    before_rows = _row_counts(container)
    before_artifacts = _files(container.settings.resolved_artifacts_dir())
    before_cache = _files(container.settings.resolved_cache_dir())
    response = client.post("/workbench/run", data=_custom_form(), headers=CANONICAL_HEADERS)

    assert response.status_code == 200
    token_match = TOKEN_RE.search(response.text)
    assert token_match is not None
    token = token_match.group(1)
    assert HANDOFF_TOKEN_PATTERN.fullmatch(token) is not None
    assert response.text.count(token) == 1
    assert line1 not in response.text and line2 not in response.text
    assert "temporary and single-use" in response.text
    assert "exact custom source, observer, and UTC interval" in response.text
    assert "not live tracking" in response.text
    cookie_header = response.headers["set-cookie"]
    assert cookie_header.startswith(f"{SESSION_COOKIE_NAME}=")
    assert "HttpOnly" in cookie_header
    assert "Max-Age=1800" in cookie_header
    assert "Path=/workbench" in cookie_header
    assert "SameSite=strict" in cookie_header
    assert "Domain=" not in cookie_header and "Secure" not in cookie_header
    cookie = client.cookies.get(SESSION_COOKIE_NAME)
    assert cookie is not None and HANDOFF_TOKEN_PATTERN.fullmatch(cookie) is not None
    assert cookie != token and line1 not in cookie and line2 not in cookie
    assert container.custom_tle_handoff_store.record_count() == 1
    assert container.custom_tle_handoff_store.session_count() == 1
    record = next(iter(container.custom_tle_handoff_store._records.values()))
    assert record.observer_latitude_deg == 12.5
    assert record.observer_longitude_deg == 77.6
    assert record.observer_altitude_metres == 920.0
    assert record.tle_line1 == line1 and record.tle_line2 == line2
    assert _row_counts(container) == before_rows
    assert _files(container.settings.resolved_artifacts_dir()) == before_artifacts
    assert _files(container.settings.resolved_cache_dir()) == before_cache


def test_failed_protocol_creates_no_cookie_session_or_handoff(enabled_context: Any) -> None:
    client, container = enabled_context
    response = client.post(
        "/workbench/run",
        data=_custom_form(),
        headers={"origin": "http://localhost:8000", "sec-fetch-site": "same-origin"},
    )

    assert response.status_code == 403
    assert SESSION_COOKIE_NAME not in response.headers.get("set-cookie", "")
    assert container.custom_tle_handoff_store.session_count() == 0
    assert container.custom_tle_handoff_store.record_count() == 0


def test_malformed_cookie_is_rotated_only_after_valid_protocol(enabled_context: Any) -> None:
    client, container = enabled_context
    client.cookies.set(
        SESSION_COOKIE_NAME,
        "malformed",
        domain="127.0.0.1",
        path="/workbench",
    )
    response = client.post("/workbench/run", data=_custom_form(), headers=CANONICAL_HEADERS)

    assert response.status_code == 200
    rotated = client.cookies.get(
        SESSION_COOKIE_NAME,
        domain="127.0.0.1",
        path="/workbench",
    )
    assert rotated is not None and rotated != "malformed"
    assert HANDOFF_TOKEN_PATTERN.fullmatch(rotated) is not None
    assert container.custom_tle_handoff_store.session_count() == 1


def test_store_token_digest_record_size_repr_and_diagnostics_are_bounded() -> None:
    store = _new_store()
    creation = store.create(_store_input(), submitted_cookie=None)
    digest = hashlib.sha256(creation.handoff_token.encode("ascii")).digest()
    record = store._records[digest]

    assert digest in store._records
    assert record.logical_size_bytes() <= 1_024
    assert repr(record) == "TransientCustomTleHandoffRecord(<redacted>)"
    assert _iss_tle()[0] not in repr(record)
    events = store.diagnostic_events()
    assert len(events) == 1
    assert events[0].reason is DiagnosticReason.CREATED
    event_text = repr(events)
    assert creation.handoff_token not in event_text
    assert creation.session_cookie_value not in event_text
    assert record.source_checksum not in event_text


def test_logical_field_and_total_size_rejection_retains_no_state() -> None:
    store = _new_store()
    with pytest.raises(HandoffRecordError):
        store.create(_store_input(safe_source_label="x" * 81), submitted_cookie=None)

    assert store.record_count() == 0
    assert store.session_count() == 0

    small_store = _new_store(limits=TransientHandoffLimits(maximum_logical_record_bytes=300))
    with pytest.raises(HandoffRecordError):
        small_store.create(_store_input(), submitted_cookie=None)
    assert small_store.record_count() == 0
    assert small_store.session_count() == 0


def test_per_session_capacity_has_no_live_eviction() -> None:
    store = _new_store(
        limits=TransientHandoffLimits(maximum_records=3, maximum_records_per_session=1)
    )
    first = store.create(_store_input(), submitted_cookie=None)
    with pytest.raises(HandoffCapacityError):
        store.create(_store_input(), submitted_cookie=first.session_cookie_value)

    assert store.record_count() == 1
    record = store.consume(
        first.handoff_token,
        submitted_cookie=first.session_cookie_value,
    )
    assert record.source_checksum == _store_input().source_checksum


def test_global_capacity_rejects_without_creating_a_partial_session() -> None:
    store = _new_store(
        limits=TransientHandoffLimits(
            maximum_records=1,
            maximum_records_per_session=1,
        )
    )
    first = store.create(_store_input(), submitted_cookie=None)
    with pytest.raises(HandoffCapacityError):
        store.create(_store_input(), submitted_cookie=None)

    assert store.record_count() == 1
    assert store.session_count() == 1
    store.consume(first.handoff_token, submitted_cookie=first.session_cookie_value)


def test_expired_cleanup_precedes_capacity_and_restart_loses_state() -> None:
    clock = _Clock()
    store = _new_store(
        clock=clock,
        limits=TransientHandoffLimits(maximum_records=1, maximum_records_per_session=1),
    )
    first = store.create(_store_input(), submitted_cookie=None)
    clock.value += 301
    second = store.create(_store_input(), submitted_cookie=first.session_cookie_value)

    assert store.record_count() == 1
    with pytest.raises(HandoffUnavailableError):
        _new_store().consume(
            second.handoff_token,
            submitted_cookie=second.session_cookie_value or first.session_cookie_value,
        )


def test_session_expiry_rotates_without_sliding_and_shutdown_clears_state() -> None:
    clock = _Clock()
    store = _new_store(clock=clock)
    first = store.create(_store_input(), submitted_cookie=None)
    original_cookie = first.session_cookie_value
    assert original_cookie is not None

    clock.value += 1_801
    rotated = store.create(_store_input(), submitted_cookie=original_cookie)
    assert rotated.session_cookie_value is not None
    assert rotated.session_cookie_value != original_cookie
    assert store.session_count() == 1
    assert store.record_count() == 1

    store.clear()
    assert store.session_count() == 0
    assert store.record_count() == 0
    assert store.diagnostic_events() == ()


def test_collision_generation_is_capped_and_retains_first_record() -> None:
    fixed = b"z" * 32
    store = _new_store(random_bytes=lambda _size: fixed)
    first = store.create(_store_input(), submitted_cookie=None)

    with pytest.raises(HandoffCapacityError):
        store.create(_store_input(), submitted_cookie=first.session_cookie_value)
    assert store.record_count() == 1


def test_diagnostic_ring_overwrites_oldest_without_sensitive_correlation() -> None:
    store = _new_store()
    marker = _store_input().source_checksum
    for _ in range(300):
        with pytest.raises(HandoffUnavailableError):
            store.consume("bad", submitted_cookie=None)

    events = store.diagnostic_events()
    assert len(events) == 256
    rendered = repr(events)
    assert marker not in rendered
    assert "tle_line" not in rendered


@pytest.mark.parametrize(
    ("content_type", "status"),
    [
        (b"application/json", 415),
        (b"multipart/form-data", 415),
        (b"text/plain", 415),
        (b"application/x-www-form-urlencoded; charset=latin-1", 415),
        (b"application/x-www-form-urlencoded; charset=utf-8; charset=utf-8", 415),
    ],
)
def test_handoff_parser_rejects_unsupported_media(content_type: bytes, status: int) -> None:
    request = _raw_request(b"handoff_id=" + (b"A" * 43), content_type=content_type)
    with pytest.raises(HandoffRequestError) as exc_info:
        asyncio.run(_parse_handoff_id(request))
    assert exc_info.value.status_code == status


def test_handoff_parser_accepts_missing_length_and_utf8_charset() -> None:
    token = "A" * 43
    body = f"handoff_id={token}".encode()
    request = _raw_request(
        body,
        content_type=b"application/x-www-form-urlencoded; charset=UTF-8",
    )
    assert asyncio.run(_parse_handoff_id(request)) == token


@pytest.mark.parametrize(
    ("body", "length", "status"),
    [
        (b"handoff_id=" + (b"A" * 43), b"1", 422),
        (b"handoff_id=%ZZ", None, 422),
        (b"handoff_id=", None, 422),
        (b"handoff_id=" + (b"A" * 42), None, 422),
        (b"handoff_id=" + (b"A" * 43) + b"&handoff_id=" + (b"B" * 43), None, 422),
        (b"other=" + (b"A" * 43), None, 422),
        (b"x" * 513, None, 413),
        (b"\xff", None, 422),
    ],
)
def test_handoff_parser_bounds_and_strict_form_rules(
    body: bytes,
    length: bytes | None,
    status: int,
) -> None:
    request = _raw_request(body, content_length=length)
    with pytest.raises(HandoffRequestError) as exc_info:
        asyncio.run(_parse_handoff_id(request))
    assert exc_info.value.status_code == status


def test_exact_512_byte_body_is_parsed_before_unknown_field_rejection() -> None:
    prefix = b"handoff_id=" + (b"A" * 43) + b"&padding="
    body = prefix + (b"x" * (512 - len(prefix)))
    request = _raw_request(body, content_length=b"512")
    with pytest.raises(HandoffRequestError) as exc_info:
        asyncio.run(_parse_handoff_id(request))
    assert exc_info.value.status_code == 422


def test_successful_consume_is_single_use_and_errors_keep_csp(enabled_context: Any) -> None:
    client, container = enabled_context
    token, _cookie = _create_handoff(client)
    first = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": token},
        headers=CANONICAL_HEADERS,
    )
    second = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": token},
        headers=CANONICAL_HEADERS,
    )

    assert first.status_code == 200
    assert "Predicted trajectory replay" in first.text
    assert second.status_code == 410
    assert token not in second.text
    assert container.custom_tle_handoff_store.record_count() == 0
    for name, value in SECURITY_HEADERS.items():
        expected = WORKBENCH_REFERRER_POLICY if name == "Referrer-Policy" else value
        assert second.headers[name] == expected


def test_consume_reconstructs_exact_custom_source_observer_and_interval(
    enabled_context: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, container = enabled_context
    line1, line2 = _iss_tle()
    token, _cookie = _create_handoff(client)
    original_calculate = container.trajectory_replay_service.calculate
    captured: list[Any] = []

    def capture(request: Any) -> Any:
        captured.append(request)
        return original_calculate(request)

    monkeypatch.setattr(container.trajectory_replay_service, "calculate", capture)
    response = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": token},
        headers=CANONICAL_HEADERS,
    )

    assert response.status_code == 200
    assert len(captured) == 1
    replay_request = captured[0]
    assert replay_request.orbital_source.tle_line1 == line1
    assert replay_request.orbital_source.tle_line2 == line2
    expected_checksum = resolve_custom_offline_tle(
        satellite_label="Transient ISS",
        tle_line1=line1,
        tle_line2=line2,
    ).elements.element_checksum
    assert replay_request.orbital_source.element_checksum == expected_checksum
    assert replay_request.observer.latitude_deg == 12.5
    assert replay_request.observer.longitude_deg == 77.6
    assert replay_request.start_time == dt.datetime(2019, 12, 9, 19, 40, tzinfo=dt.UTC)
    assert replay_request.end_time == dt.datetime(2019, 12, 9, 20, 40, tzinfo=dt.UTC)
    assert line1 not in response.text and line2 not in response.text


def test_owner_mismatch_does_not_consume_and_correct_owner_can_continue(
    enabled_context: Any,
) -> None:
    client, container = enabled_context
    token, first_cookie = _create_handoff(client)
    client.cookies.clear()
    _other_token, second_cookie = _create_handoff(client, custom_label="Second Browser")
    assert second_cookie != first_cookie

    mismatched = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": token},
        headers=CANONICAL_HEADERS,
    )
    assert mismatched.status_code == 410
    assert container.custom_tle_handoff_store.record_count() == 2

    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, first_cookie, path="/workbench")
    correct = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": token},
        headers=CANONICAL_HEADERS,
    )
    assert correct.status_code == 200
    assert container.custom_tle_handoff_store.record_count() == 1


def test_concurrent_consume_has_exactly_one_success() -> None:
    store = _new_store()
    creation = store.create(_store_input(), submitted_cookie=None)

    def consume() -> bool:
        try:
            store.consume(
                creation.handoff_token,
                submitted_cookie=creation.session_cookie_value,
            )
        except HandoffUnavailableError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _index: consume(), range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7


def test_purpose_mismatch_does_not_remove_record() -> None:
    store = _new_store()
    creation = store.create(_store_input(), submitted_cookie=None)
    digest = hashlib.sha256(creation.handoff_token.encode("ascii")).digest()
    store._records[digest] = replace(store._records[digest], purpose="other-purpose")

    with pytest.raises(HandoffUnavailableError):
        store.consume(
            creation.handoff_token,
            submitted_cookie=creation.session_cookie_value,
        )
    assert store.record_count() == 1


def test_replay_failure_consumes_permanently_without_partial_result(
    enabled_context: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, container = enabled_context
    token, _cookie = _create_handoff(client)

    def fail_replay(_request: object) -> None:
        raise ValueError("internal raw failure detail")

    monkeypatch.setattr(container.trajectory_replay_service, "calculate", fail_replay)
    failed = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": token},
        headers=CANONICAL_HEADERS,
    )
    retried = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": token},
        headers=CANONICAL_HEADERS,
    )

    assert failed.status_code == 422
    assert "could not complete safely" in failed.text
    assert "internal raw failure detail" not in failed.text
    assert "trajectory-replay-data" not in failed.text
    assert retried.status_code == 410
    assert container.custom_tle_handoff_store.record_count() == 0


def test_consume_route_is_post_only_and_disabled_state_is_unavailable(client: TestClient) -> None:
    assert client.get("/workbench/replay/custom-handoff").status_code == 405
    response = client.post(
        "/workbench/replay/custom-handoff",
        data={"handoff_id": "A" * 43},
    )
    assert response.status_code == 410
    assert "A" * 43 not in response.text


def _row_counts(container: AppContainer) -> dict[str, int]:
    names = sorted(Base.metadata.tables)
    with container.database.session() as session:
        return {
            name: int(session.execute(text(f"select count(*) from {name}")).scalar_one())
            for name in names
        }


def _files(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}
