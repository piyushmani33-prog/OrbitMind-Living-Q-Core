"""Strict, immutable Operation Admission v0 contracts (U7.4).

Every model here is frozen, rejects unknown fields, rejects implicit type
coercion (``strict=True``), bounds every string, requires timezone-aware UTC
timestamps, and carries an explicit schema version. No field can carry a secret,
credential, token, raw prompt, command body, tool argument, callable, or import
path — the schema simply has no place for one, and free-text fields reject
path/URL/wildcard content. Identifiers and timestamps are supplied explicitly by
callers; this layer never generates ids and never reads a clock.

The admission **policy version** is a module-owned constant: a proposal can never
supply or influence it. The operation profile (the required capability, expected
side-effect/risk class, and whether Authority and/or explicit human approval are
required) is derived authoritatively from ``operation_kind``; any proposal echo
must agree exactly.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Annotated, Final, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc

ADMISSION_SCHEMA_VERSION: Final = "operation-admission-v0"

#: The single authoritative policy version. A proposal cannot supply or influence
#: it; ``AdmissionEvaluationContext.policy_version`` must equal this exact value.
OPERATION_ADMISSION_POLICY_VERSION: Final = "operation-admission-v0"

# Canonical grammars (aligned with the authority contracts). None can express
# "*", whitespace, path separators, or control characters.
_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$"
_CAPABILITY_PATTERN: Final = r"^[a-z][a-z0-9_]{2,63}$"
# operation_kind is a bounded safe TOKEN (not a native enum) so an unknown but
# structurally valid token is resolvable to ``unsupported_operation_kind`` rather
# than rejected as malformed input.
_OPERATION_KIND_PATTERN: Final = r"^[a-z][a-z0-9_]{2,63}$"
_KEBAB_TOKEN_PATTERN: Final = r"^[a-z][a-z0-9-]{1,63}$"
_RESOURCE_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9._:-]{0,126}$"
_PROVENANCE_PATTERN: Final = r"^[a-z0-9][a-z0-9._:-]{0,126}$"

_FORBIDDEN_TEXT_FRAGMENTS: Final = ("://", "\\", "/", "..")
_FORBIDDEN_TEXT_CATEGORIES: Final = ("Cc", "Cf", "Zl", "Zp")


class AdmissionContractError(ValidationError):
    """Typed fail-closed error for a rejected admission payload."""

    code = "admission_contract_error"


def _reject_dot_dot(value: str) -> str:
    if ".." in value:
        raise ValueError("value must not contain '..'")
    return value


def _validate_safe_text(value: str, *, field_name: str) -> str:
    """Bounded human text: printable, single-line, no path/URL/wildcard content."""
    for character in value:
        if character == "\x7f" or unicodedata.category(character) in _FORBIDDEN_TEXT_CATEGORIES:
            raise ValueError(
                f"{field_name} must be a single line without control or invisible characters"
            )
    for fragment in _FORBIDDEN_TEXT_FRAGMENTS:
        if fragment in value:
            raise ValueError(f"{field_name} must not contain path or URL fragments ({fragment!r})")
    if "*" in value:
        raise ValueError(f"{field_name} must not contain wildcards")
    return value


_ResourceIdField = Annotated[
    str, Field(pattern=_RESOURCE_ID_PATTERN), AfterValidator(_reject_dot_dot)
]
_ProvenanceField = Annotated[
    str, Field(pattern=_PROVENANCE_PATTERN), AfterValidator(_reject_dot_dot)
]


class ProposalActorType(StrEnum):
    """Kind of principal that may act. Mirrors the authority subject vocabulary."""

    OPERATOR = "operator"
    AGENT = "agent"
    LABORATORY = "laboratory"
    TOOL = "tool"
    ADAPTER = "adapter"


class AdmissionOperationKind(StrEnum):
    """The bounded v0 operation taxonomy the policy recognizes."""

    READ_REPOSITORY = "read_repository"
    RUN_LOCAL_VALIDATION = "run_local_validation"
    PROPOSE_FILE_CHANGE = "propose_file_change"
    CREATE_ISOLATED_WORKTREE = "create_isolated_worktree"
    INSTALL_DEPENDENCY = "install_dependency"
    ACCESS_SECRET = "access_secret"
    CALL_EXTERNAL_PROVIDER = "call_external_provider"
    PUSH_BRANCH = "push_branch"
    CREATE_PULL_REQUEST = "create_pull_request"
    CLOUD_QUANTUM_EXECUTION = "cloud_quantum_execution"
    MERGE_PULL_REQUEST = "merge_pull_request"
    DEPLOY = "deploy"
    SPEND_MONEY = "spend_money"
    SEND_EXTERNAL_COMMUNICATION = "send_external_communication"
    HARDWARE_CONTROL = "hardware_control"


class AdmissionSideEffectClass(StrEnum):
    """Coarse, bounded side-effect classification."""

    NONE = "none"
    LOCAL_READ = "local_read"
    LOCAL_WRITE_PROPOSAL = "local_write_proposal"
    ISOLATED_WORKTREE = "isolated_worktree"
    EXTERNAL_EFFECT = "external_effect"
    IRREVERSIBLE_REAL_WORLD = "irreversible_real_world"


class AdmissionRiskClass(StrEnum):
    """Coarse, bounded risk classification."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AdmissionOutcome(StrEnum):
    """The exactly-three v0 admission outcomes."""

    ADMITTED = "admitted"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"


