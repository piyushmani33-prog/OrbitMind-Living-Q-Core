"""Application container: builds and wires services from settings.

Constructed once at startup and stored on ``app.state.container``. Centralizes
dependency wiring so routers depend on interfaces, not construction details.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from orbitmind.api.transient_handoff import CustomTleTransientHandoffStore
from orbitmind.camera.csrf import (
    CAMERA_CSRF_POLICY,
    CameraPageCsrfRegistry,
    CameraPageSessionUnavailableError,
)
from orbitmind.camera.media import CameraMediaError
from orbitmind.camera.runtime import CameraMediaRuntimeContext
from orbitmind.camera.service import CameraMediaService, CameraMediaShutdownReport
from orbitmind.core.config import Settings, get_settings
from orbitmind.core.page_csrf import (
    AUTHORITY_WORKBENCH_CSRF_POLICY,
    PAGE_CSRF_OPAQUE_SECRET_BYTES,
    PageCsrfRegistry,
)
from orbitmind.laboratory.catalog import build_default_registry
from orbitmind.memory.service import MemoryService
from orbitmind.mission_windows.service import MissionWindowService
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
from orbitmind.trajectory_replay.service import TrajectoryReplayService
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
    """Owns long-lived services with explicit application-lifespan ownership."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        celestrak_transport: httpx.BaseTransport | None = None,
        celestrak_sleep: Callable[[float], None] = time.sleep,
        jpl_transport: httpx.BaseTransport | None = None,
        jpl_sleep: Callable[[float], None] = time.sleep,
        custom_tle_handoff_store: CustomTleTransientHandoffStore | None = None,
        camera_runtime_context: CameraMediaRuntimeContext | None = None,
        caller_owns_lifecycle: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.caller_owns_lifecycle = caller_owns_lifecycle
        self.camera_runtime_context = camera_runtime_context
        page_csrf_clock = (
            camera_runtime_context.utcnow if camera_runtime_context is not None else _utc_now
        )
        page_session_id_generator = (
            camera_runtime_context.page_session_id_generator
            if camera_runtime_context is not None
            else lambda: secrets.token_bytes(PAGE_CSRF_OPAQUE_SECRET_BYTES)
        )
        csrf_token_generator = (
            camera_runtime_context.csrf_token_generator
            if camera_runtime_context is not None
            else lambda: secrets.token_bytes(PAGE_CSRF_OPAQUE_SECRET_BYTES)
        )
        process_binding_key = (
            camera_runtime_context.process_binding_key
            if camera_runtime_context is not None
            else secrets.token_bytes(PAGE_CSRF_OPAQUE_SECRET_BYTES)
        )
        self.page_csrf_registry = PageCsrfRegistry(
            clock=page_csrf_clock,
            page_session_id_generator=page_session_id_generator,
            csrf_token_generator=csrf_token_generator,
            process_binding_key=process_binding_key,
            policies=(CAMERA_CSRF_POLICY, AUTHORITY_WORKBENCH_CSRF_POLICY),
        )
        self.camera_page_csrf_registry = (
            CameraPageCsrfRegistry(shared_registry=self.page_csrf_registry)
            if camera_runtime_context is not None
            else None
        )
        self.camera_media_service = (
            CameraMediaService(camera_runtime_context)
            if camera_runtime_context is not None
            else None
        )
        self.camera_media_shutdown_report: CameraMediaShutdownReport | None = None
        if custom_tle_handoff_store is not None and not self.settings.custom_tle_handoff_enabled:
            raise ValueError("custom-TLE handoff store requires explicit feature enablement")
        self.custom_tle_handoff_store = (
            custom_tle_handoff_store or CustomTleTransientHandoffStore()
            if self.settings.custom_tle_handoff_enabled
            else None
        )
        self.database = Database(
            self.settings.database_url,
            recycle_seconds=self.settings.database_pool_recycle_seconds,
        )
        # U6: deterministic, non-executing laboratory catalog (explicit registration).
        self.laboratory_registry = build_default_registry()
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
        self.mission_window_service = MissionWindowService()
        self.trajectory_replay_service = TrajectoryReplayService()

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
        """Ensure local schema exists and the source catalog is recorded."""
        if not self.database.is_postgres:
            self.database.create_all()
        with self.database.session() as session:
            source_repo = SqlAlchemySourceRepository(session)
            for definition in self.catalog.list():
                source_repo.sync_definition(definition)
            session.commit()
        if self.camera_media_service is not None:
            self.camera_media_service.start()

    def require_camera_page_csrf_registry(self) -> CameraPageCsrfRegistry:
        """Return this application's camera CSRF authority or fail closed."""

        if self.camera_page_csrf_registry is None:
            raise CameraPageSessionUnavailableError
        return self.camera_page_csrf_registry

    def require_page_csrf_registry(self) -> PageCsrfRegistry:
        """Return the shared local page-CSRF registry."""

        return self.page_csrf_registry

    def require_camera_media_service(self) -> CameraMediaService:
        """Return this application's media service or fail without a path fallback."""

        if self.camera_media_service is None:
            raise CameraMediaError("camera_invalid_state", 409)
        return self.camera_media_service

    def shutdown(self) -> None:
        """Release process-local sensitive state and database resources."""

        if self.camera_media_service is not None:
            self.camera_media_shutdown_report = self.camera_media_service.close()
        if self.camera_page_csrf_registry is not None:
            self.camera_page_csrf_registry.close()
        else:
            self.page_csrf_registry.close()
        if self.custom_tle_handoff_store is not None:
            self.custom_tle_handoff_store.clear()
        self.database.dispose()


def _utc_now() -> datetime:
    """Timezone-aware UTC clock for the authority CSRF registry."""

    return datetime.now(UTC)
