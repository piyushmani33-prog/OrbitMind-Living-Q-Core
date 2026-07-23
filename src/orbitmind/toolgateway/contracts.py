"""Frozen, non-executing Controlled Tool Gateway v0 contracts."""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic import ValidationError as PydanticValidationError

from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import ensure_utc

TOOL_GATEWAY_SCHEMA_VERSION: Final = "tool-gateway-v0"
TOOL_GATEWAY_POLICY_VERSION: Final = "tool-gateway-v0"
_ID = r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$"
_TOKEN = r"^[a-z][a-z0-9_-]{2,63}$"
_TOOL_ID = r"^[a-z][a-z0-9_]{2,63}$"
_VERSION = r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$"
_HASH = r"^[0-9a-f]{64}$"


class ToolGatewayContractError(ValidationError):
    code = "tool_gateway_contract_error"


class ToolClass(StrEnum):
    REPOSITORY_READ = "repository_read"
    LOCAL_VALIDATION = "local_validation"


class AdapterKind(StrEnum):
    LOCAL_DETERMINISTIC = "local_deterministic"


class ToolAvailability(StrEnum):
    AVAILABLE = "available"
    DISABLED = "disabled"


class GatewayNetworkPolicy(StrEnum):
    FORBIDDEN = "forbidden"


class GatewayFilesystemPolicy(StrEnum):
    NONE = "none"
    READ_ONLY_REPOSITORY = "read_only_repository"


class GatewayProcessPolicy(StrEnum):
    FORBIDDEN = "forbidden"


class GatewayExternalCommunicationPolicy(StrEnum):
    FORBIDDEN = "forbidden"


class GatewayRiskClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class GatewayOutcome(StrEnum):
    ELIGIBLE = "eligible"
    DENIED = "denied"
    APPROVAL_REQUIRED = "approval_required"


class GatewayReasonCode(StrEnum):
    OWNER_MISMATCH = "owner_mismatch"
    ACTOR_MISMATCH = "actor_mismatch"
    UNKNOWN_TOOL = "unknown_tool"
    UNSUPPORTED_TOOL_VERSION = "unsupported_tool_version"
    FORBIDDEN_TOOL_CLASS = "forbidden_tool_class"
    INPUT_SCHEMA_MISMATCH = "input_schema_mismatch"
    TOOL_UNAVAILABLE = "tool_unavailable"
    ADMISSION_NOT_FOUND = "admission_not_found"
    ADMISSION_NOT_ADMITTED = "admission_not_admitted"
    ADMISSION_ACTOR_MISMATCH = "admission_actor_mismatch"
    ADMISSION_OPERATION_MISMATCH = "admission_operation_mismatch"
    EXPLICIT_HUMAN_APPROVAL_REQUIRED = "explicit_human_approval_required"
    ELIGIBLE_BY_POLICY = "eligible_by_policy"


_DETAILS: Final = MappingProxyType(
    {
        GatewayReasonCode.OWNER_MISMATCH: (
            "The proposal owner does not match the trusted context."
        ),
        GatewayReasonCode.ACTOR_MISMATCH: (
            "The proposal actor does not match the trusted context."
        ),
        GatewayReasonCode.UNKNOWN_TOOL: "The requested tool is not registered.",
        GatewayReasonCode.UNSUPPORTED_TOOL_VERSION: (
            "The requested tool version is not supported."
        ),
        GatewayReasonCode.FORBIDDEN_TOOL_CLASS: (
            "The requested tool class is forbidden in this version."
        ),
        GatewayReasonCode.INPUT_SCHEMA_MISMATCH: (
            "The input schema reference does not match the registered tool."
        ),
        GatewayReasonCode.TOOL_UNAVAILABLE: "The requested tool is currently unavailable.",
        GatewayReasonCode.ADMISSION_NOT_FOUND: (
            "No matching admission record was found in the owner scope."
        ),
        GatewayReasonCode.ADMISSION_NOT_ADMITTED: ("The referenced operation was not admitted."),
        GatewayReasonCode.ADMISSION_ACTOR_MISMATCH: (
            "The admission record does not cover the trusted actor."
        ),
        GatewayReasonCode.ADMISSION_OPERATION_MISMATCH: (
            "The admission record does not cover the requested tool operation."
        ),
        GatewayReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED: (
            "This tool proposal requires explicit human approval before it may proceed."
        ),
        GatewayReasonCode.ELIGIBLE_BY_POLICY: (
            "The tool proposal is eligible by policy for a future controlled adapter boundary."
        ),
    }
)


