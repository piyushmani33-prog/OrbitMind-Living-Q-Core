"""Versioned, immutable Laboratory Manifest contracts.

A ``LaboratoryManifest`` is a governed metadata contract describing one
laboratory: its identity, domain, declared capabilities, postures, approval
gates and limitations. It is **not executable authority**: manifests carry no
import paths, commands, code, credentials or secrets, and registering one
grants nothing.

Contracts here are framework-independent (Pydantic only — no FastAPI, no
persistence, no I/O) so they can be validated and serialized deterministically
anywhere in the platform.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictStr,
    ValidationInfo,
    field_validator,
    model_validator,
)

from orbitmind.laboratory.capabilities import CapabilityDeclaration

LABORATORY_MANIFEST_SCHEMA_VERSION: Final = "laboratory-manifest-v1"
LABORATORY_SUPPORTED_MANIFEST_SCHEMA_VERSIONS: Final[frozenset[str]] = frozenset(
    {LABORATORY_MANIFEST_SCHEMA_VERSION}
)

# This is the Laboratory Framework contract version, deliberately distinct from
# both the package version and the manifest schema version.
_MAX_FRAMEWORK_VERSION_COMPONENT: Final = 1_000_000
_MAX_FRAMEWORK_VERSION_LENGTH: Final = 23
_FRAMEWORK_VERSION_PATTERN: Final = (
    r"^(0|[1-9][0-9]{0,6})\.(0|[1-9][0-9]{0,6})\.(0|[1-9][0-9]{0,6})$"
)

# Category / service identifiers are bounded kebab-case tokens: no path
# separators, dots, spaces or executable references can appear in them.
_KEBAB_PATTERN = r"^[a-z][a-z0-9-]{1,63}$"
_LABORATORY_ID_PATTERN = r"^[a-z][a-z0-9-]{2,47}$"
_SEMVER_PATTERN = r"^\d{1,4}\.\d{1,4}\.\d{1,4}$"


def is_supported_laboratory_manifest_schema_version(value: object) -> bool:
    """Whether ``value`` is one of the explicitly supported manifest schemas."""

    return type(value) is str and value in LABORATORY_SUPPORTED_MANIFEST_SCHEMA_VERSIONS


@dataclass(frozen=True, order=True)
class LaboratoryFrameworkVersion:
    """Strict, dependency-free version of the Laboratory Framework contract."""

    major: int
    minor: int
    patch: int

    def __post_init__(self) -> None:
        for component_name, component in (
            ("major", self.major),
            ("minor", self.minor),
            ("patch", self.patch),
        ):
            if type(component) is not int or not 0 <= component <= _MAX_FRAMEWORK_VERSION_COMPONENT:
                raise ValueError(
                    f"{component_name} must be an integer from 0 to "
                    f"{_MAX_FRAMEWORK_VERSION_COMPONENT}"
                )

    @classmethod
    def parse(cls, value: object) -> Self:
        """Parse the canonical ``MAJOR.MINOR.PATCH`` grammar without coercion."""

        if type(value) is not str:
            raise ValueError("framework version must be a string")
        if len(value) > _MAX_FRAMEWORK_VERSION_LENGTH:
            raise ValueError("framework version exceeds the maximum length")
        match = re.fullmatch(_FRAMEWORK_VERSION_PATTERN, value)
        if match is None:
            raise ValueError("framework version must use canonical MAJOR.MINOR.PATCH form")
        return cls(*(int(component) for component in match.groups()))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


LABORATORY_FRAMEWORK_CONTRACT_VERSION: Final = LaboratoryFrameworkVersion.parse("1.0.0")


class LaboratoryDomain(StrEnum):
    """Scientific/engineering domain a laboratory belongs to."""

    DEVELOPMENT = "development"
    RESEARCH = "research"
    QUANTUM = "quantum"
    ROBOTICS = "robotics"
    SPACE = "space"
    MANUFACTURING = "manufacturing"


class LaboratoryImplementationStatus(StrEnum):
    """How much of a laboratory actually exists in the current runtime."""

    # Registered: catalog + governance metadata only; no execution surface.
    CATALOG_FOUNDATION = "catalog-foundation"
    # A real manifest exists but nothing operational is implemented.
    PLANNED = "planned"


class NetworkPosture(StrEnum):
    """Network stance of a laboratory's (future) work."""

    OFFLINE_ONLY = "offline-only"
    PERMISSIONED_WINDOW_REQUIRED = "permissioned-window-required"


class HardwarePosture(StrEnum):
    """Physical-hardware stance. v1 laboratories touch no hardware."""

    NO_HARDWARE_ACCESS = "no-hardware-access"


