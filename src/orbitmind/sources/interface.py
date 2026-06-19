"""Generic orbital-source interface (connectors implement this).

The orchestrator and API depend on this Protocol, never on a specific connector or
its response structures.
"""

from __future__ import annotations

from typing import Protocol

from orbitmind.persistence.source_repository import SourceRepository
from orbitmind.sources.models import (
    ElementFetchResult,
    SourceCacheRecord,
    SourceHealthStatus,
    SourcePolicy,
)


class OrbitalSource(Protocol):
    """A source of normalized orbital element records."""

    @property
    def source_id(self) -> str: ...

    def policy(self) -> SourcePolicy: ...

    def get_element_record(
        self,
        satellite_id: str,
        repo: SourceRepository,
        *,
        force_refresh: bool = False,
    ) -> ElementFetchResult:
        """Return a normalized element record (cache-first; refresh per policy)."""
        ...

    def read_cache(self, satellite_id: str, repo: SourceRepository) -> SourceCacheRecord | None: ...

    def health(self, repo: SourceRepository) -> SourceHealthStatus: ...
