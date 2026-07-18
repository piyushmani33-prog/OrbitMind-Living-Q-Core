"""Built-in laboratory catalog and deterministic visual projections.

One truthful built-in laboratory (the Development Laboratory, catalog
foundation only) plus clearly-labelled static architectural metadata used by
the read API and the visual Workbench: the planned-laboratory roadmap, the
governed mission flow, the evidence chain, the safety/approval plane and the
offline/connected boundary. Everything here is deterministic, offline and
free of runtime measurement — no fake telemetry, health or activity.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from orbitmind import __version__
from orbitmind.laboratory.capabilities import (
    CAPABILITY_IS_NOT_PERMISSION,
    ApprovalPosture,
    CapabilityDeclaration,
    CapabilityDeterminism,
    LabCapability,
)
from orbitmind.laboratory.contracts import (
    ApprovalGate,
    CompatibilityInfo,
    HardwarePosture,
    LaboratoryDomain,
    LaboratoryImplementationStatus,
    LaboratoryManifest,
    NetworkPosture,
    PersistencePosture,
    ReplayRequirement,
    ResourceBoundaries,
)
from orbitmind.laboratory.registry import LaboratoryRegistry

LABORATORY_CATALOG_SCHEMA_VERSION: Final = "laboratory-catalog-v1"
PLANNED_STATUS_LABEL: Final = "planned — no runtime implementation"


def build_development_laboratory_manifest() -> LaboratoryManifest:
    """The one truthful built-in laboratory: catalog/governance foundation only."""
    return LaboratoryManifest(
        laboratory_id="development-laboratory",
        display_name="Development Laboratory",
        laboratory_version="0.1.0",
        domain=LaboratoryDomain.DEVELOPMENT,
        description=(
            "Catalog and governance foundation for future governed software-"
            "development work inside OrbitMind. Declares the capability "
            "vocabulary and approval postures such work would require. No "
            "agent runtime is connected and no development work is performed."
        ),
        implementation_status=LaboratoryImplementationStatus.CATALOG_FOUNDATION,
        capabilities=(
            CapabilityDeclaration(
                capability=LabCapability.REPOSITORY_READ,
                approval_posture=ApprovalPosture.MISSION_APPROVAL_REQUIRED,
                determinism=CapabilityDeterminism.DETERMINISTIC,
                summary=(
                    "Read repository content at a pinned revision inside an "
                    "approved mission. Declared for future work; no tool is "
                    "connected."
                ),
            ),
            CapabilityDeclaration(
                capability=LabCapability.REPOSITORY_WRITE,
                approval_posture=ApprovalPosture.ACTION_APPROVAL_REQUIRED,
                determinism=CapabilityDeterminism.DETERMINISTIC,
                summary=(
                    "Propose a bounded candidate change for human review. "
                    "Writing anything would require explicit per-action "
                    "approval; no write path exists in this slice."
                ),
            ),
            CapabilityDeclaration(
                capability=LabCapability.TEST_EXECUTE,
                approval_posture=ApprovalPosture.MISSION_APPROVAL_REQUIRED,
                determinism=CapabilityDeterminism.DETERMINISTIC,
                summary=(
                    "Run the offline deterministic test suite as evidence "
                    "collection inside an approved mission. Not implemented "
                    "in this slice."
                ),
            ),
            CapabilityDeclaration(
                capability=LabCapability.LOCAL_PROCESS_EXECUTE,
                approval_posture=ApprovalPosture.ACTION_APPROVAL_REQUIRED,
                determinism=CapabilityDeterminism.NON_DETERMINISTIC,
                summary=(
                    "Execute a bounded local process under explicit per-"
                    "action approval and resource limits. Not implemented in "
                    "this slice; generated code is never executed."
                ),
            ),
        ),
        accepted_goal_categories=(
            "code-change-proposal",
            "test-evidence-collection",
        ),
        required_deterministic_services=(
            "mission-lifecycle",
            "provenance",
            "verification",
            "artifact-persistence",
        ),
        adapters=(),
        produced_artifact_categories=(
            "candidate-diff",
            "test-report",
        ),
        produced_evidence_categories=(
            "review-evidence",
            "test-execution-evidence",
        ),
        network_posture=NetworkPosture.OFFLINE_ONLY,
        hardware_posture=HardwarePosture.NO_HARDWARE_ACCESS,
        persistence_posture=PersistencePosture.NO_LABORATORY_PERSISTENCE,
        approval_gates=(
            ApprovalGate.NETWORK_ACCESS,
            ApprovalGate.EXTERNAL_AI,
            ApprovalGate.REPOSITORY_WRITE,
            ApprovalGate.DEPENDENCY_INSTALLATION,
            ApprovalGate.COMMIT,
            ApprovalGate.PUSH,
            ApprovalGate.PULL_REQUEST,
            ApprovalGate.MERGE,
            ApprovalGate.DEPLOYMENT,
        ),
        replay_support=ReplayRequirement.DETERMINISTIC_REPLAY_REQUIRED,
        verification_requirements=(
            "Future laboratory outputs must pass the existing verification service before review.",
            "Generated code is untrusted: it is never executed or promoted automatically.",
        ),
        resource_boundaries=ResourceBoundaries(
            max_concurrent_missions=1,
            max_mission_wall_clock_seconds=3_600,
            notes=(
                "Declared bounds for future governed work; nothing executes "
                "in this catalog-foundation slice."
            ),
        ),
        compatibility=CompatibilityInfo(
            platform_version_baseline=__version__,
            mission_contract=(
                "Reuses the existing Mission aggregate as the governed work "
                "primitive (ADR-0031); no new work object is introduced."
            ),
        ),
        limitations=(
            "No agent runtime is connected.",
            "No autonomous development occurs.",
            "No external AI adapter is connected.",
            "Declared write and execution capabilities are not granted; "
            "declaration is metadata, not permission.",
            "Merge and deployment remain human-authorized.",
            "This slice provides catalog and governance foundations only.",
        ),
    )


class PlannedLaboratoryProjection(BaseModel):
    """A roadmap-only laboratory: static metadata, never registered as active."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    laboratory_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,47}$")
    display_name: str = Field(min_length=1, max_length=80)
    domain: LaboratoryDomain
    status: Literal["planned — no runtime implementation"] = PLANNED_STATUS_LABEL
    summary: str = Field(min_length=1, max_length=300)