class PersistencePosture(StrEnum):
    """Persistence stance: laboratories own no independent persisted truth."""

    NO_LABORATORY_PERSISTENCE = "no-laboratory-persistence"
    READS_EXISTING_RECORDS_ONLY = "reads-existing-records-only"


class ApprovalGate(StrEnum):
    """Sensitive boundaries that always require explicit human approval."""

    NETWORK_ACCESS = "network_access"
    EXTERNAL_AI = "external_ai"
    REPOSITORY_WRITE = "repository_write"
    DEPENDENCY_INSTALLATION = "dependency_installation"
    CLOUD_SERVICE = "cloud_service"
    QUANTUM_HARDWARE = "quantum_hardware"
    PHYSICAL_HARDWARE = "physical_hardware"
    CAMERA_OR_MICROPHONE = "camera_or_microphone"
    COMMIT = "commit"
    PUSH = "push"
    PULL_REQUEST = "pull_request"
    MERGE = "merge"
    DEPLOYMENT = "deployment"
    PUBLISHING = "publishing"
    KNOWLEDGE_UPGRADE = "knowledge_upgrade"
    RUNTIME_UPGRADE = "runtime_upgrade"


class ReplayRequirement(StrEnum):
    """Replay contract imposed on any future laboratory execution."""

    # Future executions must either replay deterministically or be explicitly
    # classified as non-deterministic re-evaluation — never conflated.
    DETERMINISTIC_REPLAY_REQUIRED = "deterministic-replay-required"
    NOT_APPLICABLE = "not-applicable"


class DeprecationState(StrEnum):
    """Lifecycle state of the manifest contract itself."""

    ACTIVE_CONTRACT = "active-contract"
    DEPRECATED = "deprecated"


class ResourceBoundaries(BaseModel):
    """Declared bounds any future execution inside the laboratory must respect."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_concurrent_missions: int = Field(ge=0, le=64)
    max_mission_wall_clock_seconds: int = Field(ge=1, le=86_400)
    notes: str = Field(min_length=1, max_length=300)


class CompatibilityInfo(BaseModel):
    """Platform compatibility statement for the manifest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    platform_version_baseline: str = Field(pattern=_SEMVER_PATTERN)
    mission_contract: str = Field(min_length=1, max_length=120)


class FrameworkCompatibilityRange(BaseModel):
    """Structured inclusive/exclusive compatibility range for framework contracts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    minimum_inclusive: StrictStr = Field(
        min_length=5,
        max_length=_MAX_FRAMEWORK_VERSION_LENGTH,
    )
    maximum_exclusive: StrictStr = Field(
        min_length=5,
        max_length=_MAX_FRAMEWORK_VERSION_LENGTH,
    )

    @field_validator("minimum_inclusive", "maximum_exclusive", mode="before")
    @classmethod
    def _canonical_framework_version(cls, value: object) -> str:
        return str(LaboratoryFrameworkVersion.parse(value))

    @model_validator(mode="after")
    def _minimum_precedes_maximum(self) -> Self:
        if self.minimum_version >= self.maximum_version:
            raise ValueError("minimum_inclusive must be strictly less than maximum_exclusive")
        return self

    @property
    def minimum_version(self) -> LaboratoryFrameworkVersion:
        """The validated inclusive minimum as an immutable comparable value."""

        return LaboratoryFrameworkVersion.parse(self.minimum_inclusive)

    @property
    def maximum_version(self) -> LaboratoryFrameworkVersion:
        """The validated exclusive maximum as an immutable comparable value."""

        return LaboratoryFrameworkVersion.parse(self.maximum_exclusive)

    def contains(self, candidate: LaboratoryFrameworkVersion | str) -> bool:
        """Return the deterministic inclusive-minimum/exclusive-maximum decision."""

        candidate_version = (
            candidate
            if isinstance(candidate, LaboratoryFrameworkVersion)
            else LaboratoryFrameworkVersion.parse(candidate)
        )
        return self.minimum_version <= candidate_version < self.maximum_version


class AdapterDeclaration(BaseModel):
    """A declared (never connected in v1) adapter boundary.

    Adapters are named integration points only — no import path, command or
    endpoint appears here, and ``connected`` is pinned to ``False``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    adapter_id: str = Field(pattern=_KEBAB_PATTERN)
    purpose: str = Field(min_length=1, max_length=300)
    approval_posture_note: str = Field(min_length=1, max_length=300)
    connected: Literal[False] = False


