"""Repository for immutable Phase 4C observation-geometry persistence."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.core.errors import IdempotencyConflictError, NotFoundError, ValidationError
from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.observation_geometry.models import (
    GEOMETRY_COMPUTATION_VERSION,
    GEOMETRY_SCHEMA_VERSION,
    GeometryComputationRequest,
    GeometryComputationResult,
    geometry_checksum,
    request_checksum,
    source_identity_checksum,
)
from orbitmind.observation_geometry.verification import verify_geometry_result
from orbitmind.persistence.observation_geometry_models import (
    ObservationGeometryRequestRow,
    ObservationGeometryRunRow,
)

GEOMETRY_RUN_STATUS_COMPLETED = "completed"


class StoredObservationGeometryRequest(BaseModel):
    """Authenticated persisted geometry request."""

    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    request_checksum: str
    request: GeometryComputationRequest
    element_checksum: str
    source_identity_checksum: str
    idempotency_key: str | None


class StoredObservationGeometryRun(BaseModel):
    """Authenticated persisted completed geometry run."""

    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    request_checksum: str
    geometry_checksum: str
    result: GeometryComputationResult


class GeometryRequestWriteResult(BaseModel):
    """Outcome of owner-scoped geometry request creation/replay."""

    model_config = ConfigDict(frozen=True)

    request: StoredObservationGeometryRequest
    created: bool


class GeometryRunWriteResult(BaseModel):
    """Outcome of owner-scoped geometry run creation/replay."""

    model_config = ConfigDict(frozen=True)

    run: StoredObservationGeometryRun
    created: bool


class SqlAlchemyObservationGeometryRepository:
    """Persistence boundary for authenticated geometry requests and completed runs."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create_geometry_request(
        self,
        request: GeometryComputationRequest,
        *,
        owner_id: str,
        idempotency_key: str | None = None,
        use_savepoint: bool = True,
    ) -> GeometryRequestWriteResult:
        """Create or replay an immutable owner-scoped geometry request."""

        owner = normalize_owner_id(owner_id)
        key = _normalize_idempotency_key(idempotency_key)
        checksum = request_checksum(request)
        if key is not None:
            existing_for_key = self._find_request_by_idempotency(owner, key)
            if existing_for_key is not None:
                stored = self._row_to_request(existing_for_key)
                if stored.request_checksum != checksum:
                    raise IdempotencyConflictError(
                        "idempotency key reused with a different request"
                    )
                return GeometryRequestWriteResult(request=stored, created=False)
        existing_for_checksum = self._find_request_by_checksum(owner, checksum)
        if existing_for_checksum is not None:
            return GeometryRequestWriteResult(
                request=self._row_to_request(existing_for_checksum),
                created=False,
            )

        row = ObservationGeometryRequestRow(
            id=new_id(),
            owner_id=owner,
            request_checksum=checksum,
            request_schema_version=GEOMETRY_SCHEMA_VERSION,
            element_checksum=request.elements.element_checksum,
            source_identity_checksum=source_identity_checksum(request.elements.source),
            site_id=request.site.site_id,
            start_at=request.start,
            end_at=request.end,
            step_seconds=request.step_seconds,
            minimum_elevation_deg=request.minimum_elevation_deg,
            request_json=request.model_dump(mode="json"),
            idempotency_key=key,
            created_at=utcnow(),
        )
        if use_savepoint:
            try:
                with self._s.begin_nested():
                    self._s.add(row)
                    self._s.flush()
            except IntegrityError:
                self._s.expire_all()
                recovered = self._recover_request_after_integrity_error(
                    owner=owner,
                    request_checksum=checksum,
                    idempotency_key=key,
                )
                if recovered is None:
                    raise
                return GeometryRequestWriteResult(request=recovered, created=False)
        else:
            self._s.add(row)
            self._s.flush()
        return GeometryRequestWriteResult(request=self._row_to_request(row), created=True)

    def get_geometry_request(
        self, request_id: str, *, owner_id: str
    ) -> StoredObservationGeometryRequest | None:
        row = self._request_row(request_id, normalize_owner_id(owner_id))
        return self._row_to_request(row) if row is not None else None

    def get_geometry_request_by_checksum(
        self, *, owner_id: str, request_checksum: str
    ) -> StoredObservationGeometryRequest | None:
        row = self._find_request_by_checksum(normalize_owner_id(owner_id), request_checksum)
        return self._row_to_request(row) if row is not None else None

    def persist_geometry_result(
        self,
        *,
        request_id: str,
        owner_id: str,
        result: GeometryComputationResult,
        use_savepoint: bool = True,
    ) -> GeometryRunWriteResult:
        """Persist or replay one completed authenticated geometry run."""

        owner = normalize_owner_id(owner_id)
        stored_request = self.get_geometry_request(request_id, owner_id=owner)
        if stored_request is None:
            raise NotFoundError("observation-geometry request not found")
        _validate_result_for_request(result, stored_request.request)
        existing = self._find_run_by_request(owner, request_id)
        if existing is not None:
            stored = self._row_to_run(existing)
            if stored.geometry_checksum != result.geometry_checksum:
                raise ValidationError("stored geometry run conflicts with computed result")
            return GeometryRunWriteResult(run=stored, created=False)

        now = utcnow()
        row = ObservationGeometryRunRow(
            id=new_id(),
            owner_id=owner,
            request_id=request_id,
            request_checksum=result.request_checksum,
            geometry_checksum=result.geometry_checksum,
            element_checksum=result.element_checksum,
            source_identity_checksum=result.source_identity_checksum,
            result_schema_version=result.schema_version,
            computation_version=result.computation_version,
            run_status=GEOMETRY_RUN_STATUS_COMPLETED,
            epistemic_status=result.epistemic_status.value,
            sample_count=result.sample_count,
            failed_sample_count=result.failed_sample_count,
            interval_count=len(result.intervals),
            limitations_json=list(result.limitations),
            result_json=result.model_dump(mode="json"),
            created_at=now,
            completed_at=now,
        )
        if use_savepoint:
            try:
                with self._s.begin_nested():
                    self._s.add(row)
                    self._s.flush()
            except IntegrityError:
                self._s.expire_all()
                recovered_row = self._find_run_by_request(owner, request_id)
                if recovered_row is None:
                    raise
                stored = self._row_to_run(recovered_row)
                if stored.geometry_checksum != result.geometry_checksum:
                    raise ValidationError(
                        "stored geometry run conflicts with computed result"
                    ) from None
                return GeometryRunWriteResult(run=stored, created=False)
        else:
            self._s.add(row)
            self._s.flush()
        return GeometryRunWriteResult(run=self._row_to_run(row), created=True)

    def get_geometry_run(
        self, run_id: str, *, owner_id: str
    ) -> StoredObservationGeometryRun | None:
        row = self._run_row(run_id, normalize_owner_id(owner_id))
        return self._row_to_run(row) if row is not None else None

    def get_completed_run_for_request(
        self, request_id: str, *, owner_id: str
    ) -> StoredObservationGeometryRun | None:
        row = self._find_run_by_request(normalize_owner_id(owner_id), request_id)
        return self._row_to_run(row) if row is not None else None

    def _recover_request_after_integrity_error(
        self,
        *,
        owner: str,
        request_checksum: str,
        idempotency_key: str | None,
    ) -> StoredObservationGeometryRequest | None:
        if idempotency_key is not None:
            existing_for_key = self._find_request_by_idempotency(owner, idempotency_key)
            if existing_for_key is not None:
                stored = self._row_to_request(existing_for_key)
                if stored.request_checksum != request_checksum:
                    raise IdempotencyConflictError(
                        "idempotency key reused with a different request"
                    ) from None
                return stored
        existing_for_checksum = self._find_request_by_checksum(owner, request_checksum)
        if existing_for_checksum is not None:
            return self._row_to_request(existing_for_checksum)
        return None

    def _find_request_by_idempotency(
        self, owner_id: str, idempotency_key: str
    ) -> ObservationGeometryRequestRow | None:
        return (
            self._s.execute(
                select(ObservationGeometryRequestRow).where(
                    ObservationGeometryRequestRow.owner_id == owner_id,
                    ObservationGeometryRequestRow.idempotency_key == idempotency_key,
                )
            )
            .scalars()
            .first()
        )

    def _find_request_by_checksum(
        self, owner_id: str, checksum: str
    ) -> ObservationGeometryRequestRow | None:
        return (
            self._s.execute(
                select(ObservationGeometryRequestRow).where(
                    ObservationGeometryRequestRow.owner_id == owner_id,
                    ObservationGeometryRequestRow.request_checksum == checksum,
                )
            )
            .scalars()
            .first()
        )

    def _request_row(self, request_id: str, owner_id: str) -> ObservationGeometryRequestRow | None:
        return (
            self._s.execute(
                select(ObservationGeometryRequestRow).where(
                    ObservationGeometryRequestRow.id == request_id,
                    ObservationGeometryRequestRow.owner_id == owner_id,
                )
            )
            .scalars()
            .first()
        )

    def _find_run_by_request(
        self, owner_id: str, request_id: str
    ) -> ObservationGeometryRunRow | None:
        return (
            self._s.execute(
                select(ObservationGeometryRunRow).where(
                    ObservationGeometryRunRow.owner_id == owner_id,
                    ObservationGeometryRunRow.request_id == request_id,
                )
            )
            .scalars()
            .first()
        )

    def _run_row(self, run_id: str, owner_id: str) -> ObservationGeometryRunRow | None:
        return (
            self._s.execute(
                select(ObservationGeometryRunRow).where(
                    ObservationGeometryRunRow.id == run_id,
                    ObservationGeometryRunRow.owner_id == owner_id,
                )
            )
            .scalars()
            .first()
        )

    def _row_to_request(
        self, row: ObservationGeometryRequestRow
    ) -> StoredObservationGeometryRequest:
        if row.request_schema_version != GEOMETRY_SCHEMA_VERSION:
            raise ValidationError("unsupported observation-geometry request schema version")
        request = _validate_snapshot(
            GeometryComputationRequest,
            row.request_json,
            "stored observation-geometry request snapshot is invalid",
        )
        _assert_request_row_matches(row, request)
        return StoredObservationGeometryRequest(
            id=row.id,
            owner_id=row.owner_id,
            request_checksum=row.request_checksum,
            request=request,
            element_checksum=row.element_checksum,
            source_identity_checksum=row.source_identity_checksum,
            idempotency_key=row.idempotency_key,
        )

    def _row_to_run(self, row: ObservationGeometryRunRow) -> StoredObservationGeometryRun:
        if row.result_schema_version != GEOMETRY_SCHEMA_VERSION:
            raise ValidationError("unsupported observation-geometry result schema version")
        if row.run_status != GEOMETRY_RUN_STATUS_COMPLETED:
            raise ValidationError("observation-geometry run status mismatch")
        request_row = self._request_row(row.request_id, row.owner_id)
        if request_row is None:
            raise ValidationError("observation-geometry run request relationship mismatch")
        stored_request = self._row_to_request(request_row)
        result = _validate_snapshot(
            GeometryComputationResult,
            row.result_json,
            "stored observation-geometry result snapshot is invalid",
        )
        _assert_run_row_matches(row, result)
        _validate_result_for_request(result, stored_request.request)
        return StoredObservationGeometryRun(
            id=row.id,
            request_id=row.request_id,
            owner_id=row.owner_id,
            request_checksum=row.request_checksum,
            geometry_checksum=row.geometry_checksum,
            result=result,
        )


