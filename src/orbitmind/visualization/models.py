"""Artifact metadata domain model."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.mission.models import OutputType


class ArtifactRecord(BaseModel):
    """Metadata describing a generated visual artifact (binary lives on disk)."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=new_id)
    mission_id: str
    type: OutputType
    path: str  # relative to the artifacts root
    sidecar_path: str  # relative to the artifacts root
    checksum: str  # sha256 of the image bytes
    created_at: datetime = Field(default_factory=utcnow)
