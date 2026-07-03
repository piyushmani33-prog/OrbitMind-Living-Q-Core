"""API wire schemas for on-demand static reports.

Static reports are summary/index projections. They do not expose raw local
locators, sidecar JSON, image bytes, or internal persisted payloads.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from orbitmind.api.visual_manifest_schemas import (
    MissionVisualManifestResponse,
    OptimizationBenchmarkVisualManifestResponse,
)
from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import utcnow

STATIC_REPORT_SCHEMA_VERSION: Literal["static-report-v1"] = "static-report-v1"
MISSION_STATIC_REPORT_SOURCE_DOMAIN: Literal["mission"] = "mission"
OPTIMIZATION_BENCHMARK_STATIC_REPORT_SOURCE_DOMAIN: Literal["optimization-benchmark"] = (
    "optimization-benchmark"
)

MISSION_STATIC_REPORT_DISCLAIMER = (
    "This mission static report is a read-only, non-authoritative summary/index "
    "projection over persisted mission metadata and the reviewed mission visual "
    "manifest projection. It is not proof by itself, not evidence by itself, not "
    "live tracking, not real-time position authority, not operational access, not "
    "taskability, not command readiness, not approval, not certification, not "
    "signed receipt authority, not an operational recommendation, not autonomous "
    "decision-making, not causal proof, not complete lineage, not quantum authority, "
    "and not a claim of general quantum advantage."
)
OPTIMIZATION_BENCHMARK_STATIC_REPORT_DISCLAIMER = (
    "This optimization benchmark static report is a read-only, non-authoritative "
    "summary/index projection over authenticated persisted benchmark metadata and "
    "the reviewed optimization-benchmark visual manifest projection. It is not "
    "proof by itself, not evidence by itself, not operational access, not "
    "taskability, not command readiness, not approval, not authorization, not "
    "certification, not signed receipt authority, not consumer-conferred authority, "
    "not an operational recommendation, not autonomous decision-making, not causal "
    "proof, not complete lineage, not quantum authority, and not a claim of general "
    "quantum advantage."
)

AUTHORITY_BOUNDARIES: tuple[str, ...] = (
    "no live tracking",
    "no real-time position authority",
    "no operational access",
    "no taskability",
    "no command readiness",
    "no approval",
    "no certification",
    "no signed receipt authority",
    "no operational recommendation",
    "no autonomous decision-making",
    "no causal proof",
    "no complete lineage",
    "no quantum authority",
    "no general quantum advantage",
)
MISSION_REPORT_LIMITATIONS: tuple[str, ...] = (
    "Mission static report v1 is generated on demand and is not persisted as a report artifact.",
    "Mission static report v1 uses the existing mission visual manifest projection "
    "as its safe input layer; it does not inspect image bytes or sidecar JSON.",
    "Report identity is non-authoritative and is not a certificate, attestation, "
    "approval, receipt, signed receipt authority, or operational clearance.",
    "Mission static report v1 inherits the current mission read model; true owner "
    "isolation applies only to future owner-scoped report domains or after mission "
    "ownership is designed.",
)
OPTIMIZATION_BENCHMARK_REPORT_LIMITATIONS: tuple[str, ...] = (
    "Optimization benchmark static report v1 is generated on demand and is not "
    "persisted as a report artifact.",
    "Optimization benchmark static report v1 uses the existing authenticated "
    "optimization-benchmark visual manifest projection as its safe input layer; "
    "it does not parse, expose, or repackage sidecar JSON.",
    "Optimization benchmark static report v1 delegates to existing benchmark "
    "read authentication and fails closed on unauthenticated, integrity-failed, "
    "malformed, tampered, missing-artifact, or missing-sidecar evidence.",
    "Optimization benchmark static report v1 fails closed instead of emitting "
    "partial report bodies because unauthenticated evidence is diagnostic only "
    "and must not be served as a report product.",
    "receipt_status signed is a persisted record-integrity provenance signal "
    "only, not approval, authorization, certification, operational clearance, "
    "command readiness, signed receipt authority, or consumer-conferred authority.",
    "Quantum artifact labels, when present, are non-authoritative diagnostics; "
    "absence of quantum artifacts or samples can be normal.",
    "comparison_conclusion is the authenticated recorded label only; this report "
    "does not re-derive solver comparisons, rank solvers, expose thresholds, or "
    "present operational recommendations, and it preserves "
    "classical-baseline-authoritative framing.",
    "Optimization benchmark static report v1 inherits the current optimization "
    "benchmark read model; owner isolation applies only to future owner-scoped "
    "domains or after benchmark ownership is designed.",
)


class MissionStaticReportStatusSection(BaseModel):
    """Report identity and status section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_kind: Literal["mission-static-report"]
    generation_mode: Literal["on-demand"]
    authority: Literal["non-authoritative"]
    report_id_status: str
    owner_scope: str


