"""Repository for minimal Phase 4B observation-planning persistence."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.observation_planning.models import (
    ObservationPlanningRequest,
    ObservationPlanningResult,
    ObservationPlanningScientificIdentity,
    PlanningResultStatus,
    planning_request_checksum,
)
from orbitmind.optimization.models import ScheduleEvaluation
from orbitmind.persistence.observation_planning_models import (
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
    ObservationPlanRow,
)

REQUEST_SCHEMA_VERSION = "observation-planning-request-v1"
RESULT_SCHEMA_VERSION = "observation-planning-result-v1"
PLAN_SCHEMA_VERSION = "observation-plan-v1"


class StoredObservationPlanningRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    request_checksum: str
    request: ObservationPlanningRequest
    source_mode: str
    idempotency_key: str | None


class StoredObservationPlanningRun(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    request_id: str
    owner_id: str
    result: ObservationPlanningResult
    scientific_identity_checksum: str
    plan_id: str | None = None


class StoredObservationPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    run_id: str
    owner_id: str
    problem_checksum: str
    selected_opportunity_ids: tuple[str, ...]
    evaluation: ScheduleEvaluation
    limitations: tuple[str, ...]
    scientific_identity: ObservationPlanningScientificIdentity
    scientific_identity_checksum: str


def scientific_identity_checksum(identity: ObservationPlanningScientificIdentity) -> str:
    """Checksum the deterministic planning identity."""

    return sha256_canonical_json(identity.model_dump(mode="json"))


class SqlAlchemyObservationPlanningRepository:
    """Narrow persistence boundary for immutable observation-planning envelopes."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create_planning_request(
        self, request: ObservationPlanningRequest, *, owner_id: str | None = None
    ) -> StoredObservationPlanningRequest:
        resolved_owner = _owner(owner_id or request.requested_by)
        checksum = planning_request_checksum(request)
        if request.idempotency_key is not None:
            existing = self._find_request_by_idempotency(resolved_owner, request.idempotency_key)
            if existing is not None:
                stored = self._row_to_request(existing)
                if stored.request_checksum != checksum:
                    raise ValidationError("idempotency key reused with a different request")
                return stored
        row = ObservationPlanningRequestRow(
            id=new_id(),
            owner_id=resolved_owner,
            request_checksum=checksum,
            source_mode=request.source_mode.value,
            request_schema_version=REQUEST_SCHEMA_VERSION,
            request_json=request.model_dump(mode="json"),
            idempotency_key=request.idempotency_key,
            created_at=utcnow(),
        )
        try:
            with self._s.begin_nested():
                self._s.add(row)
                self._s.flush()
        except IntegrityError:
            self._s.expire_all()
            if request.idempotency_key is None:
                raise
            existing = self._find_request_by_idempotency(resolved_owner, request.idempotency_key)
            if existing is None:
                raise
            stored = self._row_to_request(existing)
            if stored.request_checksum != checksum:
                raise ValidationError("idempotency key reused with a different request") from None
            return stored
        return self._row_to_request(row)

    def get_planning_request(
        self, request_id: str, *, owner_id: str
    ) -> StoredObservationPlanningRequest | None:
        row = self._request_row(request_id, _owner(owner_id))
        return self._row_to_request(row) if row is not None else None

    def persist_planning_result(
        self,
        *,
        request_id: str,
        owner_id: str,
        result: ObservationPlanningResult,
    ) -> StoredObservationPlanningRun:
        resolved_owner = _owner(owner_id)
        request = self.get_planning_request(request_id, owner_id=resolved_owner)
        if request is None:
            raise NotFoundError("observation-planning request not found")
        if request.request_checksum != result.request_checksum:
            raise ValidationError("planning result request checksum does not match request")
        identity = result.scientific_identity
        if identity.problem_checksum != result.problem_checksum:
            raise ValidationError("scientific identity problem checksum does not match result")
        if (
            result.authoritative_result is not None
            and result.authoritative_result.problem_checksum != result.problem_checksum
        ):
            raise ValidationError("planning result problem checksum does not match solver result")
        if (
            result.independent_evaluation is not None
            and result.independent_evaluation.problem_checksum != result.problem_checksum
        ):
            raise ValidationError("planning result problem checksum does not match evaluation")
        identity_checksum = scientific_identity_checksum(identity)
        existing = self._find_run_by_identity(request_id, identity_checksum)
        if existing is not None:
            return self._row_to_run(existing)

        run_id = new_id()
        now = utcnow()
        run = ObservationPlanningRunRow(
            id=run_id,
            request_id=request_id,
            owner_id=resolved_owner,
            request_checksum=result.request_checksum,
            problem_checksum=result.problem_checksum,
            planning_status=result.status.value,
            authoritative_solver=result.selected_solver.value if result.selected_solver else None,
            solver_execution_status=(
                result.solver_execution_status.value if result.solver_execution_status else None
            ),
            optimality_label=result.optimality_label.value,
            verification_label=(
                result.verification_label.value if result.verification_label else None
            ),
            source_mode=result.source_mode.value,
            feasible=result.feasible,
            objective_value=result.objective_value,
            result_schema_version=RESULT_SCHEMA_VERSION,
            result_json=result.model_dump(mode="json"),
            scientific_identity_json=identity.model_dump(mode="json"),
            scientific_identity_checksum=identity_checksum,
            created_at=now,
            completed_at=now,
        )
        try:
            with self._s.begin_nested():
                self._s.add(run)
                self._s.flush()
                if result.status == PlanningResultStatus.VERIFIED_FEASIBLE:
                    self._s.add(_plan_row(run_id, resolved_owner, result, identity_checksum))
                self._s.flush()
        except IntegrityError:
            self._s.expire_all()
            existing = self._find_run_by_identity(request_id, identity_checksum)
            if existing is None:
                raise
            return self._row_to_run(existing)
        return self._row_to_run(run)

    def get_planning_run(
        self, run_id: str, *, owner_id: str
    ) -> StoredObservationPlanningRun | None:
        row = self._run_row(run_id, _owner(owner_id))
        return self._row_to_run(row) if row is not None else None

    def get_observation_plan(self, plan_id: str, *, owner_id: str) -> StoredObservationPlan | None:
        row = self._plan_row(plan_id, _owner(owner_id))
        return self._row_to_plan(row) if row is not None else None

    def get_observation_plan_for_run(
        self, run_id: str, *, owner_id: str
    ) -> StoredObservationPlan | None:
        row = (
            self._s.execute(
                select(ObservationPlanRow).where(
                    ObservationPlanRow.run_id == run_id,
                    ObservationPlanRow.owner_id == _owner(owner_id),
                )
            )
            .scalars()
            .first()
        )
        return self._row_to_plan(row) if row is not None else None

    def _find_request_by_idempotency(
        self, owner_id: str, idempotency_key: str
    ) -> ObservationPlanningRequestRow | None:
        return (
            self._s.execute(
                select(ObservationPlanningRequestRow).where(
                    ObservationPlanningRequestRow.owner_id == owner_id,
                    ObservationPlanningRequestRow.idempotency_key == idempotency_key,
                )
            )
            .scalars()
            .first()
        )

    def _find_run_by_identity(
        self, request_id: str, identity_checksum: str
    ) -> ObservationPlanningRunRow | None:
        return (
            self._s.execute(
                select(ObservationPlanningRunRow).where(
                    ObservationPlanningRunRow.request_id == request_id,
                    ObservationPlanningRunRow.scientific_identity_checksum == identity_checksum,
                )
            )
            .scalars()
            .first()
        )

    def _request_row(self, request_id: str, owner_id: str) -> ObservationPlanningRequestRow | None:
        return (
            self._s.execute(
                select(ObservationPlanningRequestRow).where(
                    ObservationPlanningRequestRow.id == request_id,
                    ObservationPlanningRequestRow.owner_id == owner_id,
                )
            )
            .scalars()
            .first()
        )

    def _run_row(self, run_id: str, owner_id: str) -> ObservationPlanningRunRow | None:
        return (
            self._s.execute(
                select(ObservationPlanningRunRow).where(
                    ObservationPlanningRunRow.id == run_id,
                    ObservationPlanningRunRow.owner_id == owner_id,
                )
            )
            .scalars()
            .first()
        )

    def _plan_row(self, plan_id: str, owner_id: str) -> ObservationPlanRow | None:
        return (
            self._s.execute(
                select(ObservationPlanRow).where(
                    ObservationPlanRow.id == plan_id,
                    ObservationPlanRow.owner_id == owner_id,
                )
            )
            .scalars()
            .first()
        )

    def _row_to_request(
        self, row: ObservationPlanningRequestRow
    ) -> StoredObservationPlanningRequest:
        if row.request_schema_version != REQUEST_SCHEMA_VERSION:
            raise ValidationError("unsupported observation-planning request schema version")
        request = ObservationPlanningRequest.model_validate(row.request_json)
        checksum = planning_request_checksum(request)
        if checksum != row.request_checksum:
            raise ValidationError("observation-planning request checksum mismatch")
        if request.source_mode.value != row.source_mode:
            raise ValidationError("observation-planning request source-mode mismatch")
        return StoredObservationPlanningRequest(
            id=row.id,
            owner_id=row.owner_id,
            request_checksum=row.request_checksum,
            request=request,
            source_mode=row.source_mode,
            idempotency_key=row.idempotency_key,
        )

    def _row_to_run(self, row: ObservationPlanningRunRow) -> StoredObservationPlanningRun:
        if row.result_schema_version != RESULT_SCHEMA_VERSION:
            raise ValidationError("unsupported observation-planning result schema version")
        result = ObservationPlanningResult.model_validate(row.result_json)
        identity = ObservationPlanningScientificIdentity.model_validate(
            row.scientific_identity_json
        )
        if identity != result.scientific_identity:
            raise ValidationError("stored scientific identity does not match planning result")
        checksum = scientific_identity_checksum(identity)
        if checksum != row.scientific_identity_checksum:
            raise ValidationError("stored scientific identity checksum mismatch")
        _assert_row_matches_result(row, result)
        plan = (
            self._s.execute(
                select(ObservationPlanRow).where(
                    ObservationPlanRow.run_id == row.id,
                    ObservationPlanRow.owner_id == row.owner_id,
                )
            )
            .scalars()
            .first()
        )
        return StoredObservationPlanningRun(
            id=row.id,
            request_id=row.request_id,
            owner_id=row.owner_id,
            result=result,
            scientific_identity_checksum=row.scientific_identity_checksum,
            plan_id=plan.id if plan is not None else None,
        )

    def _row_to_plan(self, row: ObservationPlanRow) -> StoredObservationPlan:
        if row.plan_schema_version != PLAN_SCHEMA_VERSION:
            raise ValidationError("unsupported observation-plan schema version")
        evaluation = ScheduleEvaluation.model_validate(row.evaluation_json)
        identity = ObservationPlanningScientificIdentity.model_validate(
            row.scientific_identity_json
        )
        checksum = scientific_identity_checksum(identity)
        if checksum != row.scientific_identity_checksum:
            raise ValidationError("observation-plan scientific identity checksum mismatch")
        selected = tuple(str(item) for item in row.selected_opportunity_ids_json)
        if selected != tuple(evaluation.selected_opportunity_ids):
            raise ValidationError("observation-plan selected IDs disagree with evaluation")
        if identity.selected_opportunity_ids != selected:
            raise ValidationError("observation-plan selected IDs disagree with identity")
        if identity.problem_checksum != row.problem_checksum:
            raise ValidationError("observation-plan problem checksum mismatch")
        return StoredObservationPlan(
            id=row.id,
            run_id=row.run_id,
            owner_id=row.owner_id,
            problem_checksum=row.problem_checksum,
            selected_opportunity_ids=selected,
            evaluation=evaluation,
            limitations=tuple(str(item) for item in row.limitations_json),
            scientific_identity=identity,
            scientific_identity_checksum=row.scientific_identity_checksum,
        )


