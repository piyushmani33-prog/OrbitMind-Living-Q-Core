"""Freshness classification for orbital data (ADR-0010).

Freshness is computed from the source policy thresholds, the data epoch, the fetch
timestamp, and cache state. Stale/expired data is NEVER described as live.
"""

from __future__ import annotations

from datetime import datetime

from orbitmind.core.timeutils import utcnow
from orbitmind.sources.models import (
    CacheStatus,
    DataLiveness,
    FreshnessState,
    SourceFreshnessAssessment,
    SourcePolicy,
)


def assess_external_freshness(
    *,
    policy: SourcePolicy,
    data_epoch: datetime,
    fetched_at: datetime | None,
    cache_status: CacheStatus,
    liveness: DataLiveness,
    expires_at: datetime | None,
    now: datetime | None = None,
) -> SourceFreshnessAssessment:
    """Classify external orbital data by the age of its element-set epoch."""
    current = now or utcnow()
    age = (current - data_epoch).total_seconds()
    if age <= policy.freshness_current_seconds:
        state = FreshnessState.CURRENT
    elif age <= policy.freshness_fresh_seconds:
        state = FreshnessState.FRESH
    elif age <= policy.freshness_aging_seconds:
        state = FreshnessState.AGING
    elif age <= policy.freshness_stale_seconds:
        state = FreshnessState.STALE
    else:
        state = FreshnessState.EXPIRED

    # A live/cached liveness label must not survive once the data itself is stale.
    effective_liveness = liveness
    if state in (FreshnessState.STALE, FreshnessState.EXPIRED) and liveness in (
        DataLiveness.LIVE,
        DataLiveness.CACHED,
    ):
        effective_liveness = (
            DataLiveness.STALE if state is FreshnessState.STALE else DataLiveness.EXPIRED
        )

    return SourceFreshnessAssessment(
        state=state,
        liveness=effective_liveness,
        cache_status=cache_status,
        data_epoch=data_epoch,
        fetched_at=fetched_at,
        age_seconds=age,
        expires_at=expires_at,
        explanation=(
            f"data-epoch age {age / 3600:.1f}h; cache={cache_status.value}; "
            f"liveness={effective_liveness.value}"
        ),
    )


def fixture_freshness() -> SourceFreshnessAssessment:
    """Freshness for bundled sample data (always test-fixture, never live)."""
    return SourceFreshnessAssessment(
        state=FreshnessState.TEST_FIXTURE,
        liveness=DataLiveness.FIXTURE,
        cache_status=CacheStatus.BYPASSED,
        explanation="bundled offline sample fixture; NOT live data",
    )
