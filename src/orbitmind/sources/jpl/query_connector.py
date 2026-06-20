"""JPL SBDB constrained-query connector (allowlisted, bounded, deterministic sort)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable

import httpx
from pydantic import ValidationError as PydanticValidationError

from orbitmind.persistence.source_repository import SourceRepository
from orbitmind.smallbody.models import JplSourceRecord
from orbitmind.smallbody.query import (
    SbdbQueryFilter,
    SmallBodyKindFilter,
    SmallBodyQueryItem,
    SmallBodyQueryResultSet,
)
from orbitmind.sources.cache import KeyedLock, SourceCacheStore
from orbitmind.sources.errors import SourceSchemaError
from orbitmind.sources.fetching import CachedSourceFetcher
from orbitmind.sources.jpl.common import canonical_cache_key, jpl_freshness
from orbitmind.sources.jpl.normalization import normalize_query
from orbitmind.sources.jpl.query_models import SbdbQueryResponse
from orbitmind.sources.models import SourceDefinition, SourcePolicy

_SORT_ATTR = {
    "full_name": "full_name",
    "pdes": "designation",
    "a": "semimajor_axis_au",
    "e": "eccentricity",
    "i": "inclination_deg",
    "q": "perihelion_distance_au",
    "H": "absolute_magnitude_h",
    "diameter": "diameter_km",
    "moid": "moid_au",
}


def _sort_key(field: str) -> Callable[[SmallBodyQueryItem], tuple[bool, object]]:
    attr = _SORT_ATTR[field]

    def key(item: SmallBodyQueryItem) -> tuple[bool, object]:
        value = getattr(item, attr)
        # None sorts last; otherwise sort by (str|float) value.
        return (value is None, "" if value is None else value)

    return key


class SbdbQueryConnector:
    """Guarded constrained SBDB query."""

    def __init__(
        self,
        definition: SourceDefinition,
        cache_store: SourceCacheStore,
        *,
        max_results: int = 200,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        lock: KeyedLock | None = None,
    ) -> None:
        self._def = definition
        self._policy = definition.policy
        self._max_results = max_results
        self._fetcher = CachedSourceFetcher(
            self._policy, cache_store, transport=transport, sleep=sleep, lock=lock
        )

    @property
    def source_id(self) -> str:
        return self._def.source_id

    def policy(self) -> SourcePolicy:
        return self._policy

    def query(
        self, query_filter: SbdbQueryFilter, repo: SourceRepository, *, force_refresh: bool = False
    ) -> SmallBodyQueryResultSet:
        fields = sorted({*query_filter.output_fields, query_filter.sort_field})
        fetch_limit = min(query_filter.offset + query_filter.limit, self._max_results)
        params: dict[str, str] = {"fields": ",".join(fields), "limit": str(fetch_limit)}
        if query_filter.object_kind is SmallBodyKindFilter.ASTEROID:
            params["sb-kind"] = "a"
        elif query_filter.object_kind is SmallBodyKindFilter.COMET:
            params["sb-kind"] = "c"
        if query_filter.orbit_class is not None:
            params["sb-class"] = query_filter.orbit_class
        if query_filter.potentially_hazardous:
            params["sb-group"] = "pha"
        elif query_filter.near_earth_object:
            params["sb-group"] = "neo"

        cache_key = canonical_cache_key(self.source_id, params)
        fetch = self._fetcher.fetch(
            cache_key=cache_key,
            url=self._policy.base_url,
            params=params,
            repo=repo,
            force_refresh=force_refresh,
        )
        try:
            response = SbdbQueryResponse.model_validate(json.loads(fetch.body))
        except (json.JSONDecodeError, UnicodeDecodeError, PydanticValidationError) as exc:
            raise SourceSchemaError(f"SBDB query response failed validation: {exc}") from exc

        items, total, _ = normalize_query(response, limit=fetch_limit)
        items.sort(key=_sort_key(query_filter.sort_field))
        page = items[query_filter.offset : query_filter.offset + query_filter.limit]
        truncated = total > len(items) or len(items) > len(page)
        return SmallBodyQueryResultSet(
            items=page,
            total_reported=total,
            returned=len(page),
            truncated=truncated,
            limit=query_filter.limit,
            offset=query_filter.offset,
            source=JplSourceRecord(
                source_id=self.source_id,
                source_record_id="sbdb-query",
                requested_identifier=cache_key,
                signature_version=response.signature.version if response.signature else None,
                fetched_at=fetch.fetched_at,
                checksum=fetch.checksum,
                schema_version=self._policy.schema_version,
                policy_version=self._policy.policy_version,
            ),
            freshness=jpl_freshness(self._policy, fetch),
        )
