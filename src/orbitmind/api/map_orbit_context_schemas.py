"""API wire schemas for coordinate-free Map/Orbit Contexts.

Map/Orbit Contexts are read-only context envelopes. They expose safe handles,
labels, limitations, and coordinate-display boundaries; they do not expose raw
coordinates, TLEs, samples, intervals, sidecars, image bytes, provider state, or
render instructions.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orbitmind.api.visual_manifest_schemas import MissionVisualManifestResponse
from orbitmind.core.timeutils import utcnow

MAP_ORBIT_CONTEXT_SCHEMA_VERSION: Literal["map-orbit-context-v1"] = "map-orbit-context-v1"
MISSION_MAP_ORBIT_CONTEXT_SOURCE_DOMAIN: Literal["mission"] = "mission"
MISSION_MAP_ORBIT_CONTEXT_TYPE: Literal["mission-map-orbit-context"] = "mission-map-orbit-context"
COORDINATE_PAYLOAD_POLICY: Literal["excluded-by-design-in-v1"] = "excluded-by-design-in-v1"

MISSION_MAP_ORBIT_CONTEXT_DISCLAIMER = (
    "This mission Map/Orbit Context is a coordinate-free, read-only, "
    "non-authoritative context projection over persisted mission metadata and "
    "the reviewed mission visual manifest projection. It is not proof by itself, "
    "not evidence by itself, not live tracking, not real-time position authority, "
    "not provider/live-data behavior, not rendering, not operational access, not "
    "taskability, not command readiness, not approval, not certification, not "
    "signed receipt authority, not an operational recommendation, not quantum "
    "authority, and not a claim of general quantum advantage."
)

AUTHORITY_BOUNDARIES: tuple[str, ...] = (
    "no live tracking",
    "no real-time position authority",
    "no provider/live-data",
    "no rendering",
    "no operational access",
    "no taskability",
    "no command readiness",
    "no approval",
    "no certification",
    "no signed receipt authority",
    "no operational recommendation",
    "no quantum authority",
    "no general quantum advantage",
)

MISSION_MAP_ORBIT_CONTEXT_LIMITATIONS: tuple[str, ...] = (
    "Mission Map/Orbit Context v1 is coordinate-free and generated on demand; "
    "coordinate payloads are excluded by design in v1.",
    "Mission Map/Orbit Context v1 uses the existing mission visual manifest "
    "projection as its safe input layer; it does not inspect artifact binary data, "
    "sidecar content, orbital element text, coordinate payloads, or internal orbital "
    "state payloads.",
    "Mission Map/Orbit Context v1 inherits the current mission read model; "
    "mission records are not currently owner-scoped.",
    "Static reports and provenance graphs may be references in future reviewed "
    "slices only; they are not evidence for Mission Map/Orbit Context v1.",
)

_MAP_CONTEXT_ARTIFACT_TYPE = "ground_track"
_ORBIT_CONTEXT_ARTIFACT_TYPE = "altitude_vs_time"


class MissionMapOrbitInputsSection(BaseModel):
    """Safe source and visual-manifest references used by the context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: str
    manifest_schema_version: str
    manifest_source_domain: Literal["mission"]
    manifest_scope_id: str
    mission_record_handle: str
    artifact_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]
    source_labels: tuple[str, ...]


class MissionMapContextSection(BaseModel):
    """Coordinate-free map-context metadata for reviewed ground-track artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_kind: Literal["mission-ground-track-context"]
    artifact_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]
    source_labels: tuple[str, ...]
    limitations: tuple[str, ...]
    coordinate_payloads: Literal["excluded-by-design-in-v1"]


class MissionOrbitContextSection(BaseModel):
    """Coordinate-free orbit-context metadata for reviewed altitude artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    context_kind: Literal["mission-orbit-context"]
    artifact_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]
    source_labels: tuple[str, ...]
    limitations: tuple[str, ...]
    coordinate_payloads: Literal["excluded-by-design-in-v1"]


