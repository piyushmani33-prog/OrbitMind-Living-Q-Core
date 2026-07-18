"""Strict, immutable authority contracts (U7.0).

Every model here is frozen, rejects unknown fields, rejects implicit type
coercion (``strict=True``), bounds every string, requires timezone-aware
timestamps normalized to UTC, and carries an explicit schema version. No
contract can express a wildcard subject, capability, or scope; no grant can be
perpetual; no field can carry a secret, credential, token, command, callable,
or import path — the schema simply has no place for one, and free-text fields
reject path/URL-like content.

Identifiers are supplied explicitly by callers (deterministic by design): this
layer never generates ids and never reads a clock.
"""

from __future__ import annotations

import json
import unicodedata
from datetime import datetime, timedelta
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

AUTHORITY_CONTRACT_SCHEMA_VERSION: Final = "authority-contracts-v1"

# Structural ceiling: no perpetual grants. A validity window may never exceed
# this span, independent of any future policy layer (ADR-0033).
MAX_GRANT_VALIDITY: Final = timedelta(days=366)

# Canonical grammars. None of them can express "*", whitespace, path
# separators, or control characters.
_AUTHORITY_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$"
_CAPABILITY_PATTERN: Final = r"^[a-z][a-z0-9_]{2,63}$"
_KEBAB_TOKEN_PATTERN: Final = r"^[a-z][a-z0-9-]{1,63}$"
_RESOURCE_ID_PATTERN: Final = r"^[a-z0-9][a-z0-9._:-]{0,126}$"
_POLICY_VERSION_PATTERN: Final = r"^[a-z][a-z0-9.-]{2,63}$"

_FORBIDDEN_TEXT_FRAGMENTS: Final = ("://", "\\", "/", "..")


class AuthorityContractError(ValidationError):
    """Typed fail-closed error for rejected authority payloads."""

    code = "authority_contract_error"


def _reject_dot_dot(value: str) -> str:
    if ".." in value:
        raise ValueError("value must not contain '..'")
    return value


# Uniform policy-version type: canonical token, no '..' anywhere.
_PolicyVersionField = Annotated[
    str, Field(pattern=_POLICY_VERSION_PATTERN), AfterValidator(_reject_dot_dot)
]


class SubjectType(StrEnum):
    """Kind of principal a grant could ever be scoped to."""

    OPERATOR = "operator"
    AGENT = "agent"
    LABORATORY = "laboratory"
    TOOL = "tool"
    ADAPTER = "adapter"


class ApprovalDecisionOutcome(StrEnum):
    """Terminal outcome of a human approval decision."""

    APPROVED = "approved"
    REJECTED = "rejected"


class DelegationPolicy(StrEnum):
    """Delegation policy vocabulary. v1 contains only prohibition."""

    PROHIBITED = "prohibited"


class AuthorityReasonCode(StrEnum):
    """Stable reason codes for deterministic authority evaluation."""

    AUTHORIZED = "authorized"
    APPROVAL_NOT_APPROVED = "approval_not_approved"
    APPROVAL_GRANT_MISMATCH = "approval_grant_mismatch"
    SUBJECT_MISMATCH = "subject_mismatch"
    CAPABILITY_MISMATCH = "capability_mismatch"
    SCOPE_MISMATCH = "scope_mismatch"
    PURPOSE_MISMATCH = "purpose_mismatch"
    NOT_YET_VALID = "not_yet_valid"
    EXPIRED = "expired"
    REVOKED = "revoked"
    POLICY_VERSION_MISMATCH = "policy_version_mismatch"
    DELEGATION_PROHIBITED = "delegation_prohibited"
    MALFORMED_AUTHORITY_CHAIN = "malformed_authority_chain"


# Fixed, non-interpolated decision text. Keeping this next to the decision
# contract lets parsing reject forged result details without importing the
# evaluator and creating an authority-package cycle.
_EVALUATION_DETAILS: Final[MappingProxyType[AuthorityReasonCode, str]] = MappingProxyType(
    {
        AuthorityReasonCode.AUTHORIZED: (
            "Authority chain is exact, approved, within validity, and unrevoked."
        ),
        AuthorityReasonCode.APPROVAL_NOT_APPROVED: (
            "The approval decision is not an approval; no authority exists."
        ),
        AuthorityReasonCode.APPROVAL_GRANT_MISMATCH: (
            "The grant does not exactly match the approved decision."
        ),
        AuthorityReasonCode.SUBJECT_MISMATCH: "The evaluated subject does not match the grant.",
        AuthorityReasonCode.CAPABILITY_MISMATCH: (
            "The evaluated capability does not match the grant."
        ),
        AuthorityReasonCode.SCOPE_MISMATCH: "The evaluated scope does not match the grant.",
        AuthorityReasonCode.PURPOSE_MISMATCH: "The evaluated purpose does not match the grant.",
        AuthorityReasonCode.NOT_YET_VALID: "The grant is not yet valid at the evaluation time.",
        AuthorityReasonCode.EXPIRED: "The grant is expired at the evaluation time.",
        AuthorityReasonCode.REVOKED: "The grant is revoked at the evaluation time.",
        AuthorityReasonCode.POLICY_VERSION_MISMATCH: (
            "The evaluated policy version does not match the grant."
        ),
        AuthorityReasonCode.DELEGATION_PROHIBITED: "Delegation is prohibited in v1.",
        AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN: (
            "The supplied authority chain is not internally consistent."
        ),
    }
)


