"""Application container: builds and wires services from settings.

Constructed once at startup and stored on ``app.state.container``. Centralizes
dependency wiring so routers depend on interfaces, not construction details.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable

import httpx

from orbitmind.core.config import Settings, get_settings
from orbitmind.memory.service import MemoryService
from orbitmind.observability.service import ObservabilityService
from orbitmind.optimization.receipts import (
    EvidenceReceiptSigner,
    HmacSha256EvidenceReceiptSigner,
)
from orbitmind.optimization.service import OptimizationService
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.orchestration.source_resolver import SourceResolver
from orbitmind.persistence.database import Database
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.smallbody.service import SmallBodyService
from orbitmind.smallbody.verification import SmallBodyVerificationService
from orbitmind.sources.cache import SourceCacheStore
from orbitmind.sources.celestrak.connector import CelestrakConnector
from orbitmind.sources.jpl.cad_connector import CadConnector
from orbitmind.sources.jpl.policies import (
    JPL_CAD_SOURCE_ID,
    JPL_SBDB_QUERY_SOURCE_ID,
    JPL_SBDB_SOURCE_ID,
)
from orbitmind.sources.jpl.query_connector import SbdbQueryConnector
from orbitmind.sources.jpl.sbdb_connector import SbdbConnector
from orbitmind.sources.policies import CELESTRAK_SOURCE_ID, SourceCatalog
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.propagation import PropagationService
from orbitmind.verification.checks import VerificationService
from orbitmind.visualization.charts import VisualizationService
from orbitmind.visualization.smallbody_charts import SmallBodyVisualizationService


def _build_evidence_signers(
    settings: Settings,
) -> tuple[EvidenceReceiptSigner | None, dict[str, EvidenceReceiptSigner]]:
    """Build the active receipt signer + the verification keyring (incl. retired keys).

    The secret comes ONLY from configuration/env (never the DB). When no key is configured the
    active signer is None UNLESS this is a test environment, where an ephemeral process-local key
    is used so the receipt path is exercised end-to-end. In non-test environments without a key,
    quantum evidence runs diagnostically but is never accepted (provenance unavailable).
    """
    signers: dict[str, EvidenceReceiptSigner] = {}
    for entry in settings.evidence_signing_retired_keys.split(","):
        if ":" in entry:
            kid, _, sec = entry.partition(":")
            kid, sec = kid.strip(), sec.strip()
            if kid and sec:
                signers[kid] = HmacSha256EvidenceReceiptSigner(sec.encode("utf-8"), kid)
    active: EvidenceReceiptSigner | None = None
    if settings.evidence_signing_key:
        active = HmacSha256EvidenceReceiptSigner(
            settings.evidence_signing_key.encode("utf-8"), settings.evidence_signing_key_id
        )
    elif settings.env == "test":
        active = HmacSha256EvidenceReceiptSigner(secrets.token_bytes(32), "ephemeral-test")
    if active is not None:
        signers[active.key_id] = active
    return active, signers


class AppContainer:
    """Owns long-lived services for the application lifetime."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        celestrak_transport: httpx.BaseTransport | None = None,
        celestrak_sleep: Callable[[float], None] = time.sleep,
        jpl_transport: httpx.BaseTransport | None = None,
        jpl_sleep: Callable[[float], None] = time.sleep,
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

        # --- Phase 3A: JPL small-body connectors + service ---
        sbdb = SbdbConnector(
            self.catalog.require(JPL_SBDB_SOURCE_ID),
            self.cache_store,
            transport=jpl_transport,
            sleep=jpl_sleep,
        )
        query = SbdbQueryConnector(
            self.catalog.require(JPL_SBDB_QUERY_SOURCE_ID),
            self.cache_store,
            max_results=self.settings.jpl_max_results,
            transport=jpl_transport,
            sleep=jpl_sleep,
        )
        cad = CadConnector(
            self.catalog.require(JPL_CAD_SOURCE_ID),
            self.cache_store,
            max_results=self.settings.jpl_max_results,
            max_query_span_days=self.settings.jpl_max_query_span_days,
            transport=jpl_transport,
            sleep=jpl_sleep,
        )
        self.small_body_service = SmallBodyService(
            settings=self.settings,
            database=self.database,
            sbdb=sbdb,
            query=query,
            cad=cad,
            verification=SmallBodyVerificationService(),
            visualization=SmallBodyVisualizationService(self.settings.resolved_artifacts_dir()),
        )

        # --- Phase 3B: scientific memory service ---
        self.memory_service = MemoryService(settings=self.settings, database=self.database)

        # --- Phase 4A: bounded quantum optimization service ---
        signer, signers = _build_evidence_signers(self.settings)
        self.optimization_service = OptimizationService(
            settings=self.settings,
            database=self.database,
            receipt_signer=signer,
            receipt_signers=signers,
        )

    def init_storage(self) -> None:
        """Ensure the schema exists and the source catalog is recorded (local/dev)."""
        self.database.create_all()
        with self.database.session() as session:
            source_repo = SqlAlchemySourceRepository(session)
            for definition in self.catalog.list():
                source_repo.sync_definition(definition)
            session.commit()