class MissionMapOrbitEvidenceStatusSection(BaseModel):
    """Evidence availability and authority-boundary status for a successful context."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["available"]
    withheld: Literal[False]
    coordinate_payloads: Literal["excluded-by-design-in-v1"]
    authority_boundaries: tuple[str, ...]
    limitations: tuple[str, ...]


class MissionMapOrbitContextResponse(BaseModel):
    """Safe HTTP projection for Mission Map/Orbit Context v1.

    The ``scope_id`` intentionally uses the contract-pinned self-describing form
    ``mission:{mission_id}``, even though mission visual manifest and static
    report siblings use the bare mission id. The bare mission id remains exposed
    through ``inputs_and_provenance.manifest_scope_id`` and safe mission handles.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["map-orbit-context-v1"]
    context_id: str
    read_at: datetime
    source_domain: Literal["mission"]
    scope_id: str
    context_type: Literal["mission-map-orbit-context"]
    inputs_and_provenance: MissionMapOrbitInputsSection
    map_context: MissionMapContextSection
    orbit_context: MissionOrbitContextSection
    evidence_status: MissionMapOrbitEvidenceStatusSection
    limitations: tuple[str, ...]
    disclaimer: str

    @classmethod
    def from_manifest(
        cls,
        manifest: MissionVisualManifestResponse,
        *,
        read_at: datetime | None = None,
    ) -> MissionMapOrbitContextResponse:
        """Build a coordinate-free context from the safe mission visual manifest.

        This performs no I/O, no database reads, no file reads, no sidecar or image
        inspection, no raw TLE/sample/interval/coordinate reads, no provider calls,
        no rendering, no recomputation, no regeneration, and no mutation.
        """

        mission_id = manifest.scope_id
        scope_id = f"mission:{mission_id}"
        artifact_handles = tuple(item.artifact_handle for item in manifest.items)
        checksum_handles = tuple(item.checksum_handle for item in manifest.items)
        source_labels = _unique(label for item in manifest.items for label in item.source_labels)
        return cls(
            schema_version=MAP_ORBIT_CONTEXT_SCHEMA_VERSION,
            context_id=f"map-orbit-context:{scope_id}:v1",
            read_at=read_at or utcnow(),
            source_domain=MISSION_MAP_ORBIT_CONTEXT_SOURCE_DOMAIN,
            scope_id=scope_id,
            context_type=MISSION_MAP_ORBIT_CONTEXT_TYPE,
            inputs_and_provenance=MissionMapOrbitInputsSection(
                manifest_id=manifest.manifest_id,
                manifest_schema_version=manifest.schema_version,
                manifest_source_domain=manifest.source_domain,
                manifest_scope_id=mission_id,
                mission_record_handle=scope_id,
                artifact_handles=artifact_handles,
                checksum_handles=checksum_handles,
                source_labels=source_labels,
            ),
            map_context=MissionMapContextSection(
                context_kind="mission-ground-track-context",
                artifact_handles=_artifact_handles(manifest, _MAP_CONTEXT_ARTIFACT_TYPE),
                checksum_handles=_checksum_handles(manifest, _MAP_CONTEXT_ARTIFACT_TYPE),
                source_labels=source_labels,
                limitations=_context_limitations(manifest, _MAP_CONTEXT_ARTIFACT_TYPE),
                coordinate_payloads=COORDINATE_PAYLOAD_POLICY,
            ),
            orbit_context=MissionOrbitContextSection(
                context_kind="mission-orbit-context",
                artifact_handles=_artifact_handles(manifest, _ORBIT_CONTEXT_ARTIFACT_TYPE),
                checksum_handles=_checksum_handles(manifest, _ORBIT_CONTEXT_ARTIFACT_TYPE),
                source_labels=source_labels,
                limitations=_context_limitations(manifest, _ORBIT_CONTEXT_ARTIFACT_TYPE),
                coordinate_payloads=COORDINATE_PAYLOAD_POLICY,
            ),
            evidence_status=MissionMapOrbitEvidenceStatusSection(
                status="available",
                withheld=False,
                coordinate_payloads=COORDINATE_PAYLOAD_POLICY,
                authority_boundaries=AUTHORITY_BOUNDARIES,
                limitations=MISSION_MAP_ORBIT_CONTEXT_LIMITATIONS,
            ),
            limitations=MISSION_MAP_ORBIT_CONTEXT_LIMITATIONS,
            disclaimer=MISSION_MAP_ORBIT_CONTEXT_DISCLAIMER,
        )


def _artifact_handles(
    manifest: MissionVisualManifestResponse, artifact_type: str
) -> tuple[str, ...]:
    return tuple(item.artifact_handle for item in manifest.items if item.item_type == artifact_type)


def _checksum_handles(
    manifest: MissionVisualManifestResponse, artifact_type: str
) -> tuple[str, ...]:
    return tuple(item.checksum_handle for item in manifest.items if item.item_type == artifact_type)


def _context_limitations(
    manifest: MissionVisualManifestResponse, artifact_type: str
) -> tuple[str, ...]:
    matching = tuple(item for item in manifest.items if item.item_type == artifact_type)
    limitations = _unique(limitation for item in matching for limitation in item.limitations)
    if not matching:
        limitations = (
            f"No reviewed artifact of type {artifact_type} exists for this mission; "
            "no artifact handle or checksum handle is fabricated.",
        )
    return (
        "This section is coordinate-free context metadata only; coordinate payloads "
        "are excluded by design in v1.",
        *limitations,
    )


def _unique(values: Iterable[object]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        seen[str(value)] = None
    return tuple(seen)