class MissionStaticReportInputsSection(BaseModel):
    """Safe source and visual-manifest references used by the report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: str
    manifest_schema_version: str
    manifest_source_domain: Literal["mission"]
    manifest_scope_id: str
    source_record_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]
    source_labels: tuple[str, ...]


class MissionStaticReportSummarySection(BaseModel):
    """Bounded mission summary derived from the safe manifest projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    mission_id: str
    epistemic_status: str
    verification_state: str
    artifact_count: int
    artifact_types: tuple[str, ...]
    artifact_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]
    source_labels: tuple[str, ...]
    limitations: tuple[str, ...]


class MissionStaticReportEvidenceSection(BaseModel):
    """Evidence availability, limitations, and authority-negation section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_status: Literal["available"]
    withheld: bool
    authority_boundaries: tuple[str, ...]
    limitations: tuple[str, ...]
    disclaimer: str


class MissionStaticReportAppendixSection(BaseModel):
    """Appendix-style safe references only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route_references: tuple[str, ...]
    manifest_reference: str
    source_record_handles: tuple[str, ...]
    artifact_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]


class OptimizationBenchmarkStaticReportStatusSection(BaseModel):
    """Report identity and delegated-authentication status section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    report_kind: Literal["optimization-benchmark-static-report"]
    generation_mode: Literal["on-demand"]
    authority: Literal["non-authoritative"]
    authentication_mode: Literal["delegated-read-authentication"]
    failure_mode: Literal["fail-closed"]
    report_id_status: str
    owner_scope: str


class OptimizationBenchmarkStaticReportInputsSection(BaseModel):
    """Safe source and visual-manifest references used by the report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_id: str
    manifest_schema_version: str
    manifest_source_domain: Literal["optimization-benchmark"]
    manifest_scope_id: str
    source_record_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]
    source_labels: tuple[str, ...]


class OptimizationBenchmarkStaticReportSummarySection(BaseModel):
    """Bounded optimization benchmark summary from an authenticated manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    benchmark_id: str
    verified: bool
    integrity_failed: bool
    receipt_status: Literal["signed"]
    comparison_conclusion: str | None
    artifact_count: int
    artifact_types: tuple[str, ...]
    artifact_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]
    source_labels: tuple[str, ...]
    limitations: tuple[str, ...]


class OptimizationBenchmarkStaticReportEvidenceSection(BaseModel):
    """Evidence availability, delegated-authentication, and authority-negation section."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_status: Literal["authenticated"]
    withheld: bool
    receipt_status: Literal["signed"]
    delegated_authentication: str
    authority_boundaries: tuple[str, ...]
    limitations: tuple[str, ...]
    disclaimer: str


