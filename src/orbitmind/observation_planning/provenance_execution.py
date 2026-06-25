"""Transactional execution of provenance-anchored observation planning."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from orbitmind.core.errors import ValidationError
from orbitmind.observation_planning.models import (
    AuthoritativePlanningSolver,
    ObservationPlanningRequest,
    PlanningOptimalityLabel,
    PlanningResultStatus,
)
from orbitmind.observation_planning.orchestration import (
    PersistedObservationPlanningExecution,
    _execute_observation_planning_in_transaction,
)
from orbitmind.observation_planning.provenance import (
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.observation_planning.provenance_preparation import (
    PreparedEligibilityPlanningRequest,
    prepare_eligibility_backed_planning_request,
)
from orbitmind.persistence.observation_planning_link_repository import (
    SqlAlchemyObservationPlanningLinkRepository,
    StoredProvenancePlanningLink,
)
from orbitmind.persistence.observation_planning_repository import normalize_owner_id

_IDEMPOTENCY_PREFIX = "eligibility-preparation:"


class ProvenanceAnchoredPlanningExecution(BaseModel):
    """Typed result for one persisted provenance-anchored planning execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    owner_id: str
    provenance_record_id: str
    provenance_checksum: str
    eligibility_set_record_id: str
    eligibility_set_checksum: str
    preparation_checksum: str
    planning_request_checksum: str
    planning_request_id: str
    planning_run_id: str
    observation_plan_id: str | None
    source_type: PinnedInputSourceType
    source_verification_status: ScientificInputVerificationStatus
    selected_window_ids: tuple[str, ...]
    planning_status: PlanningResultStatus
    authoritative_solver: AuthoritativePlanningSolver | None
    optimality: PlanningOptimalityLabel
    feasible: bool
    independent_objective: float | None
    request_created: bool
    run_created: bool
    plan_created: bool
    link_record_id: str
    link_checksum: str
    limitations: tuple[str, ...]
    preparation: PreparedEligibilityPlanningRequest
    planning_execution: PersistedObservationPlanningExecution
    link: StoredProvenancePlanningLink


def execute_provenance_anchored_planning(
    *,
    session: Session,
    owner_id: str,
    requested_by: str,
    eligibility_set_id: str | None = None,
    eligibility_set_checksum: str | None = None,
    selected_window_ids: Sequence[str] | None = None,
    idempotency_key: str | None = None,
) -> ProvenanceAnchoredPlanningExecution:
    """Prepare, execute, and persist a provenance-planning derivation link atomically."""

    owner = normalize_owner_id(owner_id)
    if session.in_transaction():
        raise ValidationError("provenance-anchored planning requires a fresh session")
    with session.begin():
        preparation = prepare_eligibility_backed_planning_request(
            session=session,
            owner_id=owner,
            eligibility_set_id=eligibility_set_id,
            eligibility_set_checksum=eligibility_set_checksum,
            requested_by=requested_by,
            selected_window_ids=selected_window_ids,
        )
        request_key = idempotency_key or _default_idempotency_key(preparation.preparation_checksum)
        request = _request_with_idempotency(preparation, request_key)
        planning_execution = _execute_observation_planning_in_transaction(
            session=session,
            owner_id=owner,
            request=request,
        )
        link = SqlAlchemyObservationPlanningLinkRepository(session).create_provenance_planning_link(
            owner_id=owner,
            preparation=preparation,
            planning_request_id=planning_execution.request_id,
            planning_run_id=planning_execution.run_id,
            observation_plan_id=planning_execution.plan_id,
            result=planning_execution.result,
            planning_scientific_identity_checksum=(planning_execution.scientific_identity_checksum),
        )
        return ProvenanceAnchoredPlanningExecution(
            owner_id=owner,
            provenance_record_id=preparation.provenance_record_id,
            provenance_checksum=preparation.provenance_checksum,
            eligibility_set_record_id=preparation.eligibility_set_record_id,
            eligibility_set_checksum=preparation.eligibility_set_checksum,
            preparation_checksum=preparation.preparation_checksum,
            planning_request_checksum=preparation.planning_request_checksum,
            planning_request_id=planning_execution.request_id,
            planning_run_id=planning_execution.run_id,
            observation_plan_id=planning_execution.plan_id,
            source_type=preparation.eligibility_source_type,
            source_verification_status=preparation.eligibility_verification_status,
            selected_window_ids=preparation.selected_window_ids,
            planning_status=planning_execution.final_status,
            authoritative_solver=planning_execution.result.selected_solver,
            optimality=planning_execution.result.optimality_label,
            feasible=planning_execution.feasible,
            independent_objective=planning_execution.result.objective_value,
            request_created=planning_execution.request_created,
            run_created=planning_execution.run_created,
            plan_created=planning_execution.plan_created,
            link_record_id=link.id,
            link_checksum=link.link_checksum,
            limitations=link.limitations,
            preparation=preparation,
            planning_execution=planning_execution,
            link=link,
        )


def _default_idempotency_key(preparation_checksum: str) -> str:
    return f"{_IDEMPOTENCY_PREFIX}{preparation_checksum}"


def _request_with_idempotency(
    preparation: PreparedEligibilityPlanningRequest,
    idempotency_key: str,
) -> ObservationPlanningRequest:
    request = preparation.prepared_request
    if request.idempotency_key is not None and request.idempotency_key != idempotency_key:
        raise ValidationError("conflicting provenance-anchored idempotency key")
    if request.idempotency_key == idempotency_key:
        return request
    return request.model_copy(update={"idempotency_key": idempotency_key})
