"""Strict API DTOs for the trusted-local U7.5A Admission surface."""

from __future__ import annotations

from datetime import datetime
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.admission.contracts import (
    AdmissionRecord,
    AdmissionRiskClass,
    AdmissionSideEffectClass,
    ProposalScope,
)
from orbitmind.orchestration.authority_lifecycle import AuthorityChainReadModel

ADMISSION_API_SCHEMA_VERSION: Final[Literal["admission-api-v1"]] = "admission-api-v1"

_ID_FIELD = Field(pattern=r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$")
_CAPABILITY_FIELD = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
_OPERATION_FIELD = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")


class _StrictApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AdmissionProposalRequest(_StrictApiModel):
    """Untrusted proposal fields; all identity and evaluation fields are omitted."""

    schema_version: Literal["admission-api-v1"] = ADMISSION_API_SCHEMA_VERSION
    proposal_id: str = _ID_FIELD
    operation_kind: str = _OPERATION_FIELD
    requested_capability: str = _CAPABILITY_FIELD
    requested_scope: ProposalScope
    side_effect_class: AdmissionSideEffectClass
    risk_class: AdmissionRiskClass
    purpose: str = Field(min_length=1, max_length=300)
    resource_target: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9._:-]{0,126}$")
    requested_authority_grant_id: str | None = Field(
        default=None, pattern=r"^[a-z0-9][a-z0-9-]{6,62}[a-z0-9]$"
    )
    requested_at: datetime
    idempotency_key: str = Field(min_length=1, max_length=200)
    provenance_refs: tuple[str, ...] = Field(default=(), max_length=8)


class AdmissionRecordResponse(_StrictApiModel):
    """One immutable Admission decision-evidence record."""

    schema_version: Literal["admission-api-v1"] = ADMISSION_API_SCHEMA_VERSION
    record: AdmissionRecord
    execution_authority: Literal[False] = False
    note: Literal["Admission is decision evidence only; it does not prove execution."] = (
        "Admission is decision evidence only; it does not prove execution."
    )


class AdmissionRecordListResponse(_StrictApiModel):
    """Bounded owner-scoped Admission list."""

    schema_version: Literal["admission-api-v1"] = ADMISSION_API_SCHEMA_VERSION
    owner_id: str
    items: tuple[AdmissionRecord, ...]
    page_size: int = Field(ge=0, le=50)
    truncated: bool


class AdmissionEvidenceChainResponse(_StrictApiModel):
    """Admission-centric evidence with optional genuinely linked Authority data."""

    schema_version: Literal["admission-api-v1"] = ADMISSION_API_SCHEMA_VERSION
    owner_id: str
    admission: AdmissionRecord
    authority: AuthorityChainReadModel | None
    execution_authority: Literal[False] = False


class RequestAdmissionChainResponse(_StrictApiModel):
    """Authority-request evidence and only Admissions linked through its grants."""

    schema_version: Literal["admission-api-v1"] = ADMISSION_API_SCHEMA_VERSION
    owner_id: str
    authority: AuthorityChainReadModel
    admissions: tuple[AdmissionRecord, ...]
    page_size: int = Field(ge=0, le=50)
    truncated: bool
    execution_authority: Literal[False] = False