class OptimizationBenchmarkStaticReportAppendixSection(BaseModel):
    """Appendix-style safe references only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    route_references: tuple[str, ...]
    manifest_reference: str
    source_record_handles: tuple[str, ...]
    artifact_handles: tuple[str, ...]
    checksum_handles: tuple[str, ...]


class MissionStaticReportResponse(BaseModel):
    """Safe HTTP projection for a mission static report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["static-report-v1"]
    report_id: str
    read_at: datetime
    source_domain: Literal["mission"]
    scope_id: str
    report_status: MissionStaticReportStatusSection
    inputs_and_provenance: MissionStaticReportInputsSection
    mission_summary: MissionStaticReportSummarySection
    evidence_and_limitations: MissionStaticReportEvidenceSection
    appendix: MissionStaticReportAppendixSection
    limitations: tuple[str, ...]
    disclaimer: str

    @classmethod
    def from_manifest(
        cls,
        manifest: MissionVisualManifestResponse,
        *,
        read_at: datetime | None = None,
    ) -> MissionStaticReportResponse:
        """Build a report from the safe mission visual manifest projection.

        This performs no I/O, no rendering, no recomputation, and no sidecar or
        image inspection. The optional timestamp lets tests and future CLI code
        provide a deterministic read time if needed.
        """

        source_record_handles = _unique(
            handle for item in manifest.items for handle in item.source_record_handles
        )
        artifact_handles = tuple(item.artifact_handle for item in manifest.items)
        checksum_handles = tuple(item.checksum_handle for item in manifest.items)
        source_labels = _unique(label for item in manifest.items for label in item.source_labels)
        artifact_types = tuple(item.item_type for item in manifest.items)
        verification_state = _merged_label(
            tuple(item.verification_state for item in manifest.items),
            empty="mission-verification-unavailable",
            mixed="mixed-mission-verification-state",
        )
        epistemic_status = _merged_label(
            tuple(str(item.canonical_epistemic_status) for item in manifest.items),
            empty="unknown",
            mixed="mixed",
        )
        item_limitations = _unique(
            limitation for item in manifest.items for limitation in item.limitations
        )
        report_limitations = (
            *MISSION_REPORT_LIMITATIONS,
            *manifest.limitations,
        )
        route = "GET /api/v1/static-reports/mission/{mission_id}"
        manifest_route = "GET /api/v1/visual-manifests/mission/{mission_id}"
        return cls(
            schema_version=STATIC_REPORT_SCHEMA_VERSION,
            report_id=f"static-report:mission:{manifest.scope_id}:v1",
            read_at=read_at or utcnow(),
            source_domain=MISSION_STATIC_REPORT_SOURCE_DOMAIN,
            scope_id=manifest.scope_id,
            report_status=MissionStaticReportStatusSection(
                report_kind="mission-static-report",
                generation_mode="on-demand",
                authority="non-authoritative",
                report_id_status=(
                    "report_id is a deterministic non-authoritative summary/index identifier only"
                ),
                owner_scope=(
                    "inherits current mission read model; mission records are not "
                    "currently owner-scoped"
                ),
            ),
            inputs_and_provenance=MissionStaticReportInputsSection(
                manifest_id=manifest.manifest_id,
                manifest_schema_version=manifest.schema_version,
                manifest_source_domain=manifest.source_domain,
                manifest_scope_id=manifest.scope_id,
                source_record_handles=source_record_handles,
                checksum_handles=checksum_handles,
                source_labels=source_labels,
            ),
            mission_summary=MissionStaticReportSummarySection(
                mission_id=manifest.scope_id,
                epistemic_status=epistemic_status,
                verification_state=verification_state,
                artifact_count=len(manifest.items),
                artifact_types=artifact_types,
                artifact_handles=artifact_handles,
                checksum_handles=checksum_handles,
                source_labels=source_labels,
                limitations=(*item_limitations, *manifest.limitations),
            ),
            evidence_and_limitations=MissionStaticReportEvidenceSection(
                evidence_status="available",
                withheld=False,
                authority_boundaries=AUTHORITY_BOUNDARIES,
                limitations=report_limitations,
                disclaimer=MISSION_STATIC_REPORT_DISCLAIMER,
            ),
            appendix=MissionStaticReportAppendixSection(
                route_references=(route, manifest_route),
                manifest_reference=manifest.manifest_id,
                source_record_handles=source_record_handles,
                artifact_handles=artifact_handles,
                checksum_handles=checksum_handles,
            ),
            limitations=report_limitations,
            disclaimer=MISSION_STATIC_REPORT_DISCLAIMER,
        )