PLANNED_LABORATORIES: tuple[PlannedLaboratoryProjection, ...] = (
    PlannedLaboratoryProjection(
        laboratory_id="research-laboratory",
        display_name="Research Laboratory",
        domain=LaboratoryDomain.RESEARCH,
        summary=(
            "Future governed literature and evidence research on top of the "
            "existing research memory surfaces."
        ),
    ),
    PlannedLaboratoryProjection(
        laboratory_id="quantum-laboratory",
        display_name="Quantum Laboratory",
        domain=LaboratoryDomain.QUANTUM,
        summary=(
            "Future bounded quantum experimentation, simulator-only and "
            "classical-baseline-first per ADR-0005/ADR-0027."
        ),
    ),
    PlannedLaboratoryProjection(
        laboratory_id="robotics-laboratory",
        display_name="Robotics Laboratory",
        domain=LaboratoryDomain.ROBOTICS,
        summary=(
            "Future robotics design/simulation work; physical hardware "
            "control remains a prohibited-by-default approval gate."
        ),
    ),
    PlannedLaboratoryProjection(
        laboratory_id="space-laboratory",
        display_name="Space Laboratory",
        domain=LaboratoryDomain.SPACE,
        summary=(
            "Future extension of the existing deterministic orbital slice "
            "into a full laboratory surface."
        ),
    ),
    PlannedLaboratoryProjection(
        laboratory_id="manufacturing-laboratory",
        display_name="Manufacturing Laboratory",
        domain=LaboratoryDomain.MANUFACTURING,
        summary=(
            "Future manufacturing/process engineering workflows; no design or tooling exists yet."
        ),
    ),
)


