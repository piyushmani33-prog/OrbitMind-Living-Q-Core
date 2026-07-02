"""API wire schemas for read-only visual manifests.

Visual manifests expose path-free discovery metadata. They do not expose sidecar JSON,
image files, or raw local paths.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orbitmind.api.optimization_views import ArtifactView
from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.mission.models import Mission
from orbitmind.optimization.models import BenchmarkRun
from orbitmind.sources.models import MissionSourceData
from orbitmind.verification.models import VerificationFinding
from orbitmind.visualization.models import ArtifactRecord

VISUAL_MANIFEST_SCHEMA_VERSION: Literal["visual-manifest-v1"] = "visual-manifest-v1"
MISSION_VISUAL_MANIFEST_SOURCE_DOMAIN: Literal["mission"] = "mission"
OPTIMIZATION_BENCHMARK_VISUAL_MANIFEST_SOURCE_DOMAIN: Literal["optimization-benchmark"] = (
    "optimization-benchmark"
)
VISUAL_MANIFEST_DISCLAIMER: str = (
    "This visual manifest is a read-only discovery/index projection over persisted "
    "mission and artifact metadata. It is not verification by itself, not live "
    "tracking, not operational access, not taskability, not command readiness, not "
    "approval, not a signed receipt, not certification, and not quantum authority."
)
OPTIMIZATION_BENCHMARK_VISUAL_MANIFEST_DISCLAIMER: str = (
    "This optimization benchmark visual manifest is a read-only discovery/index "
    "projection over authenticated persisted benchmark artifact metadata. It is not "
    "verification by itself, not operational access, not taskability, not command "
    "readiness, not approval, not a signed receipt, not certification, not quantum "
    "authority, and not a claim of general quantum advantage."
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
_OPTIMIZATION_MANIFEST_LIMITATION = (
    "Phase 5.7 optimization-benchmark v1 delegates to the existing authenticated "
    "benchmark read path and projects only path-free artifact metadata; the manifest "
    "schema does not expose or repackage sidecar JSON."
)
_OPTIMIZATION_NON_AUTHORITATIVE_LIMITATION = (
    "manifest_id is a non-authoritative discovery/index identifier, not a receipt id, "
    "approval id, certification id, or operational clearance."
)
_OPTIMIZATION_RECEIPT_LIMITATION = (
    "receipt_status is projected only as the existing read-time record-integrity "
    "state; the manifest does not issue, re-sign, reinterpret, or expose receipt "
    "internals."
)
_OPTIMIZATION_QUANTUM_LIMITATION = (
    "Quantum artifacts, when present, are non-authoritative diagnostics; absence of "
    "quantum visual artifacts is normal when no persisted quantum diagnostic data exists."
)
_OPTIMIZATION_COMPARISON_LIMITATION = (
    "comparison_conclusion is the recorded authenticated label only; this manifest "
    "does not re-derive solver comparisons or present operational recommendations."
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
            source_domain=MISSION_VISUAL_MANIFEST_SOURCE_DOMAIN,
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


class OptimizationBenchmarkVisualManifestItemResponse(BaseModel):
    """Path-free visual item metadata for one optimization benchmark artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str
    item_type: str
    media_type: str
    artifact_handle: str
    checksum_handle: str
    source_record_handles: tuple[str, ...]
    canonical_epistemic_status: EpistemicStatus
    source_labels: tuple[str, ...]
    limitations: tuple[str, ...]
    disclaimers: tuple[str, ...]
    presentation_hints: dict[str, str]


