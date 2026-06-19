"""Application container: builds and wires services from settings.

Constructed once at startup and stored on ``app.state.container``. Centralizes
dependency wiring so routers depend on interfaces, not construction details.
"""

from __future__ import annotations

from orbitmind.core.config import Settings, get_settings
from orbitmind.observability.service import ObservabilityService
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.persistence.database import Database
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.propagation import PropagationService
from orbitmind.verification.checks import VerificationService
from orbitmind.visualization.charts import VisualizationService


class AppContainer:
    """Owns long-lived services for the application lifetime."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.database = Database(self.settings.database_url)
        self.registry = SourceRegistry()
        self.observability = ObservabilityService(self.settings, self.database)
        self.orchestrator = PrimeOrchestrator(
            settings=self.settings,
            database=self.database,
            registry=self.registry,
            propagation=PropagationService(),
            verification=VerificationService(),
            visualization=VisualizationService(self.settings.resolved_artifacts_dir()),
        )

    def init_storage(self) -> None:
        """Ensure the schema exists (local/dev convenience; Alembic is canonical)."""
        self.database.create_all()
