"""Trusted-local, owner-scoped Admission JSON API for U7.5A.

The surface evaluates policy and stores/reads decision evidence. It performs no
operation and emits no token, capability, command result, or execution receipt.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from orbitmind.admission.contracts import OperationProposal, ProposalActorType
from orbitmind.api.admission_schemas import (
    AdmissionEvidenceChainResponse,
    AdmissionProposalRequest,
    AdmissionRecordListResponse,
    AdmissionRecordResponse,
    RequestAdmissionChainResponse,
)
from orbitmind.api.deps import get_container, get_current_owner_id
from orbitmind.api.routers.authority import _header_values
from orbitmind.core.errors import ValidationError
from orbitmind.core.timeutils import utcnow
from orbitmind.orchestration.admission_evidence import (
    DEFAULT_ADMISSION_PAGE_SIZE,
    MAX_ADMISSION_PAGE_SIZE,
    AdmissionRecordNotFoundError,
    list_admission_records_bounded,
    read_admission_evidence_chain,
    read_admission_record,
    read_request_admission_chain,
)
from orbitmind.orchestration.admission_lifecycle import (
    AdmissionDisposition,
    admit_operation,
)

_TRUSTED_LOCAL_ADMISSION_PEER = "127.0.0.1"
_MAX_ADMISSION_API_BODY_BYTES = 16_384
_NO_STORE_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
}


def require_trusted_local_admission_peer(request: Request) -> None:
    """Reject requests whose direct peer is not canonical IPv4 loopback."""

    client = request.client
    if client is None or client.host != _TRUSTED_LOCAL_ADMISSION_PEER:
        raise HTTPException(
            status_code=403, detail="Admission routes require a local loopback peer"
        )


router = APIRouter(tags=["admission"], dependencies=[Depends(require_trusted_local_admission_peer)])


@dataclass(frozen=True, slots=True)
class TrustedLocalAdmissionOperatorContext:
    """Fixed trusted-local actor attribution; not a remote authentication system."""

    owner_id: str
    actor_id: str = "local-operator"


def get_trusted_local_admission_operator_context(
    owner_id: Annotated[str, Depends(get_current_owner_id)],
) -> TrustedLocalAdmissionOperatorContext:
    return TrustedLocalAdmissionOperatorContext(owner_id=owner_id)


def get_admission_session(request: Request) -> Iterator[Session]:
    session = get_container(request).database.session()
    try:
        yield session
    finally:
        session.close()


def get_trusted_clock() -> datetime:
    """Return the server-owned UTC evaluation time; tests may override this dependency."""

    return utcnow()


OwnerDep = Annotated[str, Depends(get_current_owner_id)]
OperatorDep = Annotated[
    TrustedLocalAdmissionOperatorContext,
    Depends(get_trusted_local_admission_operator_context),
]
SessionDep = Annotated[Session, Depends(get_admission_session)]
ClockDep = Annotated[datetime, Depends(get_trusted_clock)]


async def _parse_json_body[ModelT: BaseModel](request: Request, model_type: type[ModelT]) -> ModelT:
    content_type = request.headers.get("content-type", "")
    if content_type.split(";", maxsplit=1)[0].strip().lower() != "application/json":
        raise ValidationError("admission API requires an application/json body")
    raw = await request.body()
    if len(raw) > _MAX_ADMISSION_API_BODY_BYTES:
        raise ValidationError("admission API body exceeds the bounded size")
    return model_type.model_validate_json(raw)


def _enforce_mutation_origin(request: Request) -> None:
    """Apply narrow browser cross-site defense-in-depth before reading JSON."""

    fetch_sites = _header_values(request, "Sec-Fetch-Site")
    if len(fetch_sites) > 1 or (
        fetch_sites and fetch_sites[0].strip().casefold() not in {"same-origin", "none"}
    ):
        raise HTTPException(status_code=403, detail="Admission mutation origin was rejected")

    origins = _header_values(request, "Origin")
    expected_origin = f"{request.url.scheme}://{request.url.netloc}"
    if len(origins) > 1 or (origins and origins[0].rstrip("/") != expected_origin):
        raise HTTPException(status_code=403, detail="Admission mutation origin was rejected")


def _json_response(*, status_code: int, payload: dict[str, object]) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=payload, headers=dict(_NO_STORE_HEADERS))


@router.post("/api/admission/proposals")
async def admit_proposal_api(
    request: Request,
    owner_id: OwnerDep,
    operator: OperatorDep,
    session: SessionDep,
    evaluated_at: ClockDep,
) -> JSONResponse:
    """Evaluate and append Admission evidence (201 created, 200 replayed)."""

    _enforce_mutation_origin(request)
    body = await _parse_json_body(request, AdmissionProposalRequest)
    proposal = OperationProposal(
        proposal_id=body.proposal_id,
        owner_id=owner_id,
        actor_id=operator.actor_id,
        actor_type=ProposalActorType.OPERATOR,
        operation_kind=body.operation_kind,
        requested_capability=body.requested_capability,
        requested_scope=body.requested_scope,
        side_effect_class=body.side_effect_class,
        risk_class=body.risk_class,
        purpose=body.purpose,
        resource_target=body.resource_target,
        requested_authority_grant_id=body.requested_authority_grant_id,
        requested_at=body.requested_at,
        idempotency_key=body.idempotency_key,
        provenance_refs=body.provenance_refs,
    )
    result = admit_operation(
        session=session,
        proposal=proposal,
        authoritative_owner_id=owner_id,
        authoritative_actor_id=operator.actor_id,
        evaluated_at=evaluated_at,
    )
    response = AdmissionRecordResponse(record=result.record)
    status = 201 if result.disposition is AdmissionDisposition.CREATED else 200
    return _json_response(status_code=status, payload=response.model_dump(mode="json"))


@router.get("/api/admission/records/{admission_id}")
def read_admission_record_api(
    admission_id: str, owner_id: OwnerDep, session: SessionDep
) -> JSONResponse:
    record = read_admission_record(session=session, owner_id=owner_id, admission_id=admission_id)
    if record is None:
        raise AdmissionRecordNotFoundError("admission record was not found")
    response = AdmissionRecordResponse(record=record)
    return _json_response(status_code=200, payload=response.model_dump(mode="json"))


@router.get("/api/admission/records")
def list_admission_records_api(
    owner_id: OwnerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_ADMISSION_PAGE_SIZE)] = (DEFAULT_ADMISSION_PAGE_SIZE),
) -> JSONResponse:
    probe = list_admission_records_bounded(session=session, owner_id=owner_id, limit=limit + 1)
    items = probe[:limit]
    response = AdmissionRecordListResponse(
        owner_id=owner_id,
        items=items,
        page_size=len(items),
        truncated=len(probe) > limit,
    )
    return _json_response(status_code=200, payload=response.model_dump(mode="json"))


@router.get("/api/admission/records/{admission_id}/evidence-chain")
def read_admission_evidence_chain_api(
    admission_id: str, owner_id: OwnerDep, session: SessionDep
) -> JSONResponse:
    chain = read_admission_evidence_chain(
        session=session, owner_id=owner_id, admission_id=admission_id
    )
    if chain is None:
        raise AdmissionRecordNotFoundError("admission record was not found")
    response = AdmissionEvidenceChainResponse(
        owner_id=chain.owner_id,
        admission=chain.admission,
        authority=chain.authority,
    )
    return _json_response(status_code=200, payload=response.model_dump(mode="json"))


@router.get("/api/admission/authority-chains/{request_id}")
def read_request_admission_chain_api(
    request_id: str,
    owner_id: OwnerDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=MAX_ADMISSION_PAGE_SIZE)] = (DEFAULT_ADMISSION_PAGE_SIZE),
) -> JSONResponse:
    chain = read_request_admission_chain(
        session=session, owner_id=owner_id, request_id=request_id, limit=limit
    )
    if chain is None:
        raise AdmissionRecordNotFoundError("authority request was not found")
    response = RequestAdmissionChainResponse(
        owner_id=chain.owner_id,
        authority=chain.authority,
        admissions=chain.admissions,
        page_size=chain.page_size,
        truncated=chain.truncated,
    )
    return _json_response(status_code=200, payload=response.model_dump(mode="json"))