def outcome_for_reason(reason: GatewayReasonCode) -> GatewayOutcome:
    if reason is GatewayReasonCode.ELIGIBLE_BY_POLICY:
        return GatewayOutcome.ELIGIBLE
    if reason is GatewayReasonCode.EXPLICIT_HUMAN_APPROVAL_REQUIRED:
        return GatewayOutcome.APPROVAL_REQUIRED
    return GatewayOutcome.DENIED


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _safe(value: str, name: str) -> str:
    if any(
        character == "\x7f" or unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
        for character in value
    ):
        raise ValueError(f"{name} must be safe single-line text")
    if any(fragment in value for fragment in ("://", "\\", "/", "..", "*")):
        raise ValueError(f"{name} must not contain path, URL, or wildcard content")
    return value


class ToolDescriptor(_Model):
    schema_version: Literal["tool-gateway-v0"] = TOOL_GATEWAY_SCHEMA_VERSION
    tool_id: str = Field(pattern=_TOOL_ID)
    tool_version: str = Field(pattern=_VERSION)
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=300)
    tool_class: ToolClass
    adapter_kind: AdapterKind
    input_schema_identifier: str = Field(pattern=_TOKEN)
    output_schema_identifier: str = Field(pattern=_TOKEN)
    risk_class: GatewayRiskClass
    network_policy: GatewayNetworkPolicy
    filesystem_policy: GatewayFilesystemPolicy
    process_policy: GatewayProcessPolicy
    external_communication_policy: GatewayExternalCommunicationPolicy
    human_approval_requirement: bool
    availability: ToolAvailability

    @field_validator("display_name", "description")
    @classmethod
    def _safe_text(cls, value: str, info: object) -> str:
        return _safe(value, getattr(info, "field_name", "text"))