class MissionFlowStage(BaseModel):
    """One conceptual stage of the governed mission flow."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage: str = Field(min_length=1, max_length=60)
    exists_today: bool
    provided_by: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=300)


GOVERNED_MISSION_FLOW: tuple[MissionFlowStage, ...] = (
    MissionFlowStage(
        stage="User Goal",
        exists_today=True,
        provided_by="Existing operator surfaces (Workbench forms, API requests)",
        description="A human states the goal; nothing starts autonomously.",
    ),
    MissionFlowStage(
        stage="Mission",
        exists_today=True,
        provided_by="orbitmind.mission (Mission aggregate, ADR-0031 primitive)",
        description="The goal becomes an identified Mission with preserved raw input.",
    ),
    MissionFlowStage(
        stage="Planning",
        exists_today=False,
        provided_by="Future Laboratory planning (not implemented)",
        description="Laboratory-level plan proposals are future work.",
    ),
    MissionFlowStage(
        stage="Capability Request",
        exists_today=False,
        provided_by="Future Laboratory runtime (not implemented)",
        description="Future work units would request declared capabilities explicitly.",
    ),
    MissionFlowStage(
        stage="Approval",
        exists_today=True,
        provided_by=(
            "Existing human-approval steps (e.g. governed research promotion); "
            "laboratory capability approvals are future work"
        ),
        description="Sensitive steps require explicit human approval.",
    ),
    MissionFlowStage(
        stage="Deterministic Execution / Adapter Invocation",
        exists_today=True,
        provided_by="orbitmind.orchestration + deterministic domain services",
        description=(
            "Deterministic tools do the calculations today; laboratory adapter "
            "invocation is future work."
        ),
    ),
    MissionFlowStage(
        stage="Evidence",
        exists_today=True,
        provided_by="Artifacts + checksums + provenance records",
        description="Every result carries identified, checksummed evidence.",
    ),
    MissionFlowStage(
        stage="Verification",
        exists_today=True,
        provided_by="orbitmind.verification checks",
        description="Findings are recorded; bad data never raises silently.",
    ),
    MissionFlowStage(
        stage="Review",
        exists_today=True,
        provided_by="Reviewer sandbox and workbench read surfaces",
        description="Humans inspect results and evidence before relying on them.",
    ),
    MissionFlowStage(
        stage="Completion or Rejection",
        exists_today=True,
        provided_by="Mission lifecycle status (completed / failed)",
        description="Missions end in an explicit recorded state.",
    ),
    MissionFlowStage(
        stage="Replay or Re-evaluation",
        exists_today=True,
        provided_by="Deterministic replay surfaces (e.g. trajectory replay)",
        description=(
            "Deterministic replay and non-deterministic re-evaluation are "
            "distinct classifications, never conflated."
        ),
    ),
)


class EvidenceChainLink(BaseModel):
    """One link of the existing evidence chain (architecture projection)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    link: str = Field(min_length=1, max_length=60)
    provided_by: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=300)


EVIDENCE_CHAIN: tuple[EvidenceChainLink, ...] = (
    EvidenceChainLink(
        link="Inputs",
        provided_by="Preserved raw request + normalized domain request",
        description="Immutable inputs are kept verbatim alongside the mission.",
    ),
    EvidenceChainLink(
        link="Configuration",
        provided_by="Typed Settings snapshot semantics",
        description="Runs are bound to explicit, validated configuration.",
    ),
    EvidenceChainLink(
        link="Artifact identity",
        provided_by="Artifact records with stable identifiers",
        description="Each produced artifact is individually identified.",
    ),
    EvidenceChainLink(
        link="Checksum",
        provided_by="SHA-256 checksums on artifacts and sources",
        description="Byte-level integrity is recorded for evidence files.",
    ),
    EvidenceChainLink(
        link="Provenance",
        provided_by="Provenance records (inputs hash, source checksums)",
        description="Where data came from is preserved with the result.",
    ),
    EvidenceChainLink(
        link="Approvals",
        provided_by="Human approval steps on sensitive paths",
        description="Sensitive promotion/actions record explicit human approval.",
    ),
    EvidenceChainLink(
        link="Execution record",
        provided_by="Mission status + audit events",
        description="What ran, when, and with what outcome is recorded.",
    ),
    EvidenceChainLink(
        link="Verification",
        provided_by="Verification findings attached to results",
        description="Checks run over outputs; findings are part of the record.",
    ),
    EvidenceChainLink(
        link="Replay classification",
        provided_by="Deterministic replay vs re-evaluation labels",
        description="Replays are classified; determinism is never assumed.",
    ),
    EvidenceChainLink(
        link="Limitations",
        provided_by="Epistemic labels + explicit limitation statements",
        description="Every major output states what it is not.",
    ),
)