class AdmissionReasonCode(StrEnum):
    """Stable, deterministic, public-safe admission reason codes.

    ``malformed_proposal`` and ``authority_owner_mismatch`` are intentionally NOT
    here: malformed input fails at the contract boundary (never persisted), and
    cross-owner existence is never revealed (an owner-scoped miss is
    ``authority_not_found``).
    """

    OWNER_MISMATCH = "owner_mismatch"
    ACTOR_MISMATCH = "actor_mismatch"
    UNSUPPORTED_OPERATION_KIND = "unsupported_operation_kind"
    FORBIDDEN_OPERATION_KIND = "forbidden_operation_kind"
    OPERATION_PROFILE_MISMATCH = "operation_profile_mismatch"
    AUTHORITY_REQUIRED = "authority_required"
    AUTHORITY_NOT_FOUND = "authority_not_found"
    AUTHORITY_ACTOR_MISMATCH = "authority_actor_mismatch"
    CAPABILITY_MISMATCH = "capability_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    AUTHORITY_NOT_YET_VALID = "authority_not_yet_valid"
    AUTHORITY_EXPIRED = "authority_expired"
    AUTHORITY_REVOKED = "authority_revoked"
    EXPLICIT_HUMAN_APPROVAL_REQUIRED = "explicit_human_approval_required"
    ADMITTED_BY_POLICY = "admitted_by_policy"


