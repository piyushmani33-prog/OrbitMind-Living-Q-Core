"""CelesTrak GP connector: cache-first fetch, normalize, freshness, health.

Reuses the existing deterministic SGP4 path by normalizing CelesTrak OMM/GP JSON
into canonical TLE lines. CelesTrak response structures never leave this module.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta

import httpx

from orbitmind.core.checksums import sha256_bytes
from orbitmind.core.logging import get_logger
from orbitmind.core.timeutils import utcnow
from orbitmind.persistence.source_repository import SourceRepository
from orbitmind.sources.cache import KeyedLock, SourceCacheStore, cache_key_for
from orbitmind.sources.celestrak.models import CelestrakGpRecord
from orbitmind.sources.errors import (
    NetworkDisabledError,
    ObjectNotFoundError,
    SourceError,
    SourceIntegrityError,
    SourceSchemaError,
)
from orbitmind.sources.freshness import assess_external_freshness
from orbitmind.sources.http_client import SafeHttpFetcher
from orbitmind.sources.models import (
    CacheStatus,
    DataLiveness,
    ElementFetchResult,
    FetchOutcome,
    OrbitalElementRecord,
    SourceCacheRecord,
    SourceDefinition,
    SourceFetchRecord,
    SourceHealth,
    SourceHealthStatus,
    SourcePolicy,
)
from orbitmind.space.elements import ElementParseError, omm_fields_to_tle, parse_omm_epoch

_log = get_logger("sources.celestrak")


class CelestrakConnector:
    """Implements the generic ``OrbitalSource`` interface for CelesTrak GP data."""

    def __init__(
        self,
        definition: SourceDefinition,
        cache_store: SourceCacheStore,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        lock: KeyedLock | None = None,
    ) -> None:
        self._def = definition
        self._policy = definition.policy
        self._store = cache_store
        self._transport = transport
        self._sleep = sleep
        self._lock = lock or KeyedLock()

    @property
    def source_id(self) -> str:
        return self._def.source_id

    def policy(self) -> SourcePolicy:
        return self._policy

    def read_cache(self, satellite_id: str, repo: SourceRepository) -> SourceCacheRecord | None:
        return repo.get_cache_entry(cache_key_for(self.source_id, satellite_id))

    def health(self, repo: SourceRepository) -> SourceHealthStatus:
        last_success, last_failure, reason = repo.last_fetch_outcomes(self.source_id)
        if not self._def.enabled or not self._policy.network_enabled:
            health = SourceHealth.DISABLED
            detail = "network or source access is disabled by policy"
        elif last_failure is not None and (last_success is None or last_failure > last_success):
            health = SourceHealth.DEGRADED
            detail = "most recent fetch failed"
        elif last_success is not None:
            health = SourceHealth.HEALTHY
            detail = "most recent fetch succeeded"
        else:
            health = SourceHealth.UNKNOWN
            detail = "no fetch attempts recorded"
        return SourceHealthStatus(
            source_id=self.source_id,
            health=health,
            network_enabled=self._policy.network_enabled,
            source_enabled=self._def.enabled,
            last_success_at=last_success,
            last_failure_at=last_failure,
            last_failure_reason=reason,
            detail=detail,
        )

    def get_element_record(
        self,
        satellite_id: str,
        repo: SourceRepository,
        *,
        force_refresh: bool = False,
    ) -> ElementFetchResult:
        cache_key = cache_key_for(self.source_id, satellite_id)
        now = utcnow()
        cached = repo.get_cache_entry(cache_key)

        # 1) Serve a valid cache entry (within TTL) unless a refresh is forced.
        if cached is not None and not force_refresh and cached.expires_at > now:
            return self._from_cache(satellite_id, cache_key, cached, repo, CacheStatus.HIT)

        # 2) Respect the minimum refresh interval (prevents over-polling / storms).
        if (
            cached is not None
            and (now - cached.fetched_at).total_seconds() < self._policy.min_refresh_seconds
        ):
            return self._from_cache(
                satellite_id, cache_key, cached, repo, CacheStatus.SUPPRESSED, suppressed=True
            )

        # 3) A live fetch is required — serialize per key to avoid a refresh storm.
        with self._lock.acquire(cache_key):
            cached = repo.get_cache_entry(cache_key)
            if cached is not None and not force_refresh and cached.expires_at > now:
                return self._from_cache(satellite_id, cache_key, cached, repo, CacheStatus.HIT)
            return self._fetch_live(satellite_id, cache_key, repo, now)

    # ---- internals ---------------------------------------------------------
    def _from_cache(
        self,
        satellite_id: str,
        cache_key: str,
        cached: SourceCacheRecord,
        repo: SourceRepository,
        cache_status: CacheStatus,
        *,
        suppressed: bool = False,
    ) -> ElementFetchResult:
        body = self._store.read_body(cached.body_path)
        if sha256_bytes(body) != cached.checksum:
            raise SourceIntegrityError("cached CelesTrak payload checksum mismatch")
        record = self._normalize(
            body,
            satellite_id,
            fetched_at=cached.fetched_at,
            cache_status=cache_status,
            liveness=DataLiveness.CACHED,
            expires_at=cached.expires_at,
        )
        outcome = FetchOutcome.SUPPRESSED if suppressed else FetchOutcome.CACHED
        fetch = SourceFetchRecord(
            source_id=self.source_id,
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
        repo.add_fetch(fetch)
        return ElementFetchResult(record=record, fetch=fetch)

    def _fetch_live(
        self, satellite_id: str, cache_key: str, repo: SourceRepository, now: datetime
    ) -> ElementFetchResult:
        url = self._policy.base_url
        if not self._policy.network_enabled:
            repo.add_fetch(
                SourceFetchRecord(
                    source_id=self.source_id,
                    cache_key=cache_key,
                    url=url,
                    outcome=FetchOutcome.DISABLED,
                    error="network access disabled by policy",
                )
            )
            raise NetworkDisabledError("network access is disabled by policy")

        fetcher = SafeHttpFetcher(self._policy, transport=self._transport, sleep=self._sleep)
        params = {"CATNR": satellite_id, "FORMAT": "json"}
        fetched_at = utcnow()
        try:
            http = fetcher.get(url, params)
            checksum = sha256_bytes(http.body)
            expires_at = fetched_at + timedelta(seconds=self._policy.cache_ttl_seconds)
            record = self._normalize(
                http.body,
                satellite_id,
                fetched_at=fetched_at,
                cache_status=CacheStatus.STORED,
                liveness=DataLiveness.LIVE,
                expires_at=expires_at,
            )
        except SourceError as exc:
            repo.add_fetch(
                SourceFetchRecord(
                    source_id=self.source_id,
                    cache_key=cache_key,
                    url=url,
                    outcome=FetchOutcome.FAILED,
                    error=exc.message,
                    completed_at=utcnow(),
                )
            )
            raise

        body_path = self._store.write_body(self.source_id, cache_key, http.body)
        repo.upsert_cache_entry(
            SourceCacheRecord(
                cache_key=cache_key,
                source_id=self.source_id,
                url=http.url,
                body_path=body_path,
                checksum=checksum,
                schema_version=self._policy.schema_version,
                http_status=http.status_code,
                content_type=http.content_type,
                fetched_at=fetched_at,
                expires_at=expires_at,
                effective_epoch=record.epoch,
                last_success_at=fetched_at,
            )
        )
        fetch = SourceFetchRecord(
            source_id=self.source_id,
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
        repo.add_fetch(fetch)
        _log.info("source.fetched", source=self.source_id, satellite_id=satellite_id)
        return ElementFetchResult(record=record, fetch=fetch)

    def _normalize(
        self,
        body: bytes,
        satellite_id: str,
        *,
        fetched_at: datetime | None,
        cache_status: CacheStatus,
        liveness: DataLiveness,
        expires_at: datetime | None,
    ) -> OrbitalElementRecord:
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise SourceSchemaError(f"response was not valid JSON: {exc}") from exc
        if not isinstance(data, list):
            raise SourceSchemaError("expected a JSON array of GP records")
        if not data:
            raise ObjectNotFoundError("CelesTrak returned no GP record for the requested NORAD ID")
        if len(data) != 1:
            raise SourceSchemaError(
                "CelesTrak returned multiple GP records for one requested NORAD ID"
            )
        try:
            raw = CelestrakGpRecord.model_validate(data[0])
            requested_norad_id = int(satellite_id)
        except (TypeError, ValueError) as exc:
            raise SourceSchemaError(f"GP record failed validation: {exc}") from exc
        if raw.norad_cat_id != requested_norad_id:
            raise SourceSchemaError(
                "CelesTrak GP record identifier did not match the requested NORAD ID"
            )
        try:
            omm = raw.to_omm_fields()
            line1, line2 = omm_fields_to_tle(omm)
            epoch = parse_omm_epoch(omm)
        except (ElementParseError, ValueError) as exc:
            raise SourceSchemaError(f"GP record failed validation/normalization: {exc}") from exc

        freshness = assess_external_freshness(
            policy=self._policy,
            data_epoch=epoch,
            fetched_at=fetched_at,
            cache_status=cache_status,
            liveness=liveness,
            expires_at=expires_at,
        )
        return OrbitalElementRecord(
            satellite_id=satellite_id,
            object_name=raw.object_name,
            norad_cat_id=raw.norad_cat_id,
            object_id=raw.object_id,
            epoch=epoch,
            tle_line1=line1,
            tle_line2=line2,
            inclination_deg=raw.inclination,
            eccentricity=raw.eccentricity,
            mean_motion=raw.mean_motion,
            source_id=self.source_id,
            schema_version=self._policy.schema_version,
            checksum=sha256_bytes(body),
            freshness=freshness,
        )
