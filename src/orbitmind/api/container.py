"""Application container: builds and wires services from settings.

Constructed once at startup and stored on ``app.state.container``. Centralizes
dependency wiring so routers depend on interfaces, not construction details.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import httpx

from orbitmind.core.config import Settings, get_settings
from orbitmind.observability.service import ObservabilityService
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.orchestration.source_resolver import SourceResolver
from orbitmind.persistence.database import Database
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.sources.cache import SourceCacheStore
from orbitmind.sources.celestrak.connector import CelestrakConnector
from orbitmind.sources.policies import CELESTRAK_SOURCE_ID, SourceCatalog
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.propagation import PropagationService
from orbitmind.verification.checks import VerificationService
from orbitmind.visualization.charts import VisualizationService


class AppContainer:
    """Owns long-lived services for the application lifetime."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        celestrak_transport: httpx.BaseTransport | None = None,
        celestrak_sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings or get_settings()
        self.database = Database(self.settings.database_url)
        self.registry = SourceRegistry()
        self.catalog = SourceCatalog(self.settings)
        self.cache_store = SourceCacheStore(self.settings.resolved_cache_dir())

        celestrak_def = self.catalog.get(CELESTRAK_SOURCE_ID)
        self.celestrak: CelestrakConnector | None = (
            CelestrakConnector(
                celestrak_def,
                self.cache_store,
                transport=celestrak_transport,
                sleep=celestrak_sleep,
            )
            if celestrak_def is not None
            else None
        )
        self.resolver = SourceResolver(self.registry, self.catalog, self.celestrak)

        self.observability = ObservabilityService(self.settings, self.database)
        self.orchestrator = PrimeOrchestrator(
            settings=self.settings,
            database=self.database,
            registry=self.registry,
            propagation=PropagationService(),
            verification=VerificationService(),
            visualization=VisualizationService(self.settings.resolved_artifacts_dir()),
            resolver=self.resolver,
        )

    def init_storage(self) -> None:
        """Ensure the schema exists and the source catalog is recorded (local/dev)."""
        self.database.create_all()
        with self.database.session() as session:
            source_repo = SqlAlchemySourceRepository(session)
            for definition in self.catalog.list():
                source_repo.sync_definition(definition)
            session.commit()