# Fixed, non-interpolated public-safe decision text (never LLM-generated).
_ADMISSION_DETAILS: Final[MappingProxyType[AdmissionReasonCode, str]] = MappingProxyType(
    {
        AdmissionReasonCode.OWNER_MISMATCH: (
            "The proposal owner does not match the trusted context."
        ),
        AdmissionReasonCode.ACTOR_MISMATCH: (
            "The proposal actor does not match the trusted context."
        ),
        AdmissionReasonCode.UNSUPPORTED_OPERATION_KIND: (
            "The operation kind is not supported in this version."
        ),
        AdmissionReasonCode.FORBIDDEN_OPERATION_KIND: (
            "The operation kind is forbidden in this version."
        ),
        AdmissionReasonCode.OPERATION_PROFILE_MISMATCH: (
            "A proposal value disagrees with the authoritative operation profile."
        ),
        AdmissionReasonCode.AUTHORITY_REQUIRED: (
            "This operation requires authority evidence, but none was referenced."
        ),
        AdmissionReasonCode.AUTHORITY_NOT_FOUND: (
            "No matching authority grant was found in the owner scope."
        ),
        AdmissionReasonCode.AUTHORITY_ACTOR_MISMATCH: (
            "The authority grant does not authorize the proposed actor."
        ),
        AdmissionReasonCode.CAPABILITY_MISMATCH: (
            "The authority grant does not cover the required capability."
        ),
        AdmissionReasonCode.SCOPE_MISMATCH: (
            "The authority grant does not cover the requested scope."
        ),
        AdmissionReasonCode.AUTHORITY_NOT_YET_VALID: (
            "The authority grant is not yet valid at the evaluation time."
        ),
        AdmissionReasonCode.AUTHORITY_EXPIRED: (
            "The authority grant is expired at the evaluation time."
        ),
        AdmissionReasonCode.AUTHORITY_REVOKED: (
            "The authority grant is revoked at the evaluation time."
        ),
        AdmissionReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED: (
            "This operation requires explicit human approval before it may proceed."
        ),
        AdmissionReasonCode.ADMITTED_BY_POLICY: (
            "The operation is admissible by policy for controlled pipeline entry."
        ),
    }
)

# Reason code -> outcome. admitted_by_policy admits; explicit_human_approval_required
# withholds; every other reason denies (fail-closed).
_OUTCOME_BY_REASON: Final[MappingProxyType[AdmissionReasonCode, AdmissionOutcome]] = (
    MappingProxyType(
        {
            AdmissionReasonCode.ADMITTED_BY_POLICY: AdmissionOutcome.ADMITTED,
            AdmissionReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED: (
                AdmissionOutcome.APPROVAL_REQUIRED
            ),
        }
    )
)


def outcome_for_reason(reason: AdmissionReasonCode) -> AdmissionOutcome:
    """Deterministic outcome for a primary reason code (fail-closed to denied)."""
    return _OUTCOME_BY_REASON.get(reason, AdmissionOutcome.DENIED)


def detail_for_reason(reason: AdmissionReasonCode) -> str:
    """Fixed public-safe detail text for a reason code."""
    return _ADMISSION_DETAILS[reason]


