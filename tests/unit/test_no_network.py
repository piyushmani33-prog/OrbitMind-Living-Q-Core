"""Guard test: a real outbound network request must fail in the test suite."""

from __future__ import annotations

import pytest

from orbitmind.sources.http_client import SafeHttpFetcher
from orbitmind.sources.policies import SourceCatalog


def test_real_network_is_blocked(celestrak_catalog: SourceCatalog) -> None:
    # transport=None uses the real httpx transport, which the autouse guard blocks.
    policy = celestrak_catalog.get("celestrak").policy
    fetcher = SafeHttpFetcher(policy, transport=None, sleep=lambda _: None)
    with pytest.raises(RuntimeError, match="real network access blocked"):
        fetcher.get("https://celestrak.org/x", {"CATNR": "25544"})
