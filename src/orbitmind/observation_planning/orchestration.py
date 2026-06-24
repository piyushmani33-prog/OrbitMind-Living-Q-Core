"""Transactional observation-planning orchestration boundary.

This module connects the in-memory Phase 4B.1 planning service to the minimal persistence
envelope. It owns one outer SQLAlchemy transaction; repositories may use nested savepoints for
idempotent races, but they do not commit independently.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from orbitmind.core.errors import ValidationError
from orbitmind.observation_planning.models import (
    ObservationPlanningRequest,
    ObservationPlanningResult,
    PlanningResultStatus,
)
from orbitmind.observation_planning.service import plan_observation_request
from orbitmind.persistence.observation_planning_repository import (
    SqlAlchemyObservationPlanningRepository,
    normalize_owner_id,
    scientific_identity_checksum,
    validate_persistable_planning_result,
)


class PersistedObservationPlanningExecution(BaseModel):
    """Typed return contract for synchronous persisted planning execution."""

    model_config = ConfigDict(frozen=True)

    request_id: str
    run_id: str
    plan_id: str | None
    owner_id: str
    request_created: bool
    run_created: bool
    plan_created: bool
    result: ObservationPlanningResult
    request_checksum: str
    problem_checksum: str
    scientific_identity_checksum: str
    final_status: PlanningResultStatus
    feasible: bool


def execute_observation_planning(
    *,
    session: Session,
    owner_id: str,
    request: ObservationPlanningRequest,
    idempotency_key: str | None = None,
) -> PersistedObservationPlanningExecution:
    """Plan and persist a bounded observation-planning request atomically.

    The caller provides a fresh session with no active transaction. This function creates the
    request envelope, runs the synchronous classical planning service, and persists the run/plan
    graph in one outer transaction. Unexpected planning or database failures roll back the whole
    newly created graph.
    """

    resolved_owner = normalize_owner_id(owner_id)
    resolved_request = _request_with_idempotency(request, idempotency_key)
    if session.in_transaction():
        raise ValidationError("observation-planning orchestration requires a fresh session")

    with session.begin():
        repo = SqlAlchemyObservationPlanningRepository(session)
        use_repository_savepoint = _use_repository_savepoint(session)
        preexisting_request = (
            repo.get_planning_request_by_idempotency(
                owner_id=resolved_owner,
                idempotency_key=resolved_request.idempotency_key,
            )
            if resolved_request.idempotency_key is not None
            else None
        )
        stored_request = repo.create_planning_request(
            resolved_request,
            owner_id=resolved_owner,
            use_savepoint=use_repository_savepoint,
        )
        request_created = preexisting_request is None

        result = plan_observation_request(resolved_request)
        validate_persistable_planning_result(result)
        identity_checksum = scientific_identity_checksum(result.scientific_identity)
        preexisting_run = repo.get_planning_run_by_scientific_identity(
            request_id=stored_request.id,
            identity_checksum=identity_checksum,
        )
        stored_run = repo.persist_planning_result(
            request_id=stored_request.id,
            owner_id=stored_request.owner_id,
            result=result,
            use_savepoint=use_repository_savepoint,
        )
        run_created = preexisting_run is None
        plan_created = run_created and stored_run.plan_id is not None

        return PersistedObservationPlanningExecution(
            request_id=stored_request.id,
            run_id=stored_run.id,
            plan_id=stored_run.plan_id,
            owner_id=stored_request.owner_id,
            request_created=request_created,
            run_created=run_created,
            plan_created=plan_created,
            result=stored_run.result,
            request_checksum=result.request_checksum,
            problem_checksum=result.problem_checksum,
            scientific_identity_checksum=stored_run.scientific_identity_checksum,
            final_status=result.status,
            feasible=result.feasible,
        )


def _request_with_idempotency(
    request: ObservationPlanningRequest,
    idempotency_key: str | None,
) -> ObservationPlanningRequest:
    if idempotency_key is None:
        return request
    if request.idempotency_key is not None and request.idempotency_key != idempotency_key:
        raise ValidationError("conflicting observation-planning idempotency key")
    if request.idempotency_key == idempotency_key:
        return request
    return request.model_copy(update={"idempotency_key": idempotency_key})


def _use_repository_savepoint(session: Session) -> bool:
    """Keep PostgreSQL race-safe savepoints, but avoid SQLite legacy savepoint auto-commit."""

    return session.get_bind().dialect.name != "sqlite"
