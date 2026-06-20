"""JPL source definitions/policies (SBDB lookup, SBDB query, CAD).

JPL-specific values (conservative defaults; JPL publishes no hard polling cadence —
rate limits are marked "requires review"). Verified against JPL SSD/CNEOS API docs
on 2026-06-19. NASA/JPL data is generally public domain, but redistribution/
commercial terms and rate limits are NOT asserted here.
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

JPL_SBDB_SOURCE_ID = "jpl-sbdb"
JPL_SBDB_QUERY_SOURCE_ID = "jpl-sbdb-query"
JPL_CAD_SOURCE_ID = "jpl-cad"
JPL_DOC_REFERENCE = "JPL SSD/CNEOS API (ssd-api.jpl.nasa.gov); inspected 2026-06-19"


def _jpl_license() -> SourceLicenseRecord:
    return SourceLicenseRecord(
        license_name="NASA/JPL Solar System Dynamics — REQUIRES REVIEW",
        attribution_text="Data courtesy NASA/JPL Solar System Dynamics (https://ssd.jpl.nasa.gov).",
        usage_note=(
            "NASA/JPL data is generally U.S. Government work, but exact redistribution, "
            "commercial-use, and rate-limit terms are NOT confirmed in this repository and "
            "must be reviewed against official JPL/CNEOS terms before redistribution or "
            "commercial use. No commercial rights are claimed."
        ),
        requires_review=True,
        commercial_use_confirmed=False,
        reference_url="https://ssd-api.jpl.nasa.gov/doc/",
    )


def _jpl_policy(
    settings: Settings,
    *,
    source_id: str,
    official_name: str,
    base_url: str,
    data_category: str,
    schema_version: str,
    enabled: bool,
) -> SourcePolicy:
    host = urlsplit(base_url).hostname or "ssd-api.jpl.nasa.gov"
    license_record = _jpl_license()
    return SourcePolicy(
        source_id=source_id,
        official_name=official_name,
        base_url=base_url,
        data_category=data_category,
        attribution_text=license_record.attribution_text,
        license=license_record,
        min_refresh_seconds=settings.jpl_min_refresh_seconds,
        cache_ttl_seconds=settings.jpl_cache_ttl_seconds,
        # Small-body orbit solutions change slowly; classify by data age generously.
        freshness_current_seconds=24 * 3600,
        freshness_fresh_seconds=7 * 24 * 3600,
        freshness_aging_seconds=30 * 24 * 3600,
        freshness_stale_seconds=180 * 24 * 3600,
        connect_timeout_seconds=settings.jpl_connect_timeout_seconds,
        read_timeout_seconds=settings.jpl_read_timeout_seconds,
        max_retries=settings.jpl_max_retries,
        allowed_methods=("GET",),
        allowed_hostnames=(host,),
        https_only=True,
        follow_redirects=False,
        max_response_bytes=settings.jpl_max_response_bytes,
        allowed_content_types=("application/json",),
        schema_format=SchemaFormat.JSON,
        schema_version=schema_version,
        failure_behavior="fail-safe-no-fallback",
        network_enabled=settings.network_enabled and enabled,
        policy_version="1",
        documentation_reference=JPL_DOC_REFERENCE,
    )


def jpl_definitions(settings: Settings) -> list[SourceDefinition]:
    """The three JPL source definitions registered in the catalog."""
    sbdb_enabled = settings.jpl_sbdb_enabled
    cad_enabled = settings.jpl_cad_enabled
    return [
        SourceDefinition(
            source_id=JPL_SBDB_SOURCE_ID,
            name="JPL SBDB lookup",
            kind=SourceKind.JPL_SBDB,
            description="JPL Small-Body Database object lookup (asteroids/comets).",
            policy=_jpl_policy(
                settings,
                source_id=JPL_SBDB_SOURCE_ID,
                official_name="JPL Small-Body Database (SBDB) API",
                base_url=settings.jpl_sbdb_base_url,
                data_category="small-body-orbit",
                schema_version="sbdb-1",
                enabled=sbdb_enabled,
            ),
            enabled=sbdb_enabled,
        ),
        SourceDefinition(
            source_id=JPL_SBDB_QUERY_SOURCE_ID,
            name="JPL SBDB query",
            kind=SourceKind.JPL_SBDB_QUERY,
            description="JPL Small-Body Database constrained query service.",
            policy=_jpl_policy(
                settings,
                source_id=JPL_SBDB_QUERY_SOURCE_ID,
                official_name="JPL Small-Body Database Query API",
                base_url=settings.jpl_sbdb_query_base_url,
                data_category="small-body-query",
                schema_version="sbdb-query-1",
                enabled=sbdb_enabled,
            ),
            enabled=sbdb_enabled,
        ),
        SourceDefinition(
            source_id=JPL_CAD_SOURCE_ID,
            name="JPL Close-Approach Data",
            kind=SourceKind.JPL_CAD,
            description="JPL/CNEOS Close-Approach Data service.",
            policy=_jpl_policy(
                settings,
                source_id=JPL_CAD_SOURCE_ID,
                official_name="JPL/CNEOS Close-Approach Data (CAD) API",
                base_url=settings.jpl_cad_base_url,
                data_category="close-approach",
                schema_version="cad-1",
                enabled=cad_enabled,
            ),
            enabled=cad_enabled,
        ),
    ]
