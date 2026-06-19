"""Provenance and evidence domain models (ADR-0006)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.core.timeutils import utcnow


class EvidenceReference(BaseModel):
    """A pointer to supporting evidence (e.g., a bundled fixture)."""

    model_config = ConfigDict(frozen=True)

    kind: str  # e.g. "tle-fixture"
    locator: str  # e.g. fixture id or path-relative reference
    description: str


class ProvenanceRecord(BaseModel):
    """Claim-level provenance for a produced result."""

    subject_ref: str  # what this provenance is about (e.g. "scientific_result")
    source_ref: str  # the source identity (e.g. fixture id / source record name)
    method: str  # how it was produced (e.g. "sgp4-propagation")
    inputs_hash: str  # sha256 of canonical inputs
    generated_at: datetime = Field(default_factory=utcnow)
    evidence: list[EvidenceReference] = Field(default_factory=list)