class ToolInvocationProposal(_Model):
    schema_version: Literal["tool-gateway-v0"] = TOOL_GATEWAY_SCHEMA_VERSION
    proposal_id: str = Field(pattern=_ID)
    owner_id: str = Field(pattern=_ID)
    actor_id: str = Field(pattern=_ID)
    admission_id: str = Field(pattern=_ID)
    tool_id: str = Field(pattern=_TOOL_ID)
    tool_version: str = Field(pattern=_VERSION)
    input_schema_reference: str = Field(pattern=_TOKEN)
    purpose: str = Field(min_length=1, max_length=300)
    requested_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=200)

    @field_validator("requested_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, value: str) -> str:
        return _safe(value, "purpose")

    @field_validator("idempotency_key")
    @classmethod
    def _key(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("idempotency_key must not have surrounding whitespace")
        return value


class GatewayEvaluationContext(_Model):
    authoritative_owner_id: str = Field(pattern=_ID)
    authoritative_actor_id: str = Field(pattern=_ID)
    evaluated_at: datetime
    policy_version: Literal["tool-gateway-v0"] = TOOL_GATEWAY_POLICY_VERSION

    @field_validator("evaluated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


class AdmissionFinding(_Model):
    found: bool
    admitted: bool
    actor_id: str | None = Field(default=None, pattern=_ID)
    operation_kind: str | None = Field(default=None, pattern=_TOOL_ID)
    admission_record_identity: str | None = Field(default=None, pattern=_HASH)

    @model_validator(mode="after")
    def _consistent(self) -> AdmissionFinding:
        if self.admitted and not self.found:
            raise ValueError("admitted requires found")
        if self.admission_record_identity is not None and not self.found:
            raise ValueError("identity requires found")
        return self


class GatewayDecision(_Model):
    outcome: GatewayOutcome
    primary_reason_code: GatewayReasonCode
    reason_codes: tuple[GatewayReasonCode, ...] = Field(min_length=1, max_length=8)
    policy_version: Literal["tool-gateway-v0"] = TOOL_GATEWAY_POLICY_VERSION
    evaluated_at: datetime
    detail: str = Field(min_length=1, max_length=200)

    @field_validator("evaluated_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _consistent(self) -> GatewayDecision:
        if self.reason_codes[-1] is not self.primary_reason_code:
            raise ValueError("primary reason must be last")
        if self.outcome is not outcome_for_reason(self.primary_reason_code):
            raise ValueError("outcome does not match primary reason")
        if self.detail != _DETAILS[self.primary_reason_code]:
            raise ValueError("detail does not match primary reason")
        return self


class GatewayDecisionRecord(_Model):
    schema_version: Literal["tool-gateway-v0"] = TOOL_GATEWAY_SCHEMA_VERSION
    gateway_decision_id: str = Field(pattern=_ID)
    owner_id: str = Field(pattern=_ID)
    proposal_id: str = Field(pattern=_ID)
    actor_id: str = Field(pattern=_ID)
    tool_id: str = Field(pattern=_TOOL_ID)
    tool_version: str = Field(pattern=_VERSION)
    descriptor_checksum: str | None = Field(default=None, pattern=_HASH)
    referenced_admission_id: str = Field(pattern=_ID)
    resolved_admission_id: str | None = Field(default=None, pattern=_ID)
    admission_record_identity: str | None = Field(default=None, pattern=_HASH)
    outcome: GatewayOutcome
    primary_reason_code: GatewayReasonCode
    reason_codes: tuple[GatewayReasonCode, ...] = Field(min_length=1, max_length=8)
    policy_version: Literal["tool-gateway-v0"] = TOOL_GATEWAY_POLICY_VERSION
    evaluated_at: datetime
    requested_at: datetime
    proposal_fingerprint: str = Field(pattern=_HASH)
    decision_checksum: str = Field(pattern=_HASH)
    created_at: datetime

    @field_validator("evaluated_at", "requested_at", "created_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)


def tool_gateway_canonical_json(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def descriptor_checksum(descriptor: ToolDescriptor) -> str:
    return sha256(
        b"orbitmind-tool-descriptor-v1\x00" + tool_gateway_canonical_json(descriptor).encode()
    ).hexdigest()


def fingerprint_source(proposal: ToolInvocationProposal, context: GatewayEvaluationContext) -> str:
    data = proposal.model_dump(mode="json", exclude={"idempotency_key"})
    data["authoritative_actor_id"] = context.authoritative_actor_id
    data["authoritative_owner_id"] = context.authoritative_owner_id
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def decision_checksum_source(
    *,
    policy_version: str,
    proposal_fingerprint: str,
    descriptor_checksum: str | None,
    admission_record_identity: str | None,
    outcome: GatewayOutcome,
    reason_codes: tuple[GatewayReasonCode, ...],
    evaluated_at: datetime,
) -> str:
    return json.dumps(
        {
            "admission_record_identity": admission_record_identity,
            "descriptor_checksum": descriptor_checksum,
            "evaluated_at": ensure_utc(evaluated_at).isoformat(),
            "outcome": outcome.value,
            "policy_version": policy_version,
            "proposal_fingerprint": proposal_fingerprint,
            "reason_codes": [reason.value for reason in reason_codes],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def parse_tool_gateway_json(model: type[_Model], payload: str) -> _Model:
    try:
        return model.model_validate_json(payload)
    except PydanticValidationError as error:
        raise ToolGatewayContractError("tool gateway contract validation failed") from error
