"""Shared helpers for the JPL connectors (cache key, freshness)."""

from __future__ import annotations

from orbitmind.sources.fetching import CachedFetch
from orbitmind.sources.freshness import assess_external_freshness
from orbitmind.sources.models import (
    DataLiveness,
    FetchOutcome,
    SourceFreshnessAssessment,
    SourcePolicy,
)

_LIVENESS = {
    FetchOutcome.FETCHED: DataLiveness.LIVE,
    FetchOutcome.CACHED: DataLiveness.CACHED,
    FetchOutcome.SUPPRESSED: DataLiveness.CACHED,
}


def canonical_cache_key(source_id: str, params: dict[str, str]) -> str:
    """A deterministic cache key from canonicalized (sorted) query parameters."""
    encoded = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{source_id}:{encoded}"


def jpl_freshness(policy: SourcePolicy, fetch: CachedFetch) -> SourceFreshnessAssessment:
    """Freshness of JPL data, based on how recently it was fetched (data age)."""
    liveness = _LIVENESS.get(fetch.outcome, DataLiveness.CACHED)
    return assess_external_freshness(
        policy=policy,
        data_epoch=fetch.fetched_at,
        fetched_at=fetch.fetched_at,
        cache_status=fetch.cache_status,
        liveness=liveness,
        expires_at=fetch.expires_at,
    )
