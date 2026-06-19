"""Safe HTTP fetcher for source connectors (ADR-0009).

Hard constraints enforced here:
- network must be enabled by policy (global AND source switch resolved upstream),
- HTTPS only, hostname allowlisted, no redirects,
- explicit connect/read timeouts, bounded retries with backoff,
- response-size cap (streamed), content-type validation,
- descriptive User-Agent, GET only, no arbitrary user-supplied URL.

Tests inject an ``httpx`` transport (e.g. ``MockTransport``) so no real network is
used. The real transport is the default only when network is actually enabled.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel

from orbitmind.core.logging import get_logger
from orbitmind.sources.errors import (
    DisallowedRequestError,
    NetworkDisabledError,
    SourceUnavailableError,
)
from orbitmind.sources.models import SourcePolicy

_log = get_logger("sources.http_client")

USER_AGENT = "OrbitMind/0.1 (+https://example.invalid/orbitmind; scientific orbital data)"


class HttpFetchResult(BaseModel):
    """The outcome of a safe HTTP GET (body bytes plus transport metadata)."""

    url: str
    status_code: int
    content_type: str
    body: bytes


class SafeHttpFetcher:
    """Performs policy-constrained HTTPS GET requests."""

    def __init__(
        self,
        policy: SourcePolicy,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._policy = policy
        self._transport = transport
        self._sleep = sleep

    def get(self, url: str, params: dict[str, str]) -> HttpFetchResult:
        """Perform a safe GET. Raises on policy violation or unavailability."""
        if not self._policy.network_enabled:
            raise NetworkDisabledError("network access is disabled by policy")

        self._enforce_url_policy(url)
        if "GET" not in self._policy.allowed_methods:
            raise DisallowedRequestError("GET is not an allowed method for this source")

        timeout = httpx.Timeout(
            connect=self._policy.connect_timeout_seconds,
            read=self._policy.read_timeout_seconds,
            write=self._policy.read_timeout_seconds,
            pool=self._policy.connect_timeout_seconds,
        )
        attempts = self._policy.max_retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                with httpx.Client(
                    transport=self._transport,
                    timeout=timeout,
                    follow_redirects=False,  # reject redirects to non-allowlisted hosts
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                ) as client:
                    return self._stream_get(client, url, params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = exc
                _log.warning("source.fetch_retry", attempt=attempt + 1, error=str(exc))
            except SourceUnavailableError as exc:
                # 5xx is retryable; re-raise non-retryable transport/policy errors.
                last_error = exc
            if attempt < attempts - 1:
                self._sleep(min(0.5 * (2**attempt), 5.0))

        raise SourceUnavailableError("source request failed after retries") from last_error

    def _stream_get(
        self, client: httpx.Client, url: str, params: dict[str, str]
    ) -> HttpFetchResult:
        max_bytes = self._policy.max_response_bytes
        with client.stream("GET", url, params=params) as response:
            if 300 <= response.status_code < 400:
                raise DisallowedRequestError("redirects are not permitted")
            if response.status_code >= 500:
                raise SourceUnavailableError(f"source returned status {response.status_code}")
            if response.status_code != 200:
                raise SourceUnavailableError(f"unexpected status {response.status_code}")

            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type and content_type not in self._policy.allowed_content_types:
                raise DisallowedRequestError(f"disallowed content-type: {content_type}")

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise DisallowedRequestError("response exceeded maximum size")
                chunks.append(chunk)

            return HttpFetchResult(
                url=str(response.url),
                status_code=response.status_code,
                content_type=content_type or "application/json",
                body=b"".join(chunks),
            )

    def _enforce_url_policy(self, url: str) -> None:
        parts = urlsplit(url)
        if self._policy.https_only and parts.scheme != "https":
            raise DisallowedRequestError("only HTTPS requests are permitted")
        host = parts.hostname or ""
        if host not in self._policy.allowed_hostnames:
            raise DisallowedRequestError(f"host '{host}' is not allowlisted")