class OptimizationBenchmarkStaticReportResponse(BaseModel):
    """Safe HTTP projection for an authenticated optimization benchmark static report.

    Optimization benchmark static reports fail closed instead of emitting partial
    report bodies because unauthenticated evidence is diagnostic only and must not
    be served as a report product.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["static-report-v1"]
    report_id: str
    read_at: datetime
    source_domain: Literal["optimization-benchmark"]
    scope_id: str
    report_status: OptimizationBenchmarkStaticReportStatusSection
    inputs_and_provenance: OptimizationBenchmarkStaticReportInputsSection
    optimization_benchmark_summary: OptimizationBenchmarkStaticReportSummarySection
    evidence_and_limitations: OptimizationBenchmarkStaticReportEvidenceSection
    appendix: OptimizationBenchmarkStaticReportAppendixSection
    limitations: tuple[str, ...]
    disclaimer: str

    @classmethod
    def from_manifest(
        cls,
        manifest: OptimizationBenchmarkVisualManifestResponse,
        *,
        read_at: datetime | None = None,
    ) -> OptimizationBenchmarkStaticReportResponse:
        """Build a report from the safe optimization visual manifest projection.

        This performs no I/O, no rendering, no recomputation, no sidecar parsing,
        no receipt re-authentication, and no raw artifact file inspection.
        """

        if (
            not manifest.verified
            or manifest.integrity_failed
            or manifest.receipt_status != "signed"
        ):
            raise ValidationError("benchmark evidence is not authenticated for static report")
        source_record_handles = _unique(
            handle for item in manifest.items for handle in item.source_record_handles
        )
        artifact_handles = tuple(item.artifact_handle for item in manifest.items)
        checksum_handles = tuple(item.checksum_handle for item in manifest.items)
        source_labels = _unique(label for item in manifest.items for label in item.source_labels)
        artifact_types = tuple(item.item_type for item in manifest.items)
        item_limitations = _unique(
            limitation for item in manifest.items for limitation in item.limitations
        )
        report_limitations = (
            *OPTIMIZATION_BENCHMARK_REPORT_LIMITATIONS,
            *manifest.limitations,
        )
        route = "GET /api/v1/static-reports/optimization-benchmark/{benchmark_id}"
        manifest_route = "GET /api/v1/visual-manifests/optimization-benchmark/{benchmark_id}"
        return cls(
            schema_version=STATIC_REPORT_SCHEMA_VERSION,
            report_id=f"static-report:optimization-benchmark:{manifest.scope_id}:v1",
            read_at=read_at or utcnow(),
            source_domain=OPTIMIZATION_BENCHMARK_STATIC_REPORT_SOURCE_DOMAIN,
            scope_id=manifest.scope_id,
            report_status=OptimizationBenchmarkStaticReportStatusSection(
                report_kind="optimization-benchmark-static-report",
                generation_mode="on-demand",
                authority="non-authoritative",
                authentication_mode="delegated-read-authentication",
                failure_mode="fail-closed",
                report_id_status=(
                    "report_id is a deterministic non-authoritative summary/index identifier only"
                ),
                owner_scope=(
                    "inherits current optimization benchmark read model; optimization "
                    "benchmark records are not currently owner-scoped"
                ),
            ),
            inputs_and_provenance=OptimizationBenchmarkStaticReportInputsSection(
                manifest_id=manifest.manifest_id,
                manifest_schema_version=manifest.schema_version,
                manifest_source_domain=manifest.source_domain,
                manifest_scope_id=manifest.scope_id,
                source_record_handles=source_record_handles,
                checksum_handles=checksum_handles,
                source_labels=source_labels,
            ),
            optimization_benchmark_summary=OptimizationBenchmarkStaticReportSummarySection(
                benchmark_id=manifest.scope_id,
                verified=True,
                integrity_failed=False,
                receipt_status="signed",
                comparison_conclusion=manifest.comparison_conclusion,
                artifact_count=len(manifest.items),
                artifact_types=artifact_types,
                artifact_handles=artifact_handles,
                checksum_handles=checksum_handles,
                source_labels=source_labels,
                limitations=(*item_limitations, *manifest.limitations),
            ),
            evidence_and_limitations=OptimizationBenchmarkStaticReportEvidenceSection(
                evidence_status="authenticated",
                withheld=False,
                receipt_status="signed",
                delegated_authentication=(
                    "delegated to the existing optimization benchmark read-authentication path"
                ),
                authority_boundaries=AUTHORITY_BOUNDARIES,
                limitations=report_limitations,
                disclaimer=OPTIMIZATION_BENCHMARK_STATIC_REPORT_DISCLAIMER,
            ),
            appendix=OptimizationBenchmarkStaticReportAppendixSection(
                route_references=(route, manifest_route),
                manifest_reference=manifest.manifest_id,
                source_record_handles=source_record_handles,
                artifact_handles=artifact_handles,
                checksum_handles=checksum_handles,
            ),
            limitations=report_limitations,
            disclaimer=OPTIMIZATION_BENCHMARK_STATIC_REPORT_DISCLAIMER,
        )


def _unique(values: Iterable[object]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for value in values:
        seen[str(value)] = None
    return tuple(seen)


def _merged_label(values: tuple[str, ...], *, empty: str, mixed: str) -> str:
    unique = _unique(values)
    if not unique:
        return empty
    if len(unique) == 1:
        return unique[0]
    return mixed
