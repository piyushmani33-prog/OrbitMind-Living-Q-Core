"""JPL/CNEOS Close-Approach Data connector (guarded, bounded)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.errors import ValidationError
from orbitmind.persistence.source_repository import SourceRepository
from orbitmind.smallbody.models import CloseApproachResultSet, JplSourceRecord
from orbitmind.smallbody.query import CadQueryFilter
from orbitmind.sources.cache import KeyedLock, SourceCacheStore
from orbitmind.sources.errors import SourceSchemaError
from orbitmind.sources.fetching import CachedSourceFetcher
from orbitmind.sources.jpl.cad_models import CadResponse
from orbitmind.sources.jpl.common import canonical_cache_key, jpl_freshness
from orbitmind.sources.jpl.normalization import normalize_cad
from orbitmind.sources.models import SourceDefinition, SourcePolicy


class CadConnector:
    """Guarded JPL/CNEOS Close-Approach Data query."""

    def __init__(
        self,
        definition: SourceDefinition,
        cache_store: SourceCacheStore,
        *,
        max_results: int = 200,
        max_query_span_days: int = 366,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        lock: KeyedLock | None = None,
    ) -> None:
        self._def = definition
        self._policy = definition.policy
        self._max_results = max_results
        self._max_span_days = max_query_span_days
        self._fetcher = CachedSourceFetcher(
            self._policy, cache_store, transport=transport, sleep=sleep, lock=lock
        )

    @property
    def source_id(self) -> str:
        return self._def.source_id

    def policy(self) -> SourcePolicy:
        return self._policy

    def close_approaches(
        self, query_filter: CadQueryFilter, repo: SourceRepository, *, force_refresh: bool = False
    ) -> CloseApproachResultSet:
        span_days = (query_filter.date_max - query_filter.date_min).days
        if span_days > self._max_span_days:
            raise ValidationError(
                f"close-approach date span exceeds maximum of {self._max_span_days} days"
            )
        limit = min(query_filter.limit, self._max_results)
        params: dict[str, str] = {
            "date-min": query_filter.date_min.strftime("%Y-%m-%d"),
            "date-max": query_filter.date_max.strftime("%Y-%m-%d"),
            "body": query_filter.body,
            "sort": "date",
            "limit": str(limit),
            "fullname": "true",
        }
        if query_filter.max_distance_au is not None:
            params["dist-max"] = str(query_filter.max_distance_au)
        if query_filter.near_earth_object_only:
            params["neo"] = "true"
        if query_filter.potentially_hazardous_only:
            params["pha"] = "true"

        cache_key = canonical_cache_key(self.source_id, params)
        fetch = self._fetcher.fetch(
            cache_key=cache_key,
            url=self._policy.base_url,
            params=params,
            repo=repo,
            force_refresh=force_refresh,
        )
        try:
            response = CadResponse.model_validate(json.loads(fetch.body))
        except (json.JSONDecodeError, UnicodeDecodeError, PydanticValidationError) as exc:
            raise SourceSchemaError(f"CAD response failed validation: {exc}") from exc

        source = JplSourceRecord(
            source_id=self.source_id,
            source_record_id="cad",
            requested_identifier=cache_key,
            signature_version=response.signature.version if response.signature else None,
            fetched_at=fetch.fetched_at,
            checksum=fetch.checksum,
            schema_version=self._policy.schema_version,
            policy_version=self._policy.policy_version,
        )
        records, total, truncated = normalize_cad(
            response,
            default_body=query_filter.body,
            source=source,
            freshness=jpl_freshness(self._policy, fetch),
            limit=limit,
        )
        return CloseApproachResultSet(
            records=records,
            total_reported=total,
            returned=len(records),
            truncated=truncated,
            source=source,
            freshness=jpl_freshness(self._policy, fetch),
        )
