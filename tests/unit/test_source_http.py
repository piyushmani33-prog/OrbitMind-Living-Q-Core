"""Unit tests for the safe HTTP fetcher and source policy enforcement."""

from __future__ import annotations

import httpx
import pytest
from tests.conftest import make_transport

from orbitmind.sources.errors import (
    DisallowedRequestError,
    NetworkDisabledError,
    SourceUnavailableError,
)
from orbitmind.sources.http_client import SafeHttpFetcher
from orbitmind.sources.models import SourcePolicy
from orbitmind.sources.policies import SourceCatalog

URL = "https://celestrak.org/NORAD/elements/gp.php"


def _policy(catalog: SourceCatalog, **overrides: object) -> SourcePolicy:
    policy = catalog.get("celestrak").policy
    return policy.model_copy(update=overrides) if overrides else policy


def test_network_disabled_raises(celestrak_catalog: SourceCatalog) -> None:
    policy = _policy(celestrak_catalog, network_enabled=False)
    fetcher = SafeHttpFetcher(policy, transport=make_transport(records=[]))
    with pytest.raises(NetworkDisabledError):
        fetcher.get(URL, {})


def test_https_enforced(celestrak_catalog: SourceCatalog) -> None:
    fetcher = SafeHttpFetcher(_policy(celestrak_catalog), transport=make_transport(records=[]))
    with pytest.raises(DisallowedRequestError, match="HTTPS"):
        fetcher.get("http://celestrak.org/x", {})


def test_hostname_allowlist(celestrak_catalog: SourceCatalog) -> None:
    fetcher = SafeHttpFetcher(_policy(celestrak_catalog), transport=make_transport(records=[]))
    with pytest.raises(DisallowedRequestError, match="allowlist"):
        fetcher.get("https://evil.example.com/gp", {})


def test_wrong_content_type_rejected(celestrak_catalog: SourceCatalog) -> None:
    transport = make_transport(records=[], content_type="text/html")
    fetcher = SafeHttpFetcher(_policy(celestrak_catalog), transport=transport)
    with pytest.raises(DisallowedRequestError, match="content-type"):
        fetcher.get(URL, {})


def test_oversized_response_rejected(celestrak_catalog: SourceCatalog) -> None:
    policy = _policy(celestrak_catalog, max_response_bytes=10)
    transport = make_transport(raw_body=b'[{"x": "much larger than ten bytes"}]')
    fetcher = SafeHttpFetcher(policy, transport=transport)
    with pytest.raises(DisallowedRequestError, match="maximum size"):
        fetcher.get(URL, {})


def test_redirect_rejected(celestrak_catalog: SourceCatalog) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example.com"})

    fetcher = SafeHttpFetcher(_policy(celestrak_catalog), transport=httpx.MockTransport(handler))
    with pytest.raises(DisallowedRequestError, match="redirect"):
        fetcher.get(URL, {})


def test_server_error_retried_then_unavailable(celestrak_catalog: SourceCatalog) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"err": "down"})

    policy = _policy(celestrak_catalog, max_retries=2)
    sleeps: list[float] = []
    fetcher = SafeHttpFetcher(policy, transport=httpx.MockTransport(handler), sleep=sleeps.append)
    with pytest.raises(SourceUnavailableError):
        fetcher.get(URL, {})
    assert calls["n"] == 3  # 1 initial + 2 retries
    assert len(sleeps) == 2  # bounded backoff, no infinite retry


def test_successful_fetch_returns_body(celestrak_catalog: SourceCatalog) -> None:
    transport = make_transport(records=[{"OBJECT_NAME": "ISS"}])
    fetcher = SafeHttpFetcher(_policy(celestrak_catalog), transport=transport)
    result = fetcher.get(URL, {"CATNR": "25544", "FORMAT": "json"})
    assert result.status_code == 200
    assert result.content_type == "application/json"
    assert b"ISS" in result.body
