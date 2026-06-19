"""Unit tests for freshness classification (ADR-0010)."""

from __future__ import annotations

import datetime as dt

from orbitmind.sources.freshness import assess_external_freshness, fixture_freshness
from orbitmind.sources.models import CacheStatus, DataLiveness, FreshnessState
from orbitmind.sources.policies import SourceCatalog

NOW = dt.datetime(2026, 6, 19, 12, 0, 0, tzinfo=dt.UTC)


def _assess(catalog: SourceCatalog, age_seconds: float, liveness: DataLiveness):
    policy = catalog.get("celestrak").policy
    return assess_external_freshness(
        policy=policy,
        data_epoch=NOW - dt.timedelta(seconds=age_seconds),
        fetched_at=NOW,
        cache_status=CacheStatus.HIT,
        liveness=liveness,
        expires_at=NOW + dt.timedelta(hours=2),
        now=NOW,
    )


def test_fixture_state() -> None:
    f = fixture_freshness()
    assert f.state is FreshnessState.TEST_FIXTURE
    assert f.liveness is DataLiveness.FIXTURE


def test_current_and_fresh(celestrak_catalog: SourceCatalog) -> None:
    assert _assess(celestrak_catalog, 3600, DataLiveness.LIVE).state is FreshnessState.CURRENT
    assert _assess(celestrak_catalog, 18 * 3600, DataLiveness.LIVE).state is FreshnessState.FRESH


def test_aging_stale_expired(celestrak_catalog: SourceCatalog) -> None:
    assert _assess(celestrak_catalog, 2 * 86400, DataLiveness.CACHED).state is FreshnessState.AGING
    assert _assess(celestrak_catalog, 5 * 86400, DataLiveness.CACHED).state is FreshnessState.STALE
    assert (
        _assess(celestrak_catalog, 30 * 86400, DataLiveness.CACHED).state is FreshnessState.EXPIRED
    )


def test_stale_data_is_never_reported_live(celestrak_catalog: SourceCatalog) -> None:
    # Even if the fetch was "live", stale data must not be labelled live.
    stale = _assess(celestrak_catalog, 5 * 86400, DataLiveness.LIVE)
    assert stale.state is FreshnessState.STALE
    assert stale.liveness is DataLiveness.STALE
    expired = _assess(celestrak_catalog, 30 * 86400, DataLiveness.LIVE)
    assert expired.liveness is DataLiveness.EXPIRED
