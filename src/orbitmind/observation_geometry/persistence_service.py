"""Transactional persistence service for bounded observation geometry."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from orbitmind.core.errors import ValidationError
from orbitmind.observation_geometry.models import (
    GeometryComputationRequest,
    GeometryComputationResult,
)
from orbitmind.observation_geometry.service import compute_observation_geometry
from orbitmind.observation_geometry.verification import verify_geometry_result
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
    normalize_owner_id,
)


class PersistedObservationGeometryExecution(BaseModel):
    """Typed result returned by the geometry persistence application boundary."""

    model_config = ConfigDict(frozen=True)

    owner_id: str
    request_id: str
    run_id: str
    request_created: bool
    run_created: bool
    request_checksum: str
    geometry_checksum: str
    result: GeometryComputationResult


def execute_and_persist_geometry(
    *,
    session: Session,
    owner_id: str,
    request: GeometryComputationRequest,
    idempotency_key: str | None = None,
) -> PersistedObservationGeometryExecution:
    """Compute or replay one owner-scoped persisted geometry result.

    The service owns exactly one outer SQLAlchemy transaction. Repositories participate in
    that transaction and never commit or roll back independently. SQLAlchemy may open an
    implicit database transaction for the enclosed reads/writes; callers should provide a fresh
    session with no active transaction.
    """

    if session.in_transaction():
        raise ValidationError("observation-geometry execution requires a fresh session")
    owner = normalize_owner_id(owner_id)
    use_savepoint = _repository_savepoints_enabled(session)
    with session.begin():
        repository = SqlAlchemyObservationGeometryRepository(session)
        request_write = repository.create_geometry_request(
            request,
            owner_id=owner,
            idempotency_key=idempotency_key,
            use_savepoint=use_savepoint,
        )
        existing_run = repository.get_completed_run_for_request(
            request_write.request.id,
            owner_id=owner,
        )
        if existing_run is not None:
            return PersistedObservationGeometryExecution(
                owner_id=owner,
                request_id=request_write.request.id,
                run_id=existing_run.id,
                request_created=request_write.created,
                run_created=False,
                request_checksum=request_write.request.request_checksum,
                geometry_checksum=existing_run.geometry_checksum,
                result=existing_run.result,
            )

        result = compute_observation_geometry(request)
        verification = verify_geometry_result(result, request=request)
        if not verification.passed:
            raise ValidationError("geometry result failed structural verification")
        run_write = repository.persist_geometry_result(
            request_id=request_write.request.id,
            owner_id=owner,
            result=result,
            use_savepoint=use_savepoint,
        )
        return PersistedObservationGeometryExecution(
            owner_id=owner,
            request_id=request_write.request.id,
            run_id=run_write.run.id,
            request_created=request_write.created,
            run_created=run_write.created,
            request_checksum=request_write.request.request_checksum,
            geometry_checksum=run_write.run.geometry_checksum,
            result=run_write.run.result,
        )


def _repository_savepoints_enabled(session: Session) -> bool:
    return session.get_bind().dialect.name != "sqlite"