class _StrictAdmissionModel(BaseModel):
    """Shared configuration: frozen, closed, coercion-free."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ScopeConstraint(_StrictAdmissionModel):
    """One exact named constraint inside a proposed scope."""

    name: str = Field(pattern=_KEBAB_TOKEN_PATTERN)
    value: _ResourceIdField


class ProposalScope(_StrictAdmissionModel):
    """Exact proposed resource scope. No wildcard resource can be expressed."""

    resource_type: str = Field(pattern=_KEBAB_TOKEN_PATTERN)
    resource_id: _ResourceIdField
    constraints: tuple[ScopeConstraint, ...] = Field(default=(), max_length=8)

    @field_validator("constraints")
    @classmethod
    def _constraints_sorted_unique(
        cls, value: tuple[ScopeConstraint, ...]
    ) -> tuple[ScopeConstraint, ...]:
        names = [constraint.name for constraint in value]
        if len(set(names)) != len(names):
            raise ValueError("constraint names must be unique")
        return tuple(sorted(value, key=lambda constraint: constraint.name))


class OperationProfile(_StrictAdmissionModel):
    """The authoritative, immutable policy profile for one operation kind."""

    required_capability: str = Field(pattern=_CAPABILITY_PATTERN)
    side_effect_class: AdmissionSideEffectClass
    risk_class: AdmissionRiskClass
    authority_required: bool
    approval_required: bool
    forbidden_in_v0: bool


def _profile(
    capability: str,
    side_effect: AdmissionSideEffectClass,
    risk: AdmissionRiskClass,
    *,
    authority: bool = False,
    approval: bool = False,
    forbidden: bool = False,
) -> OperationProfile:
    return OperationProfile(
        required_capability=capability,
        side_effect_class=side_effect,
        risk_class=risk,
        authority_required=authority,
        approval_required=approval,
        forbidden_in_v0=forbidden,
    )


_SE = AdmissionSideEffectClass
_RC = AdmissionRiskClass

#: Authoritative per-kind profiles. Deriving these from ``operation_kind`` (never
#: from caller input) prevents a proposal from reducing risk, side effects,
#: capability requirements, or approval requirements.
OPERATION_PROFILES: Final[MappingProxyType[AdmissionOperationKind, OperationProfile]] = (
    MappingProxyType(
        {
            AdmissionOperationKind.READ_REPOSITORY: _profile(
                "repository_read", _SE.LOCAL_READ, _RC.LOW
            ),
            AdmissionOperationKind.RUN_LOCAL_VALIDATION: _profile(
                "local_validation_run", _SE.NONE, _RC.LOW
            ),
            AdmissionOperationKind.PROPOSE_FILE_CHANGE: _profile(
                "repository_write_proposal", _SE.LOCAL_WRITE_PROPOSAL, _RC.MEDIUM, authority=True
            ),
            AdmissionOperationKind.CREATE_ISOLATED_WORKTREE: _profile(
                "worktree_create", _SE.ISOLATED_WORKTREE, _RC.MEDIUM, authority=True
            ),
            AdmissionOperationKind.INSTALL_DEPENDENCY: _profile(
                "dependency_install", _SE.EXTERNAL_EFFECT, _RC.HIGH, authority=True, approval=True
            ),
            AdmissionOperationKind.ACCESS_SECRET: _profile(
                "secret_access", _SE.EXTERNAL_EFFECT, _RC.HIGH, authority=True, approval=True
            ),
            AdmissionOperationKind.CALL_EXTERNAL_PROVIDER: _profile(
                "external_provider_call",
                _SE.EXTERNAL_EFFECT,
                _RC.HIGH,
                authority=True,
                approval=True,
            ),
            AdmissionOperationKind.PUSH_BRANCH: _profile(
                "branch_push", _SE.EXTERNAL_EFFECT, _RC.HIGH, authority=True, approval=True
            ),
            AdmissionOperationKind.CREATE_PULL_REQUEST: _profile(
                "pull_request_create", _SE.EXTERNAL_EFFECT, _RC.HIGH, authority=True, approval=True
            ),
            AdmissionOperationKind.CLOUD_QUANTUM_EXECUTION: _profile(
                "cloud_quantum_execute",
                _SE.EXTERNAL_EFFECT,
                _RC.CRITICAL,
                authority=True,
                approval=True,
            ),
            AdmissionOperationKind.MERGE_PULL_REQUEST: _profile(
                "pull_request_merge", _SE.IRREVERSIBLE_REAL_WORLD, _RC.CRITICAL, forbidden=True
            ),
            AdmissionOperationKind.DEPLOY: _profile(
                "deployment_execute", _SE.IRREVERSIBLE_REAL_WORLD, _RC.CRITICAL, forbidden=True
            ),
            AdmissionOperationKind.SPEND_MONEY: _profile(
                "funds_spend", _SE.IRREVERSIBLE_REAL_WORLD, _RC.CRITICAL, forbidden=True
            ),
            AdmissionOperationKind.SEND_EXTERNAL_COMMUNICATION: _profile(
                "external_communication_send",
                _SE.IRREVERSIBLE_REAL_WORLD,
                _RC.CRITICAL,
                forbidden=True,
            ),
            AdmissionOperationKind.HARDWARE_CONTROL: _profile(
                "hardware_control", _SE.IRREVERSIBLE_REAL_WORLD, _RC.CRITICAL, forbidden=True
            ),
        }
    )
)


class OperationProposal(_StrictAdmissionModel):
    """A bounded, immutable description of a proposed operation.

    ``owner_id`` and ``actor_id`` are claims re-checked against the trusted
    context; ``operation_kind`` is a bounded safe token resolved by the policy;
    ``requested_at`` is informational/auditable only and never controls any
    authority validity decision.
    """

    schema_version: Literal["operation-admission-v0"] = ADMISSION_SCHEMA_VERSION
    proposal_id: str = Field(pattern=_ID_PATTERN)
    owner_id: str = Field(pattern=_ID_PATTERN)
    actor_id: str = Field(pattern=_ID_PATTERN)
    actor_type: ProposalActorType
    operation_kind: str = Field(pattern=_OPERATION_KIND_PATTERN)
    requested_capability: str = Field(pattern=_CAPABILITY_PATTERN)
    requested_scope: ProposalScope
    side_effect_class: AdmissionSideEffectClass
    risk_class: AdmissionRiskClass
    purpose: str = Field(min_length=1, max_length=300)
    resource_target: str | None = Field(default=None, pattern=_RESOURCE_ID_PATTERN)
    requested_authority_grant_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    requested_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=200)
    provenance_refs: tuple[_ProvenanceField, ...] = Field(default=(), max_length=8)

    @field_validator("requested_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _safe_purpose(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="purpose")

    @field_validator("resource_target")
    @classmethod
    def _safe_resource_target(cls, value: str | None) -> str | None:
        return None if value is None else _reject_dot_dot(value)

    @field_validator("idempotency_key")
    @classmethod
    def _canonical_idempotency_key(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("idempotency_key must not have surrounding whitespace")
        return value

    @field_validator("provenance_refs")
    @classmethod
    def _provenance_sorted_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("provenance refs must be unique")
        return tuple(sorted(value))


class AdmissionEvaluationContext(_StrictAdmissionModel):
    """Trusted evaluation context supplied by the orchestration boundary.

    The proposal never supplies these values. ``policy_version`` must equal
    :data:`OPERATION_ADMISSION_POLICY_VERSION`; any other value fails closed.
    ``evaluated_at`` is the single injected trusted timestamp used for every
    time-dependent authority decision.
    """

    authoritative_owner_id: str = Field(pattern=_ID_PATTERN)
    authoritative_actor_id: str = Field(pattern=_ID_PATTERN)
    evaluated_at: datetime
    policy_version: Literal["operation-admission-v0"] = OPERATION_ADMISSION_POLICY_VERSION

    @field_validator("evaluated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class AuthorityFinding(_StrictAdmissionModel):
    """The orchestration-distilled result of an authority evaluation.

    Admission-native (carries no authority contract type). ``reason`` is set only
    when a required grant was referenced, resolved in the owner scope, but did not
    authorize the operation.
    """

    required: bool
    referenced: bool
    resolved: bool
    authorized: bool
    reason: AdmissionReasonCode | None = None
    resolved_grant_id: str | None = Field(default=None, pattern=_ID_PATTERN)

    @model_validator(mode="after")
    def _consistency(self) -> AuthorityFinding:
        if self.authorized and not (self.required and self.referenced and self.resolved):
            raise ValueError("authorized finding requires a resolved referenced required grant")
        if self.reason is not None and self.authorized:
            raise ValueError("an authorized finding carries no failure reason")
        if self.resolved_grant_id is not None and not self.resolved:
            raise ValueError("resolved_grant_id requires resolved=True")
        return self


class AdmissionDecision(_StrictAdmissionModel):
    """The deterministic result of one admission evaluation (policy output).

    Not a credential, token, or execution handle: an ``admitted`` decision
    confers nothing by itself.
    """

    outcome: AdmissionOutcome
    primary_reason_code: AdmissionReasonCode
    reason_codes: tuple[AdmissionReasonCode, ...] = Field(min_length=1, max_length=8)
    policy_version: Literal["operation-admission-v0"] = OPERATION_ADMISSION_POLICY_VERSION
    evaluated_at: datetime
    resolved_grant_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    detail: str = Field(min_length=1, max_length=200)

    @field_validator("evaluated_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _consistency(self) -> AdmissionDecision:
        if self.outcome is not outcome_for_reason(self.primary_reason_code):
            raise ValueError("outcome must match the primary reason code mapping")
        if self.reason_codes[-1] is not self.primary_reason_code:
            raise ValueError("the primary reason code must be the last (deciding) code")
        if self.detail != detail_for_reason(self.primary_reason_code):
            raise ValueError("detail must be the fixed text for the primary reason code")
        return self


class AdmissionRecord(_StrictAdmissionModel):
    """The immutable, owner-scoped admission evidence prepared for persistence.

    Excludes the storage-computed ``record_identity`` (the repository derives it
    from the canonical serialization of this record, avoiding self-reference).
    """

    schema_version: Literal["operation-admission-v0"] = ADMISSION_SCHEMA_VERSION
    admission_id: str = Field(pattern=_ID_PATTERN)
    owner_id: str = Field(pattern=_ID_PATTERN)
    proposal_id: str = Field(pattern=_ID_PATTERN)
    actor_id: str = Field(pattern=_ID_PATTERN)
    actor_type: ProposalActorType
    operation_kind: str = Field(pattern=_OPERATION_KIND_PATTERN)
    requested_capability: str = Field(pattern=_CAPABILITY_PATTERN)
    requested_scope: ProposalScope
    side_effect_class: AdmissionSideEffectClass
    risk_class: AdmissionRiskClass
    outcome: AdmissionOutcome
    primary_reason_code: AdmissionReasonCode
    reason_codes: tuple[AdmissionReasonCode, ...] = Field(min_length=1, max_length=8)
    policy_version: Literal["operation-admission-v0"] = OPERATION_ADMISSION_POLICY_VERSION
    evaluated_at: datetime
    requested_at: datetime
    requested_authority_grant_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    resolved_authority_grant_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    proposal_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime
    provenance_refs: tuple[str, ...] = Field(default=(), max_length=8)

    @field_validator("evaluated_at", "requested_at", "created_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


def admission_canonical_json(model: BaseModel) -> str:
    """Canonical deterministic serialization: sorted keys, compact UTF-8 JSON."""
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def fingerprint_source(proposal: OperationProposal, context: AdmissionEvaluationContext) -> str:
    """Canonical fingerprint input: normalized proposal content (excluding the
    idempotency key) bound to the trusted identity context. Excludes the decision
    and the evaluation time so a replay at a different instant shares the fingerprint."""
    content = proposal.model_dump(mode="json")
    content.pop("idempotency_key", None)
    payload = {
        "proposal": content,
        "context": {
            "authoritative_owner_id": context.authoritative_owner_id,
            "authoritative_actor_id": context.authoritative_actor_id,
        },
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def decision_checksum_source(
    *,
    policy_version: str,
    proposal_fingerprint: str,
    outcome: AdmissionOutcome,
    reason_codes: tuple[AdmissionReasonCode, ...],
    evaluated_at: datetime,
    resolved_grant_id: str | None,
) -> str:
    """Canonical decision-evidence input for the decision checksum."""
    payload = {
        "policy_version": policy_version,
        "proposal_fingerprint": proposal_fingerprint,
        "outcome": outcome.value,
        "reason_codes": [code.value for code in reason_codes],
        "evaluated_at": ensure_utc(evaluated_at).isoformat(),
        "resolved_grant_id": resolved_grant_id,
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def parse_admission_json[ModelT: BaseModel](model_type: type[ModelT], payload: str) -> ModelT:
    """Fail-closed JSON ingestion returning a typed admission error on rejection."""
    try:
        return model_type.model_validate_json(payload)
    except PydanticValidationError as error:
        raise AdmissionContractError(
            f"admission payload rejected for {model_type.__name__}"
        ) from error
