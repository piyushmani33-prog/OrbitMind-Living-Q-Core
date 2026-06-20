"""Reusable cache-first JSON fetcher (generalizes the Phase 2 source cache flow).

Cache-first within TTL → minimum-refresh suppression → live fetch under an
in-process keyed lock. Records a ``SourceFetchRecord`` and upserts the cache entry
via the passed repository; returns the raw body + metadata for the caller to
validate/normalize. No source-specific knowledge lives here.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx
from pydantic import BaseModel

from orbitmind.core.checksums import sha256_bytes
from orbitmind.core.timeutils import utcnow
from orbitmind.persistence.source_repository import SourceRepository
from orbitmind.sources.cache import KeyedLock, SourceCacheStore
from orbitmind.sources.errors import NetworkDisabledError, SourceError
from orbitmind.sources.http_client import SafeHttpFetcher
from orbitmind.sources.models import (
    CacheStatus,
    FetchOutcome,
    SourceCacheRecord,
    SourceFetchRecord,
    SourcePolicy,
)


class CachedFetch(BaseModel):
    """Raw fetch result plus cache/transport metadata."""

    body: bytes
    outcome: FetchOutcome
    cache_status: CacheStatus
    fetched_at: datetime
    from_cache: bool
    http_status: int
    content_type: str
    checksum: str
    expires_at: datetime


class CachedSourceFetcher:
    """Cache-first fetcher for a single source policy."""

    def __init__(
        self,
        policy: SourcePolicy,
        cache_store: SourceCacheStore,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        lock: KeyedLock | None = None,
    ) -> None:
        self._policy = policy
        self._store = cache_store
        self._transport = transport
        self._sleep = sleep
        self._lock = lock or KeyedLock()

    def fetch(
        self,
        *,
        cache_key: str,
        url: str,
        params: dict[str, str],
        repo: SourceRepository,
        force_refresh: bool = False,
    ) -> CachedFetch:
        now = utcnow()
        cached = repo.get_cache_entry(cache_key)

        if cached is not None and not force_refresh and cached.expires_at > now:
            return self._serve_cache(cache_key, url, cached, repo, CacheStatus.HIT)

        if (
            cached is not None
            and (now - cached.fetched_at).total_seconds() < self._policy.min_refresh_seconds
        ):
            return self._serve_cache(
                cache_key, url, cached, repo, CacheStatus.SUPPRESSED, suppressed=True
            )

        with self._lock.acquire(cache_key):
            cached = repo.get_cache_entry(cache_key)
            if cached is not None and not force_refresh and cached.expires_at > now:
                return self._serve_cache(cache_key, url, cached, repo, CacheStatus.HIT)
            return self._fetch_live(cache_key, url, params, repo)

    def _serve_cache(
        self,
        cache_key: str,
        url: str,
        cached: SourceCacheRecord,
        repo: SourceRepository,
        cache_status: CacheStatus,
        *,
        suppressed: bool = False,
    ) -> CachedFetch:
        body = self._store.read_body(cached.body_path)
        outcome = FetchOutcome.SUPPRESSED if suppressed else FetchOutcome.CACHED
        repo.add_fetch(
            SourceFetchRecord(
                source_id=self._policy.source_id,
                cache_key=cache_key,
                url=cached.url,
                outcome=outcome,
                http_status=cached.http_status,
                content_type=cached.content_type,
                response_bytes=len(body),
                checksum=cached.checksum,
                schema_version=cached.schema_version,
                from_cache=True,
                completed_at=utcnow(),
            )
        )
        return CachedFetch(
            body=body,
            outcome=outcome,
            cache_status=cache_status,
            fetched_at=cached.fetched_at,
            from_cache=True,
            http_status=cached.http_status,
            content_type=cached.content_type,
            checksum=cached.checksum,
            expires_at=cached.expires_at,
        )

    def _fetch_live(
        self, cache_key: str, url: str, params: dict[str, str], repo: SourceRepository
    ) -> CachedFetch:
        if not self._policy.network_enabled:
            repo.add_fetch(
                SourceFetchRecord(
                    source_id=self._policy.source_id,
                    cache_key=cache_key,
                    url=url,
                    outcome=FetchOutcome.DISABLED,
                    error="network access disabled by policy",
                )
            )
            raise NetworkDisabledError("network access is disabled by policy")

        fetcher = SafeHttpFetcher(self._policy, transport=self._transport, sleep=self._sleep)
        fetched_at = utcnow()
        try:
            http = fetcher.get(url, params)
        except SourceError as exc:
            repo.add_fetch(
                SourceFetchRecord(
                    source_id=self._policy.source_id,
                    cache_key=cache_key,
                    url=url,
                    outcome=FetchOutcome.FAILED,
                    error=exc.message,
                    completed_at=utcnow(),
                )
            )
            raise

        checksum = sha256_bytes(http.body)
        expires_at = fetched_at + timedelta(seconds=self._policy.cache_ttl_seconds)
        body_path = self._store.write_body(self._policy.source_id, cache_key, http.body)
        repo.upsert_cache_entry(
            SourceCacheRecord(
                cache_key=cache_key,
                source_id=self._policy.source_id,
                url=http.url,
                body_path=body_path,
                checksum=checksum,
                schema_version=self._policy.schema_version,
                http_status=http.status_code,
                content_type=http.content_type,
                fetched_at=fetched_at,
                expires_at=expires_at,
                last_success_at=fetched_at,
            )
        )
        repo.add_fetch(
            SourceFetchRecord(
                source_id=self._policy.source_id,
                cache_key=cache_key,
                url=http.url,
                outcome=FetchOutcome.FETCHED,
                http_status=http.status_code,
                content_type=http.content_type,
                response_bytes=len(http.body),
                checksum=checksum,
                schema_version=self._policy.schema_version,
                from_cache=False,
                completed_at=utcnow(),
            )
        )
        return CachedFetch(
            body=http.body,
            outcome=FetchOutcome.FETCHED,
            cache_status=CacheStatus.STORED,
            fetched_at=fetched_at,
            from_cache=False,
            http_status=http.status_code,
            content_type=http.content_type,
            checksum=checksum,
            expires_at=expires_at,
        )
