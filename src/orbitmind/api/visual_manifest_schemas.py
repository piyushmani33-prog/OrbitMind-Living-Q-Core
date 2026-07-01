"""API wire schemas for read-only visual manifests.

Phase 5.4 exposes only DB-backed mission artifact metadata. It does not read
sidecar JSON, image files, or raw local paths.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.mission.models import Mission
from orbitmind.sources.models import MissionSourceData
from orbitmind.verification.models import VerificationFinding
from orbitmind.visualization.models import ArtifactRecord

VISUAL_MANIFEST_SCHEMA_VERSION: Literal["visual-manifest-v1"] = "visual-manifest-v1"
VISUAL_MANIFEST_SOURCE_DOMAIN: Literal["mission"] = "mission"
VISUAL_MANIFEST_DISCLAIMER = (
    "This visual manifest is a read-only discovery/index projection over persisted "
    "mission and artifact metadata. It is not verification by itself, not live "
    "tracking, not operational access, not taskability, not command readiness, not "
    "approval, not a signed receipt, not certification, and not quantum authority."
)

_CHECKSUM_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_DB_ONLY_LIMITATION = (
    "Phase 5.4 mission v1 uses persisted database records only; it does not read "
    "sidecar JSON or image files, and it does not recompute file checksums."
)
_NON_AUTHORITATIVE_LIMITATION = (
    "manifest_id is a non-authoritative discovery/index identifier, not a receipt id, "
    "attestation id, signature id, approval id, or certification id."
)
_MISSION_ARTIFACT_LIMITATION = (
    "Artifact handles and checksum handles are persisted metadata only; sidecar "
    "scientific context, artifact-byte verification, and file checksum "
    "re-authentication are deferred to a future reviewed slice."
)
_MISSION_VERIFICATION_LIMITATION = (
    "verification_state is derived from persisted mission-level findings only, not "
    "artifact-byte or sidecar verification."
)


class MissionVisualManifestItemResponse(BaseModel):
    """Path-free DB-backed visual item metadata for one mission artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    item_type: str
    media_type: str
    artifact_handle: str
    checksum_handle: str
    source_record_handles: tuple[str, ...]
    canonical_epistemic_status: EpistemicStatus
    verification_state: str
    source_labels: tuple[str, ...]
    limitations: tuple[str, ...]
    disclaimers: tuple[str, ...]
    presentation_hints: dict[str, str]


class MissionVisualManifestResponse(BaseModel):
    """Safe HTTP projection for a mission visual manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["visual-manifest-v1"]
    manifest_id: str
    read_at: datetime
    source_domain: Literal["mission"]
    scope_id: str
    items: tuple[MissionVisualManifestItemResponse, ...]
    limitations: tuple[str, ...]
    disclaimer: str

    @classmethod
    def from_mission(
        cls,
        *,
        mission: Mission,
        artifacts: list[ArtifactRecord],
        findings: list[VerificationFinding],
        source_data: MissionSourceData | None,
    ) -> MissionVisualManifestResponse:
        source_record_handles = _source_record_handles(mission.id, source_data)
        source_labels = _source_labels(mission, source_data)
        verification_state = _mission_verification_state(findings)
        return cls(
            schema_version=VISUAL_MANIFEST_SCHEMA_VERSION,
            manifest_id=f"visual-manifest:mission:{mission.id}:v1",
            read_at=utcnow(),
            source_domain=VISUAL_MANIFEST_SOURCE_DOMAIN,
            scope_id=mission.id,
            items=tuple(
                _item_from_artifact(
                    artifact=artifact,
                    mission=mission,
                    source_record_handles=source_record_handles,
                    source_labels=source_labels,
                    verification_state=verification_state,
                )
                for artifact in artifacts
            ),
            limitations=(
                _DB_ONLY_LIMITATION,
                _NON_AUTHORITATIVE_LIMITATION,
                "Mission artifacts are persisted offline outputs, not live feeds or "
                "operational access.",
            ),
            disclaimer=VISUAL_MANIFEST_DISCLAIMER,
        )


def _item_from_artifact(
    *,
    artifact: ArtifactRecord,
    mission: Mission,
    source_record_handles: tuple[str, ...],
    source_labels: tuple[str, ...],
    verification_state: str,
) -> MissionVisualManifestItemResponse:
    checksum = _normalized_checksum(artifact.checksum, "artifact checksum")
    return MissionVisualManifestItemResponse(
        item_id=artifact.id,
        item_type=artifact.type.value,
        media_type="image/png",
        artifact_handle=f"mission-artifact:{artifact.id}",
        checksum_handle=f"sha256:{checksum}",
        source_record_handles=source_record_handles,
        canonical_epistemic_status=mission.epistemic_status,
        verification_state=verification_state,
        source_labels=source_labels,
        limitations=(_MISSION_ARTIFACT_LIMITATION, _MISSION_VERIFICATION_LIMITATION),
        disclaimers=(
            "This item is a path-free DB-backed artifact metadata projection, not "
            "artifact file authentication.",
        ),
        presentation_hints={
            "visual_role": "mission-artifact",
            "display_label": artifact.type.value.replace("_", " "),
            "scientific_authority": "none-added",
        },
    )


def _source_record_handles(
    mission_id: str, source_data: MissionSourceData | None
) -> tuple[str, ...]:
    handles = [f"mission:{mission_id}"]
    if source_data is not None:
        handles.append(f"source-record:{source_data.source_id}:{source_data.record_identifier}")
        source_checksum = _normalized_checksum(source_data.checksum, "source checksum")
        handles.append(f"source-checksum:sha256:{source_checksum}")
    return tuple(handles)


def _source_labels(mission: Mission, source_data: MissionSourceData | None) -> tuple[str, ...]:
    labels = [f"mission-source:{mission.normalized_request.source.value}"]
    if mission.normalized_request.source.value == "sample":
        labels.append("test-only:true")
    if source_data is not None:
        labels.extend(
            (
                f"source-id:{source_data.source_id}",
                f"freshness:{source_data.freshness_state}",
                f"liveness:{source_data.liveness}",
                f"cache:{source_data.cache_status}",
            )
        )
    return tuple(labels)


def _mission_verification_state(findings: list[VerificationFinding]) -> str:
    if not findings:
        return "mission-verification-unavailable"
    if all(finding.passed for finding in findings):
        return "mission-verification-passed"
    return "mission-verification-not-passed"


def _normalized_checksum(value: str, field_name: str) -> str:
    if not _CHECKSUM_RE.fullmatch(value):
        raise ValidationError(f"{field_name} must be a 64-character hexadecimal checksum")
    return value.lower()
