"""JPL/CNEOS Close-Approach Data (CAD) response model (source-specific)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CadSignature(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: str | None = None
    version: str | None = None


class CadResponse(BaseModel):
    """CAD returns column ``fields`` and row-major ``data`` (values as strings)."""

    model_config = ConfigDict(extra="ignore")

    signature: CadSignature | None = None
    count: int = 0
    fields: list[str] = Field(default_factory=list)
    data: list[list[str | None]] = Field(default_factory=list)