def _owner(owner_id: str) -> str:
    if not owner_id or owner_id.strip() != owner_id:
        raise ValidationError("owner_id must be non-empty and unpadded")
    return owner_id


def _plan_row(
    run_id: str,
    owner_id: str,
    result: ObservationPlanningResult,
    identity_checksum: str,
) -> ObservationPlanRow:
    if result.schedule is None or result.independent_evaluation is None:
        raise ValidationError("verified-feasible planning results require a persisted plan")
    identity = result.scientific_identity
    return ObservationPlanRow(
        id=new_id(),
        run_id=run_id,
        owner_id=owner_id,
        problem_checksum=result.problem_checksum,
        selected_opportunity_ids_json=list(result.schedule.selected_opportunity_ids),
        evaluation_json=result.independent_evaluation.model_dump(mode="json"),
        limitations_json=list(result.limitations),
        plan_schema_version=PLAN_SCHEMA_VERSION,
        scientific_identity_json=identity.model_dump(mode="json"),
        scientific_identity_checksum=identity_checksum,
        created_at=utcnow(),
    )


def _assert_row_matches_result(
    row: ObservationPlanningRunRow, result: ObservationPlanningResult
) -> None:
    if row.request_checksum != result.request_checksum:
        raise ValidationError("observation-planning run request checksum mismatch")
    if row.problem_checksum != result.problem_checksum:
        raise ValidationError("observation-planning run problem checksum mismatch")
    if row.planning_status != result.status.value:
        raise ValidationError("observation-planning run status mismatch")
    solver = result.selected_solver.value if result.selected_solver else None
    if row.authoritative_solver != solver:
        raise ValidationError("observation-planning run solver mismatch")
    solver_status = result.solver_execution_status.value if result.solver_execution_status else None
    if row.solver_execution_status != solver_status:
        raise ValidationError("observation-planning run solver status mismatch")
    if row.optimality_label != result.optimality_label.value:
        raise ValidationError("observation-planning run optimality mismatch")
    label = result.verification_label.value if result.verification_label else None
    if row.verification_label != label:
        raise ValidationError("observation-planning run verification-label mismatch")
    if row.source_mode != result.source_mode.value:
        raise ValidationError("observation-planning run source-mode mismatch")
    if row.feasible != result.feasible:
        raise ValidationError("observation-planning run feasible flag mismatch")
    if row.objective_value is None and result.objective_value is not None:
        raise ValidationError("observation-planning run objective mismatch")
    if row.objective_value is not None and result.objective_value is None:
        raise ValidationError("observation-planning run objective mismatch")
    if (
        row.objective_value is not None
        and result.objective_value is not None
        and not math.isclose(row.objective_value, result.objective_value, rel_tol=0.0, abs_tol=1e-9)
    ):
        raise ValidationError("observation-planning run objective mismatch")