class SafetyBoundary(BaseModel):
    """One sensitive boundary of the governance plane."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    gate: ApprovalGate
    current_state: str = Field(min_length=1, max_length=200)
    requires_human_approval: Literal[True] = True


SAFETY_BOUNDARIES: tuple[SafetyBoundary, ...] = tuple(
    SafetyBoundary(gate=gate, current_state=state)
    for gate, state in (
        (
            ApprovalGate.NETWORK_ACCESS,
            "Disabled by default; provider sources require explicit enablement.",
        ),
        (ApprovalGate.EXTERNAL_AI, "No external AI adapter exists in this runtime."),
        (ApprovalGate.REPOSITORY_WRITE, "No laboratory write path exists."),
        (ApprovalGate.DEPENDENCY_INSTALLATION, "No install surface exists."),
        (ApprovalGate.CLOUD_SERVICE, "No cloud control plane exists."),
        (
            ApprovalGate.QUANTUM_HARDWARE,
            "Prohibited; quantum is simulator-only and off the mission path.",
        ),
        (ApprovalGate.PHYSICAL_HARDWARE, "Prohibited; no hardware control exists."),
        (
            ApprovalGate.CAMERA_OR_MICROPHONE,
            "Camera preview is browser-local and user-initiated; microphone is never used.",
        ),
        (ApprovalGate.COMMIT, "Human-authorized only."),
        (ApprovalGate.PUSH, "Human-authorized only."),
        (ApprovalGate.PULL_REQUEST, "Human-authorized only."),
        (ApprovalGate.MERGE, "Human-authorized only."),
        (ApprovalGate.DEPLOYMENT, "No deployment surface exists."),
        (ApprovalGate.PUBLISHING, "No publishing surface exists."),
        (
            ApprovalGate.KNOWLEDGE_UPGRADE,
            "Research learning promotion requires explicit human approval.",
        ),
        (ApprovalGate.RUNTIME_UPGRADE, "No self-modification or updater exists."),
    )
)


OFFLINE_BOUNDARY_STATEMENTS: tuple[str, ...] = (
    "Deterministic local work (missions, verification, replay, this catalog) "
    "operates fully offline.",
    "Network sources (CelesTrak, JPL) are disabled by default and must be "
    "explicitly enabled per source.",
    "Credentials are never stored in laboratory metadata or manifests.",
    "When a connected window is enabled, external calls go through governed "
    "source connectors with provenance and caching.",
)


class LaboratoryCatalogProjection(BaseModel):
    """The single deterministic projection consumed by both API and Workbench."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["laboratory-catalog-v1"] = LABORATORY_CATALOG_SCHEMA_VERSION
    generated_from: Literal["deterministic-laboratory-registry"] = (
        "deterministic-laboratory-registry"
    )
    capability_principle: str = CAPABILITY_IS_NOT_PERMISSION
    laboratories: tuple[LaboratoryManifest, ...]
    planned_laboratories: tuple[PlannedLaboratoryProjection, ...]
    mission_flow: tuple[MissionFlowStage, ...]
    evidence_chain: tuple[EvidenceChainLink, ...]
    safety_boundaries: tuple[SafetyBoundary, ...]
    offline_boundary_statements: tuple[str, ...]


def build_default_registry() -> LaboratoryRegistry:
    """A fresh registry holding the built-in laboratories (explicit, no discovery)."""
    registry = LaboratoryRegistry()
    registry.register(build_development_laboratory_manifest())
    return registry


def build_catalog_projection(registry: LaboratoryRegistry) -> LaboratoryCatalogProjection:
    """Deterministic catalog projection from registry data + labelled static metadata."""
    return LaboratoryCatalogProjection(
        laboratories=registry.list_manifests(),
        planned_laboratories=PLANNED_LABORATORIES,
        mission_flow=GOVERNED_MISSION_FLOW,
        evidence_chain=EVIDENCE_CHAIN,
        safety_boundaries=SAFETY_BOUNDARIES,
        offline_boundary_statements=OFFLINE_BOUNDARY_STATEMENTS,
    )
