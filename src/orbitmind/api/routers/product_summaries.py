"""Static product summary read-surface API routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from orbitmind.api.product_summary_schemas import ProductSummaryReadProductsResponse
from orbitmind.core.errors import ValidationError

router = APIRouter(prefix="/api/v1/product-summaries", tags=["product-summaries"])


@router.get("/read-products", response_model=ProductSummaryReadProductsResponse)
def get_read_product_catalog(request: Request) -> ProductSummaryReadProductsResponse:
    """Return the static read-product capability catalog."""

    _reject_query_params(request)
    return ProductSummaryReadProductsResponse.from_static_catalog()


def _reject_query_params(request: Request) -> None:
    if request.query_params:
        raise ValidationError("unsupported product-summary query parameter")