def _sorted_unique_strings(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} entries must be unique")
    return tuple(sorted(values))


class LaboratoryManifest(BaseModel):
    """Immutable, versioned contract describing one laboratory.

    Collection fields are normalized to deterministic sorted order at
    validation time, so serialization of equal manifests is byte-stable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: StrictStr = LABORATORY_MANIFEST_SCHEMA_VERSION
    laboratory_id: str = Field(pattern=_LABORATORY_ID_PATTERN)
    display_name: str = Field(min_length=1, max_length=80)
    laboratory_version: str = Field(pattern=_SEMVER_PATTERN)
    domain: LaboratoryDomain
    description: str = Field(min_length=1, max_length=600)
    implementation_status: LaboratoryImplementationStatus
    capabilities: tuple[CapabilityDeclaration, ...] = Field(min_length=0, max_length=24)
    accepted_goal_categories: tuple[str, ...] = Field(max_length=12)
    required_deterministic_services: tuple[str, ...] = Field(max_length=12)
    adapters: tuple[AdapterDeclaration, ...] = Field(default=(), max_length=8)
    produced_artifact_categories: tuple[str, ...] = Field(max_length=16)
    produced_evidence_categories: tuple[str, ...] = Field(max_length=16)
    network_posture: NetworkPosture
    hardware_posture: HardwarePosture
    persistence_posture: PersistencePosture
    approval_gates: tuple[ApprovalGate, ...] = Field(max_length=len(ApprovalGate))
    replay_support: ReplayRequirement
    verification_requirements: tuple[str, ...] = Field(min_length=1, max_length=8)
    resource_boundaries: ResourceBoundaries
    framework_compatibility: FrameworkCompatibilityRange
    compatibility: CompatibilityInfo
    # Limitations are mandatory: an honest manifest always states what it is not.
    limitations: tuple[str, ...] = Field(min_length=1, max_length=12)
    deprecation_state: DeprecationState = DeprecationState.ACTIVE_CONTRACT

    @field_validator("capabilities")
    @classmethod
    def _capabilities_unique_and_sorted(
        cls, value: tuple[CapabilityDeclaration, ...]
    ) -> tuple[CapabilityDeclaration, ...]:
        kinds = [declaration.capability for declaration in value]
        if len(set(kinds)) != len(kinds):
            raise ValueError("capabilities must declare each capability at most once")
        return tuple(sorted(value, key=lambda declaration: declaration.capability.value))

    @field_validator("schema_version")
    @classmethod
    def _supported_schema_version(cls, value: str) -> str:
        if not is_supported_laboratory_manifest_schema_version(value):
            raise ValueError("laboratory manifest schema version is not supported")
        return value

    @field_validator("adapters")
    @classmethod
    def _adapters_unique_and_sorted(
        cls, value: tuple[AdapterDeclaration, ...]
    ) -> tuple[AdapterDeclaration, ...]:
        adapter_ids = [adapter.adapter_id for adapter in value]
        if len(set(adapter_ids)) != len(adapter_ids):
            raise ValueError("adapters must declare each adapter_id at most once")
        return tuple(sorted(value, key=lambda adapter: adapter.adapter_id))

    @field_validator("approval_gates")
    @classmethod
    def _gates_unique_and_sorted(cls, value: tuple[ApprovalGate, ...]) -> tuple[ApprovalGate, ...]:
        if len(set(value)) != len(value):
            raise ValueError("approval_gates entries must be unique")
        return tuple(sorted(value, key=lambda gate: gate.value))

    @field_validator(
        "accepted_goal_categories",
        "required_deterministic_services",
        "produced_artifact_categories",
        "produced_evidence_categories",
    )
    @classmethod
    def _kebab_token_collections(
        cls, value: tuple[str, ...], info: ValidationInfo
    ) -> tuple[str, ...]:
        field_name = info.field_name or "collection"
        for token in value:
            if not re.fullmatch(_KEBAB_PATTERN, token):
                raise ValueError(
                    f"{field_name} entries must be bounded kebab-case tokens; got {token!r}"
                )
        return _sorted_unique_strings(value, field_name=field_name)

    @field_validator("verification_requirements", "limitations")
    @classmethod
    def _bounded_statements(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        field_name = info.field_name or "collection"
        for statement in value:
            if not 1 <= len(statement) <= 300:
                raise ValueError(f"{field_name} statements must be 1..300 characters")
        if len(set(value)) != len(value):
            raise ValueError(f"{field_name} statements must be unique")
        return value

    def canonical_json(self) -> str:
        """Stable JSON serialization of the full manifest semantic contract."""
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
