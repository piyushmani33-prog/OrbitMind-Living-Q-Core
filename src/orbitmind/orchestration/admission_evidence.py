"""Owner-scoped Authority-Admission evidence projections for U7.5A.

This orchestration read-model is the only layer that composes the two domains.
It performs bounded, deterministic reads and persists nothing. An Admission
record remains decision evidence only and never conveys execution authority.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from orbitmind.admission.contracts import AdmissionRecord
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.orchestration.authority_lifecycle import (
    AuthorityChainReadModel,
    read_authority_chain,
    read_capability_grant,
)
from orbitmind.persistence.admission_repository import SqlAlchemyAdmissionRepository

DEFAULT_ADMISSION_PAGE_SIZE = 25
MAX_ADMISSION_PAGE_SIZE = 50


class AdmissionEvidenceQueryError(ValidationError):
    """A bounded Admission evidence query was invalid."""

    code = "admission_evidence_query_error"


class AdmissionRecordNotFoundError(NotFoundError):
    """An owner-scoped Admission record or Authority request was not found."""

    code = "admission_record_not_found"


class _StrictReadModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AdmissionEvidenceChain(_StrictReadModel):
    """One Admission record and only its genuinely linked Authority evidence."""

    schema_version: Literal["authority-admission-evidence-v1"] = "authority-admission-evidence-v1"
    owner_id: str
    admission: AdmissionRecord
    authority: AuthorityChainReadModel | None


class RequestAdmissionChain(_StrictReadModel):
    """One real Authority request chain plus its grant-linked Admissions."""

    schema_version: Literal["authority-admission-evidence-v1"] = "authority-admission-evidence-v1"
    owner_id: str
    authority: AuthorityChainReadModel
    admissions: tuple[AdmissionRecord, ...]
    page_size: int = Field(ge=0, le=MAX_ADMISSION_PAGE_SIZE)
    truncated: bool


def _bounded_limit(limit: int, *, allow_overfetch: bool = False) -> int:
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise AdmissionEvidenceQueryError("admission evidence page size must be positive")
    maximum = MAX_ADMISSION_PAGE_SIZE + 1 if allow_overfetch else MAX_ADMISSION_PAGE_SIZE
    return min(limit, maximum)


def _read[ResultT](
    session: Session, operation: Callable[[SqlAlchemyAdmissionRepository], ResultT]
) -> ResultT:
    if session.in_transaction():
        raise AdmissionEvidenceQueryError("admission evidence query requires a fresh session")
    with session.begin():
        repository = SqlAlchemyAdmissionRepository(session)
        return operation(repository)


def read_admission_record(
    *, session: Session, owner_id: str, admission_id: str
) -> AdmissionRecord | None:
    """Read one owner-scoped Admission record; foreign-owner rows are absent."""

    return _read(
        session,
        lambda repository: repository.get_admission_record(
            owner_id=owner_id, admission_id=admission_id
        ),
    )


def list_admission_records_bounded(
    *, session: Session, owner_id: str, limit: int = DEFAULT_ADMISSION_PAGE_SIZE
) -> tuple[AdmissionRecord, ...]:
    """Read a deterministic, SQL-bounded owner-scoped Admission prefix."""

    bounded = _bounded_limit(limit, allow_overfetch=True)
    return _read(
        session,
        lambda repository: repository.list_admission_records_bounded(
            owner_id=owner_id, limit=bounded
        ),
    )


def _list_for_grants(
    *, session: Session, owner_id: str, grant_ids: tuple[str, ...], limit: int
) -> tuple[AdmissionRecord, ...]:
    bounded = _bounded_limit(limit, allow_overfetch=True)
    return _read(
        session,
        lambda repository: repository.list_admission_records_by_resolved_grants(
            owner_id=owner_id, grant_ids=grant_ids, limit=bounded
        ),
    )


def _linked_authority_chain(
    *, session: Session, owner_id: str, grant_id: str
) -> AuthorityChainReadModel | None:
    grant = read_capability_grant(session=session, owner_id=owner_id, grant_id=grant_id)
    if grant is None:
        return None
    chain = read_authority_chain(session=session, owner_id=owner_id, request_id=grant.request_id)
    if chain is None:
        return None
    return AuthorityChainReadModel(
        owner_id=chain.owner_id,
        approval_request=chain.approval_request,
        approval_decisions=tuple(
            decision
            for decision in chain.approval_decisions
            if decision.decision_id == grant.decision_id
        ),
        capability_grants=tuple(
            candidate for candidate in chain.capability_grants if candidate.grant_id == grant_id
        ),
        revocations=tuple(
            revocation for revocation in chain.revocations if revocation.grant_id == grant_id
        ),
        evaluations=tuple(
            evaluation for evaluation in chain.evaluations if evaluation.grant_id == grant_id
        ),
    )


def read_admission_evidence_chain(
    *, session: Session, owner_id: str, admission_id: str
) -> AdmissionEvidenceChain | None:
    """Compose the evidence rooted at one owner-scoped Admission id."""

    admission = read_admission_record(session=session, owner_id=owner_id, admission_id=admission_id)
    if admission is None:
        return None
    grant_id = admission.resolved_authority_grant_id
    authority = (
        None
        if grant_id is None
        else _linked_authority_chain(session=session, owner_id=owner_id, grant_id=grant_id)
    )
    return AdmissionEvidenceChain(owner_id=owner_id, admission=admission, authority=authority)


def read_request_admission_chain(
    *,
    session: Session,
    owner_id: str,
    request_id: str,
    limit: int = DEFAULT_ADMISSION_PAGE_SIZE,
) -> RequestAdmissionChain | None:
    """Compose one Authority chain with only Admissions linked through its grants."""

    bounded = _bounded_limit(limit)
    authority = read_authority_chain(session=session, owner_id=owner_id, request_id=request_id)
    if authority is None:
        return None
    grant_ids = tuple(grant.grant_id for grant in authority.capability_grants)
    probe = _list_for_grants(
        session=session, owner_id=owner_id, grant_ids=grant_ids, limit=bounded + 1
    )
    admissions = probe[:bounded]
    return RequestAdmissionChain(
        owner_id=owner_id,
        authority=authority,
        admissions=admissions,
        page_size=len(admissions),
        truncated=len(probe) > bounded,
    )
