"""Source catalog: registered source definitions and their policies.

The effective network switch for a source is ``global network_enabled AND the
source-specific switch`` (ADR-0009). The CelesTrak endpoint is configurable (not
hard-coded) and its hostname allowlist is derived from the configured base URL.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from orbitmind.core.config import Settings
from orbitmind.sources.models import (
    SchemaFormat,
    SourceDefinition,
    SourceKind,
    SourceLicenseRecord,
    SourcePolicy,
)

CELESTRAK_SOURCE_ID = "celestrak"
SAMPLE_SOURCE_ID = "sample"


def _celestrak_definition(settings: Settings) -> SourceDefinition:
    host = urlsplit(settings.celestrak_base_url).hostname or "celestrak.org"
    effective_network = settings.network_enabled and settings.celestrak_enabled

    license_record = SourceLicenseRecord(
        license_name="CelesTrak usage terms (see celestrak.org) — REQUIRES REVIEW",
        attribution_text="Orbital data courtesy of CelesTrak (https://celestrak.org).",
        usage_note=(
            "Attribution to CelesTrak is required. The exact licensing/redistribution "
            "and commercial-use terms are NOT confirmed in this repository and MUST be "
            "reviewed against the official CelesTrak terms before any redistribution or "
            "commercial use. No commercial rights are claimed here."
        ),
        requires_review=True,
        commercial_use_confirmed=False,
        reference_url="https://celestrak.org",
    )

    policy = SourcePolicy(
        source_id=CELESTRAK_SOURCE_ID,
        official_name="CelesTrak General Perturbations (GP)",
        base_url=settings.celestrak_base_url,
        data_category="orbital-elements-gp",
        attribution_text=license_record.attribution_text,
        license=license_record,
        min_refresh_seconds=settings.celestrak_min_refresh_seconds,
        cache_ttl_seconds=settings.celestrak_cache_ttl_seconds,
        connect_timeout_seconds=settings.celestrak_connect_timeout_seconds,
        read_timeout_seconds=settings.celestrak_read_timeout_seconds,
        max_retries=settings.celestrak_max_retries,
        allowed_methods=("GET",),
        allowed_hostnames=(host,),
        https_only=True,
        follow_redirects=False,
        max_response_bytes=settings.celestrak_max_response_bytes,
        allowed_content_types=("application/json",),
        schema_format=SchemaFormat.JSON_OMM,
        schema_version="omm-1",
        failure_behavior="fail-safe-no-fallback",
        network_enabled=effective_network,
        policy_version="1",
    )
    return SourceDefinition(
        source_id=CELESTRAK_SOURCE_ID,
        name="CelesTrak GP",
        kind=SourceKind.CELESTRAK,
        description="CelesTrak General Perturbations orbital elements (OMM/GP JSON).",
        policy=policy,
        enabled=settings.celestrak_enabled,
    )


def _sample_definition() -> SourceDefinition:
    license_record = SourceLicenseRecord(
        license_name="Bundled test-only fixture",
        attribution_text="python-sgp4 reference example TLE (offline copy).",
        usage_note="Stale sample data for demonstration/tests only; NOT live data.",
        requires_review=False,
        commercial_use_confirmed=False,
    )
    policy = SourcePolicy(
        source_id=SAMPLE_SOURCE_ID,
        official_name="Bundled sample TLE fixtures",
        base_url="(offline fixture)",
        data_category="orbital-elements-tle",
        attribution_text=license_record.attribution_text,
        license=license_record,
        min_refresh_seconds=0,
        cache_ttl_seconds=0,
        allowed_hostnames=(),
        https_only=True,
        schema_format=SchemaFormat.TLE,
        schema_version="tle-3line",
        failure_behavior="fail-safe-no-fallback",
        network_enabled=False,
        policy_version="1",
    )
    return SourceDefinition(
        source_id=SAMPLE_SOURCE_ID,
        name="Bundled sample",
        kind=SourceKind.SAMPLE,
        description="Bundled, deterministic, offline sample TLE fixtures (Phase 1).",
        policy=policy,
        enabled=True,
    )


class SourceCatalog:
    """Registry of source definitions, built from settings."""

    def __init__(self, settings: Settings) -> None:
        self._defs: dict[str, SourceDefinition] = {
            SAMPLE_SOURCE_ID: _sample_definition(),
            CELESTRAK_SOURCE_ID: _celestrak_definition(settings),
        }

    def get(self, source_id: str) -> SourceDefinition | None:
        return self._defs.get(source_id)

    def list(self) -> list[SourceDefinition]:
        return list(self._defs.values())