def normalize_owner_id(owner_id: str) -> str:
    """Validate and return the explicit persistence owner identifier."""

    if not owner_id or owner_id.strip() != owner_id:
        raise ValidationError("owner_id must be non-empty and unpadded")
    return owner_id


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    if not value or value.strip() != value or len(value) > 128:
        raise ValidationError("idempotency_key must be non-empty, unpadded, and bounded")
    return value


def _validate_snapshot[ModelT: BaseModel](
    model_type: type[ModelT],
    payload: object,
    message: str,
) -> ModelT:
    try:
        return model_type.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(message) from exc


def _validate_result_for_request(
    result: GeometryComputationResult,
    request: GeometryComputationRequest,
) -> None:
    if result.request_checksum != request.request_checksum:
        raise ValidationError("geometry result request checksum does not match request")
    if result.element_checksum != request.elements.element_checksum:
        raise ValidationError("geometry result element checksum does not match request")
    expected_source = source_identity_checksum(request.elements.source)
    if result.source_identity_checksum != expected_source:
        raise ValidationError("geometry result source identity checksum mismatch")
    verification = verify_geometry_result(result, request=request)
    if not verification.passed:
        raise ValidationError("geometry result failed structural verification")


def _assert_request_row_matches(
    row: ObservationGeometryRequestRow,
    request: GeometryComputationRequest,
) -> None:
    checksum = request_checksum(request)
    if row.request_checksum != checksum:
        raise ValidationError("observation-geometry request checksum mismatch")
    if request.request_checksum != checksum:
        raise ValidationError("observation-geometry request snapshot checksum mismatch")
    if row.element_checksum != request.elements.element_checksum:
        raise ValidationError("observation-geometry request element checksum mismatch")
    expected_source = source_identity_checksum(request.elements.source)
    if row.source_identity_checksum != expected_source:
        raise ValidationError("observation-geometry request source checksum mismatch")
    if row.site_id != request.site.site_id:
        raise ValidationError("observation-geometry request site mismatch")
    if row.start_at != request.start or row.end_at != request.end:
        raise ValidationError("observation-geometry request time range mismatch")
    if row.step_seconds != request.step_seconds:
        raise ValidationError("observation-geometry request step mismatch")
    if not math.isclose(
        row.minimum_elevation_deg,
        request.minimum_elevation_deg,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValidationError("observation-geometry request minimum-elevation mismatch")


def _assert_run_row_matches(
    row: ObservationGeometryRunRow,
    result: GeometryComputationResult,
) -> None:
    checksum = geometry_checksum(result)
    if row.geometry_checksum != checksum:
        raise ValidationError("observation-geometry run checksum mismatch")
    if result.geometry_checksum != checksum:
        raise ValidationError("observation-geometry result snapshot checksum mismatch")
    if row.request_checksum != result.request_checksum:
        raise ValidationError("observation-geometry run request checksum mismatch")
    if row.element_checksum != result.element_checksum:
        raise ValidationError("observation-geometry run element checksum mismatch")
    if row.source_identity_checksum != result.source_identity_checksum:
        raise ValidationError("observation-geometry run source checksum mismatch")
    if row.computation_version != GEOMETRY_COMPUTATION_VERSION:
        raise ValidationError("observation-geometry run computation-version mismatch")
    if row.computation_version != result.computation_version:
        raise ValidationError("observation-geometry result computation-version mismatch")
    if row.epistemic_status != EpistemicStatus.DETERMINISTIC_CALCULATION.value:
        raise ValidationError("observation-geometry run epistemic-status mismatch")
    if row.epistemic_status != result.epistemic_status.value:
        raise ValidationError("observation-geometry result epistemic-status mismatch")
    if row.sample_count != result.sample_count:
        raise ValidationError("observation-geometry run sample-count mismatch")
    if row.failed_sample_count != result.failed_sample_count:
        raise ValidationError("observation-geometry run failed-sample-count mismatch")
    if row.interval_count != len(result.intervals):
        raise ValidationError("observation-geometry run interval-count mismatch")
    if tuple(row.limitations_json) != result.limitations:
        raise ValidationError("observation-geometry run limitations mismatch")
