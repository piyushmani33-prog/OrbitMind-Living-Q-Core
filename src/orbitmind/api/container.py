"""Application container: builds and wires services from settings.

Constructed once at startup and stored on ``app.state.container``. Centralizes
dependency wiring so routers depend on interfaces, not construction details.
"""

from __future__ import annotations

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

_MIN_SIGNING_KEY_BYTES = 32
# Non-empty placeholders that must be REJECTED (an empty key is the legitimate no-signer mode).
_PLACEHOLDER_KEYS = frozenset(
    {"changeme", "change-me", "placeholder", "secret", "your-key-here", "example"}
)


def _validate_signing_secret(secret: str) -> bytes:
    """Validate + decode a configured signing secret (fourth review, High #3). Rejects known
    placeholders and weak keys (< 32 bytes UTF-8). Errors never echo the secret. Callers must
    invoke this only for a NON-empty secret (an empty key = legitimate no-signer mode)."""
    if secret.strip().lower() in _PLACEHOLDER_KEYS:
        raise ValueError("evidence signing key is a known placeholder; refusing to use it")
    material = secret.encode("utf-8")
    if len(material) < _MIN_SIGNING_KEY_BYTES:
        raise ValueError(f"evidence signing key too short: needs >= {_MIN_SIGNING_KEY_BYTES} bytes")
    return material


def _build_evidence_signers(
    settings: Settings,
) -> tuple[EvidenceReceiptSigner | None, dict[str, EvidenceReceiptSigner]]:
    """Build the active receipt signer + the verification keyring (incl. retired verify-only
    keys) from configuration ONLY (never the DB; fourth review, High #3). There is NO implicit
    test-environment signer — tests inject a signer explicitly. With no configured key the active
    signer is None and accepted quantum evidence is impossible (diagnostic, unaccepted mode).
    Active and retired key ids must be distinct; key material is never logged.
    """
    signers: dict[str, EvidenceReceiptSigner] = {}
    seen_material: set[bytes] = set()
    # Malformed retired-key entries FAIL STARTUP — they are never silently skipped (fifth review,
    # Low #2). Only purely blank segments (e.g. a trailing comma) are tolerated.
    for raw_entry in settings.evidence_signing_retired_keys.get_secret_value().split(","):
        entry = raw_entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            raise ValueError("malformed retired signing key entry (expected 'key-id:secret')")
        kid, _, sec = entry.partition(":")
        kid, sec = kid.strip(), sec.strip()
        if not kid:
            raise ValueError("retired signing key entry has a blank key id")
        if not sec:
            raise ValueError("retired signing key entry has a blank secret")
        material = _validate_signing_secret(sec)  # rejects placeholder/weak material
        if kid in signers:
            raise ValueError("duplicate evidence signing key id")
        if material in seen_material:
            raise ValueError("duplicate evidence signing key material")
        signers[kid] = HmacSha256EvidenceReceiptSigner(material, kid)
        seen_material.add(material)
    active: EvidenceReceiptSigner | None = None
    raw_active = settings.evidence_signing_key.get_secret_value()
    if raw_active.strip():  # empty = legitimate no-signer mode; non-empty is fully validated
        kid = settings.evidence_signing_key_id.strip()
        if not kid:
            raise ValueError("an active signing key is configured but its key id is blank")
        material = _validate_signing_secret(raw_active)
        if kid in signers:
            raise ValueError("active signing key id duplicates a retired key id")
        if material in seen_material:
            raise ValueError("active signing key material duplicates a retired key")
        active = HmacSha256EvidenceReceiptSigner(material, kid)
        signers[kid] = active
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