# Unicode categories rejected in free text: controls (Cc), format/invisible
# characters including bidi overrides (Cf), and line/paragraph separators
# (Zl/Zp). Prevents misleading rendering in future approval surfaces.
_FORBIDDEN_TEXT_CATEGORIES: Final = ("Cc", "Cf", "Zl", "Zp")


def _validate_safe_text(value: str, *, field_name: str) -> str:
    """Bounded human text: printable, single-line, no path/URL-like content."""
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


class _StrictAuthorityModel(BaseModel):
    """Shared configuration: frozen, closed, coercion-free."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class SubjectReference(_StrictAuthorityModel):
    """Exact principal reference. No wildcard subject can be expressed."""

    subject_type: SubjectType
    subject_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)


class OperatorReference(_StrictAuthorityModel):
    """An attributable operator-designated actor for approval and issuance.

    This pure contract records only the asserted actor type and canonical id.
    Authentication and any human-facing issuance workflow remain out of scope.
    """

    subject_type: Literal[SubjectType.OPERATOR] = SubjectType.OPERATOR
    subject_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)


class ScopeConstraint(_StrictAuthorityModel):
    """One exact named constraint inside an authorization scope."""

    name: str = Field(pattern=_KEBAB_TOKEN_PATTERN)
    value: str = Field(pattern=_RESOURCE_ID_PATTERN)

    @field_validator("value")
    @classmethod
    def _no_dot_dot(cls, value: str) -> str:
        if ".." in value:
            raise ValueError("constraint value must not contain '..'")
        return value


class AuthorityScope(_StrictAuthorityModel):
    """Exact authorization scope. No wildcard resource can be expressed."""

    resource_type: str = Field(pattern=_KEBAB_TOKEN_PATTERN)
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)
    constraints: tuple[ScopeConstraint, ...] = Field(default=(), max_length=8)

    @field_validator("resource_id")
    @classmethod
    def _no_dot_dot(cls, value: str) -> str:
        if ".." in value:
            raise ValueError("resource_id must not contain '..'")
        return value

    @field_validator("constraints")
    @classmethod
    def _constraints_sorted_unique(
        cls, value: tuple[ScopeConstraint, ...]
    ) -> tuple[ScopeConstraint, ...]:
        names = [constraint.name for constraint in value]
        if len(set(names)) != len(names):
            raise ValueError("constraint names must be unique")
        return tuple(sorted(value, key=lambda constraint: constraint.name))


class ValidityWindow(_StrictAuthorityModel):
    """Mandatory bounded validity: valid_from <= t < expires_at, never perpetual."""

    valid_from: datetime
    expires_at: datetime

    @field_validator("valid_from", "expires_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _ordered_and_bounded(self) -> ValidityWindow:
        if self.valid_from >= self.expires_at:
            raise ValueError("valid_from must be strictly before expires_at")
        if self.expires_at - self.valid_from > MAX_GRANT_VALIDITY:
            raise ValueError("validity window exceeds the maximum permitted span")
        return self

    def contains(self, evaluation_time: datetime) -> bool:
        """Half-open interval test: valid_from <= evaluation_time < expires_at."""
        moment = ensure_utc(evaluation_time)
        return self.valid_from <= moment < self.expires_at


class ApprovalRequest(_StrictAuthorityModel):
    """A request for human approval. A request is never authority."""

    schema_version: Literal["authority-contracts-v1"] = AUTHORITY_CONTRACT_SCHEMA_VERSION
    request_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    owner_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    requested_by: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    subject: SubjectReference
    capability: str = Field(pattern=_CAPABILITY_PATTERN)
    scope: AuthorityScope
    purpose: str = Field(min_length=1, max_length=300)
    policy_version: _PolicyVersionField
    requested_at: datetime
    validity: ValidityWindow

    @field_validator("requested_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _safe_purpose(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="purpose")


class ApprovalDecision(_StrictAuthorityModel):
    """An attributable human decision. A decision is never execution."""

    schema_version: Literal["authority-contracts-v1"] = AUTHORITY_CONTRACT_SCHEMA_VERSION
    decision_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    request_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    owner_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    decided_by: OperatorReference
    outcome: ApprovalDecisionOutcome
    decided_at: datetime
    reason: str = Field(min_length=1, max_length=300)
    # Exact echoes of the request being decided; parity is re-verified at
    # evaluation time and any mismatch fails closed.
    subject: SubjectReference
    capability: str = Field(pattern=_CAPABILITY_PATTERN)
    scope: AuthorityScope
    purpose: str = Field(min_length=1, max_length=300)
    policy_version: _PolicyVersionField
    validity: ValidityWindow

    @field_validator("decided_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _safe_purpose(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="purpose")

    @field_validator("reason")
    @classmethod
    def _safe_reason(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="reason")


class CapabilityGrant(_StrictAuthorityModel):
    """A scoped, expiring, non-delegable capability grant.

    Possession of a grant is not sufficient authority: every use is
    re-evaluated against the full chain, exactly and fail-closed. A grant
    carries no secret, credential, command, callable, or import path — the
    schema has no such field and free text rejects path/URL fragments.
    """

    schema_version: Literal["authority-contracts-v1"] = AUTHORITY_CONTRACT_SCHEMA_VERSION
    grant_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    owner_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    request_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    decision_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    issued_by: OperatorReference
    issued_at: datetime
    subject: SubjectReference
    capability: str = Field(pattern=_CAPABILITY_PATTERN)
    scope: AuthorityScope
    purpose: str = Field(min_length=1, max_length=300)
    policy_version: _PolicyVersionField
    validity: ValidityWindow
    delegation: Literal[DelegationPolicy.PROHIBITED] = DelegationPolicy.PROHIBITED

    @field_validator("issued_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _safe_purpose(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="purpose")


class RevocationRecord(_StrictAuthorityModel):
    """Append-only revocation evidence for one grant."""

    schema_version: Literal["authority-contracts-v1"] = AUTHORITY_CONTRACT_SCHEMA_VERSION
    revocation_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    grant_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    owner_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    revoked_by: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    effective_at: datetime
    recorded_at: datetime
    reason: str = Field(min_length=1, max_length=300)

    @field_validator("effective_at", "recorded_at")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("reason")
    @classmethod
    def _safe_reason(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="reason")


class AuthorityEvaluationRequest(_StrictAuthorityModel):
    """A deterministic evaluation question with its complete authority chain.

    ``evaluation_time`` is explicit: evaluation never reads a clock.
    """

    schema_version: Literal["authority-contracts-v1"] = AUTHORITY_CONTRACT_SCHEMA_VERSION
    evaluation_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    owner_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    evaluation_time: datetime
    subject: SubjectReference
    capability: str = Field(pattern=_CAPABILITY_PATTERN)
    scope: AuthorityScope
    purpose: str = Field(min_length=1, max_length=300)
    policy_version: _PolicyVersionField
    delegation_requested: bool = False
    approval_request: ApprovalRequest
    approval_decision: ApprovalDecision
    grant: CapabilityGrant
    revocations: tuple[RevocationRecord, ...] = Field(default=(), max_length=32)

    @field_validator("evaluation_time")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @field_validator("purpose")
    @classmethod
    def _safe_purpose(cls, value: str) -> str:
        return _validate_safe_text(value, field_name="purpose")

    @field_validator("revocations")
    @classmethod
    def _revocations_sorted_unique(
        cls, value: tuple[RevocationRecord, ...]
    ) -> tuple[RevocationRecord, ...]:
        identifiers = [record.revocation_id for record in value]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("revocation_id values must be unique")
        return tuple(sorted(value, key=lambda record: (record.effective_at, record.revocation_id)))


class AuthorityEvaluationDecision(_StrictAuthorityModel):
    """The deterministic result of one authority evaluation.

    A decision — even ``authorized`` — is not a credential, token, or
    execution handle. It carries a stable reason code and nothing executable.
    """

    schema_version: Literal["authority-contracts-v1"] = AUTHORITY_CONTRACT_SCHEMA_VERSION
    evaluation_id: str = Field(pattern=_AUTHORITY_ID_PATTERN)
    evaluation_time: datetime
    authorized: bool
    reason_code: AuthorityReasonCode
    grant_id: str | None = Field(default=None, pattern=_AUTHORITY_ID_PATTERN)
    detail: str = Field(min_length=1, max_length=200)

    @field_validator("evaluation_time")
    @classmethod
    def _aware_utc(cls, value: datetime) -> datetime:
        return ensure_utc(value)

    @model_validator(mode="after")
    def _authorized_consistency(self) -> AuthorityEvaluationDecision:
        if self.authorized != (self.reason_code is AuthorityReasonCode.AUTHORIZED):
            raise ValueError("authorized must be true exactly when reason_code is authorized")
        if self.authorized and self.grant_id is None:
            raise ValueError("an authorized decision must reference the evaluated grant")
        if self.reason_code is AuthorityReasonCode.MALFORMED_AUTHORITY_CHAIN and self.grant_id:
            raise ValueError("a malformed authority chain must not reference a grant")
        if self.detail != _EVALUATION_DETAILS[self.reason_code]:
            raise ValueError("detail must be the fixed text for reason_code")
        return self


def canonical_authority_json(model: BaseModel) -> str:
    """Canonical deterministic serialization: sorted keys, compact UTF-8 JSON."""
    return json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def parse_authority_json[ModelT: BaseModel](model_type: type[ModelT], payload: str) -> ModelT:
    """Fail-closed JSON ingestion returning a typed authority error on rejection."""
    try:
        return model_type.model_validate_json(payload)
    except PydanticValidationError as error:
        raise AuthorityContractError(
            f"authority payload rejected for {model_type.__name__}"
        ) from error