class OptimizationBenchmarkVisualManifestResponse(BaseModel):
    """Safe HTTP projection for an authenticated optimization benchmark manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["visual-manifest-v1"]
    manifest_id: str
    read_at: datetime
    source_domain: Literal["optimization-benchmark"]
    scope_id: str
    verified: bool
    integrity_failed: bool
    receipt_status: Literal["signed", "none", "integrity-failed"]
    comparison_conclusion: str | None
    items: tuple[OptimizationBenchmarkVisualManifestItemResponse, ...]
    limitations: tuple[str, ...]
    disclaimer: str

    @classmethod
    def from_authenticated_benchmark(
        cls,
        *,
        run: BenchmarkRun,
        artifacts: list[ArtifactView],
        verified: bool,
        integrity_failed: bool,
        receipt_status: str,
        comparison_conclusion: str | None,
    ) -> OptimizationBenchmarkVisualManifestResponse:
        receipt_state = _optimization_receipt_status(receipt_status)
        source_record_handles = _optimization_source_record_handles(run)
        source_labels = _optimization_source_labels(
            run=run,
            verified=verified,
            integrity_failed=integrity_failed,
            receipt_status=receipt_state,
            comparison_conclusion=comparison_conclusion,
        )
        return cls(
            schema_version=VISUAL_MANIFEST_SCHEMA_VERSION,
            manifest_id=f"visual-manifest:optimization-benchmark:{run.id}:v1",
            read_at=utcnow(),
            source_domain=OPTIMIZATION_BENCHMARK_VISUAL_MANIFEST_SOURCE_DOMAIN,
            scope_id=run.id,
            verified=verified,
            integrity_failed=integrity_failed,
            receipt_status=receipt_state,
            comparison_conclusion=comparison_conclusion,
            items=tuple(
                _optimization_item_from_artifact(
                    artifact=artifact,
                    source_record_handles=source_record_handles,
                    source_labels=source_labels,
                )
                for artifact in artifacts
            ),
            limitations=(
                _OPTIMIZATION_MANIFEST_LIMITATION,
                _OPTIMIZATION_NON_AUTHORITATIVE_LIMITATION,
                _OPTIMIZATION_RECEIPT_LIMITATION,
                _OPTIMIZATION_QUANTUM_LIMITATION,
                _OPTIMIZATION_COMPARISON_LIMITATION,
            ),
            disclaimer=OPTIMIZATION_BENCHMARK_VISUAL_MANIFEST_DISCLAIMER,
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


def _optimization_item_from_artifact(
    *,
    artifact: ArtifactView,
    source_record_handles: tuple[str, ...],
    source_labels: tuple[str, ...],
) -> OptimizationBenchmarkVisualManifestItemResponse:
    artifact_id = _required_artifact_id(artifact)
    checksum = _normalized_checksum(artifact.checksum, "artifact checksum")
    limitations: tuple[str, ...] = (
        "This item is path-free optimization artifact metadata, not artifact file "
        "authentication and not raw sidecar content.",
        "Receipt, quantum execution, and solver implementation internals are not exposed.",
    )
    if artifact.type.startswith("quantum_"):
        limitations = (
            *limitations,
            "Quantum artifact metadata is non-authoritative diagnostic context only.",
        )
    return OptimizationBenchmarkVisualManifestItemResponse(
        item_id=artifact_id,
        item_type=artifact.type,
        media_type=artifact.media_type,
        artifact_handle=f"optimization-artifact:{artifact_id}",
        checksum_handle=f"sha256:{checksum}",
        source_record_handles=source_record_handles,
        canonical_epistemic_status=_epistemic_status(artifact.epistemic_status),
        source_labels=source_labels,
        limitations=limitations,
        disclaimers=(
            "This item is a path-free authenticated benchmark artifact projection, not "
            "a receipt, approval, certification, operational recommendation, or quantum "
            "authority.",
        ),
        presentation_hints={
            "visual_role": "optimization-benchmark-artifact",
            "display_label": artifact.type.replace("_", " "),
            "scientific_authority": "none-added",
        },
    )


def _optimization_source_record_handles(run: BenchmarkRun) -> tuple[str, ...]:
    handles = [
        f"optimization-benchmark:{run.id}",
        f"optimization-problem:{run.problem_id}",
    ]
    problem_checksum = _normalized_checksum(run.problem_checksum, "problem checksum")
    handles.append(f"problem-checksum:sha256:{problem_checksum}")
    return tuple(handles)


def _optimization_source_labels(
    *,
    run: BenchmarkRun,
    verified: bool,
    integrity_failed: bool,
    receipt_status: str,
    comparison_conclusion: str | None,
) -> tuple[str, ...]:
    labels = [
        "optimization-source:benchmark",
        f"evidence-authenticated:{str(verified).lower()}",
        f"integrity-failed:{str(integrity_failed).lower()}",
        f"receipt-status:{receipt_status}",
        f"has-quantum:{str(run.quantum_experiment is not None).lower()}",
    ]
    if comparison_conclusion is not None:
        labels.append(f"comparison-conclusion:{comparison_conclusion}")
    return tuple(labels)


def _optimization_receipt_status(
    value: str,
) -> Literal["signed", "none", "integrity-failed"]:
    if value == "signed":
        return "signed"
    if value == "none":
        return "none"
    if value == "integrity-failed":
        return "integrity-failed"
    raise ValidationError("receipt status is not valid")


def _required_artifact_id(artifact: ArtifactView) -> str:
    if artifact.id is None or not artifact.id:
        raise ValidationError("artifact id is required for visual manifest projection")
    return artifact.id


def _epistemic_status(value: str) -> EpistemicStatus:
    try:
        return EpistemicStatus(value)
    except ValueError as exc:
        raise ValidationError("artifact epistemic status is not valid") from exc


def _normalized_checksum(value: str, field_name: str) -> str:
    if not _CHECKSUM_RE.fullmatch(value):
        raise ValidationError(f"{field_name} must be a 64-character hexadecimal checksum")
    return value.lower()
