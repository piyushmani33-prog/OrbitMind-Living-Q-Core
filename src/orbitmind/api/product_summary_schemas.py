"""API wire schemas for static product summary read surfaces."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orbitmind.core.timeutils import utcnow

PRODUCT_SUMMARY_SCHEMA_VERSION: Literal["product-summary-v1"] = "product-summary-v1"
READ_PRODUCT_CATALOG_SUMMARY_TYPE: Literal["read-product-catalog"] = "read-product-catalog"
READ_PRODUCT_CATALOG_SCOPE_ID: Literal["orbitmind-read-products"] = "orbitmind-read-products"

PRODUCT_SUMMARY_DISCLAIMER = (
    "This read-product catalog is a static capability declaration. It is not "
    "evidence, not proof, not a data summary, not dashboard UI, not a readiness "
    "assessment, and not a quality assessment."
)

PRODUCT_SUMMARY_LIMITATIONS: tuple[str, ...] = (
    "Surface A is a static global catalog of reviewed read-product capabilities.",
    "Surface A reads no persisted domain data, owner-scoped data, API responses, "
    "or read-product payloads.",
    "Surface B per-scope composition remains deferred and requires a separate reviewed contract.",
    "The observation-study visual manifest remains deferred; this catalog lists "
    "it but does not consume its envelope, satisfy its final gate, or authorize "
    "implementation.",
    "The catalog contains no scores, ranks, rollups, data-derived aggregates, or "
    "synthesized authority.",
)


class ImplementedReadProductEntry(BaseModel):
    """One implemented read product in the static catalog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    status: Literal["implemented"]
    route: str
    schema_version: str
    source_domain: str


class DeferredReadProductEntry(BaseModel):
    """One deferred read product or read-surface capability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    status: Literal["deferred"]
    route: str | None = None
    contract_reference: str | None = None
    note: str


class UnsupportedReadProductEntry(BaseModel):
    """One unsupported capability family for this static catalog."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    status: Literal["unsupported"]
    note: str


class ProductSummaryReadProductsResponse(BaseModel):
    """Static Surface A catalog for implemented and deferred read products.

    The projection is intentionally built from static reviewed capability
    declarations only. It performs no I/O, no domain reads, no API self-calls,
    no rendering, no provider calls, and no mutation.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["product-summary-v1"]
    summary_type: Literal["read-product-catalog"]
    scope_id: Literal["orbitmind-read-products"]
    read_at: datetime
    implemented_read_products: tuple[ImplementedReadProductEntry, ...]
    deferred_read_products: tuple[DeferredReadProductEntry, ...]
    unsupported_read_products: tuple[UnsupportedReadProductEntry, ...]
    limitations: tuple[str, ...]
    disclaimer: str

    @classmethod
    def from_static_catalog(
        cls, *, read_at: datetime | None = None
    ) -> ProductSummaryReadProductsResponse:
        """Build the catalog from static declarations only."""

        return cls(
            schema_version=PRODUCT_SUMMARY_SCHEMA_VERSION,
            summary_type=READ_PRODUCT_CATALOG_SUMMARY_TYPE,
            scope_id=READ_PRODUCT_CATALOG_SCOPE_ID,
            read_at=read_at or utcnow(),
            implemented_read_products=_IMPLEMENTED_READ_PRODUCTS,
            deferred_read_products=_DEFERRED_READ_PRODUCTS,
            unsupported_read_products=_UNSUPPORTED_READ_PRODUCTS,
            limitations=PRODUCT_SUMMARY_LIMITATIONS,
            disclaimer=PRODUCT_SUMMARY_DISCLAIMER,
        )


_IMPLEMENTED_READ_PRODUCTS: tuple[ImplementedReadProductEntry, ...] = (
    ImplementedReadProductEntry(
        name="Mission visual manifest API",
        status="implemented",
        route="GET /api/v1/visual-manifests/mission/{mission_id}",
        schema_version="visual-manifest-v1",
        source_domain="mission",
    ),
    ImplementedReadProductEntry(
        name="Optimization-benchmark visual manifest API",
        status="implemented",
        route="GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}",
        schema_version="visual-manifest-v1",
        source_domain="optimization-benchmark",
    ),
    ImplementedReadProductEntry(
        name="Mission Static Report v1",
        status="implemented",
        route="GET /api/v1/static-reports/mission/{mission_id}",
        schema_version="static-report-v1",
        source_domain="mission",
    ),
    ImplementedReadProductEntry(
        name="Optimization Benchmark Static Report v1",
        status="implemented",
        route="GET /api/v1/static-reports/optimization-benchmark/{benchmark_id}",
        schema_version="static-report-v1",
        source_domain="optimization-benchmark",
    ),
    ImplementedReadProductEntry(
        name="Observation-study Provenance Graph API v1",
        status="implemented",
        route="GET /api/v1/provenance-graphs/observation-study/geometry-planning-chain",
        schema_version="provenance-graph-v1",
        source_domain="observation-study",
    ),
    ImplementedReadProductEntry(
        name="Mission Map/Orbit Context v1",
        status="implemented",
        route="GET /api/v1/map-orbit-contexts/mission/{mission_id}",
        schema_version="map-orbit-context-v1",
        source_domain="mission",
    ),
)

_DEFERRED_READ_PRODUCTS: tuple[DeferredReadProductEntry, ...] = (
    DeferredReadProductEntry(
        name="Observation-study visual manifest",
        status="deferred",
        route=(
            "GET /api/v1/visual-manifests/observation-study/{geometry_run_id}/{provenance_link_id}"
        ),
        contract_reference="OBSERVATION_STUDY_VISUAL_MANIFEST_CONTRACT.md",
        note=(
            "Listed only; not authorized; final gate not satisfied. A later "
            "Surface B per-scope composition contract is required for genuine "
            "envelope-consumer need."
        ),
    ),
    DeferredReadProductEntry(
        name="Surface B per-scope composition",
        status="deferred",
        route=None,
        contract_reference=None,
        note="Requires a separate reviewed contract.",
    ),
    DeferredReadProductEntry(
        name="Dashboard UI",
        status="deferred",
        route=None,
        contract_reference="DASHBOARD_VIEW_SPECIFICATION.md",
        note="JSON catalog only; no UI.",
    ),
)

_UNSUPPORTED_READ_PRODUCTS: tuple[UnsupportedReadProductEntry, ...] = (
    UnsupportedReadProductEntry(
        name="rendering",
        status="unsupported",
        note="No rendering implementation is authorized by Surface A.",
    ),
    UnsupportedReadProductEntry(
        name="frontend",
        status="unsupported",
        note="No frontend implementation is authorized by Surface A.",
    ),
    UnsupportedReadProductEntry(
        name="provider-live-data",
        status="unsupported",
        note="No provider/live-data behavior is authorized by Surface A.",
    ),
    UnsupportedReadProductEntry(
        name="exports-pdf",
        status="unsupported",
        note="No export or PDF behavior is authorized by Surface A.",
    ),
    UnsupportedReadProductEntry(
        name="graph-drawing",
        status="unsupported",
        note="No graph drawing is authorized by Surface A.",
    ),
    UnsupportedReadProductEntry(
        name="map-drawing",
        status="unsupported",
        note="No map drawing is authorized by Surface A.",
    ),
)
