"""API wire schemas for space objects + small bodies (Phase 3A)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from orbitmind.persistence.smallbody_repository import (
    StoredCloseApproach,
    StoredSpaceObject,
)
from orbitmind.smallbody.models import CloseApproachResultSet, SmallBodyRecord
from orbitmind.smallbody.query import CadQueryFilter, SmallBodyQueryResultSet
from orbitmind.verification.models import VerificationFinding

SMALL_BODY_DISCLAIMER = (
    "Source-reported JPL SBDB/CNEOS data. Orbit solutions carry uncertainty; physical "
    "values are estimates; small bodies use heliocentric models (never SGP4). A close "
    "approach is NOT an impact, and hazard flags are source-reported, not computed here."
)


class SmallBodyLookupRequest(BaseModel):
    """Lookup one asteroid/comet by an approved identifier."""

    identifier: str = Field(min_length=1, max_length=40, examples=["433", "Eros", "2021 AB"])
    force_refresh: bool = False
    generate_artifacts: bool = False


class SmallBodyLookupResponse(BaseModel):
    record: SmallBodyRecord
    findings: list[VerificationFinding]
    from_cache: bool
    artifacts: list[dict[str, str]]
    disclaimer: str = SMALL_BODY_DISCLAIMER


class CloseApproachRequest(BaseModel):
    """A constrained close-approach query."""

    filter: CadQueryFilter
    generate_artifacts: bool = False


class CloseApproachResponse(BaseModel):
    result: CloseApproachResultSet
    findings: list[VerificationFinding]
    artifacts: list[dict[str, str]]
    disclaimer: str = SMALL_BODY_DISCLAIMER


class SpaceObjectListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[StoredSpaceObject]


class CloseApproachListResponse(BaseModel):
    designation: str
    approaches: list[StoredCloseApproach]
    disclaimer: str = SMALL_BODY_DISCLAIMER


# Re-export filters used directly as request bodies.
__all__ = [
    "CloseApproachListResponse",
    "CloseApproachRequest",
    "CloseApproachResponse",
    "SmallBodyLookupRequest",
    "SmallBodyLookupResponse",
    "SmallBodyQueryResultSet",
    "SpaceObjectListResponse",
]
