"""Immutable links from provenance-backed preparation to persisted planning execution."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.core.checksums import sha256_canonical_json
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.observation_planning.models import ObservationPlanningResult
from orbitmind.observation_planning.provenance_preparation import (
    PreparedEligibilityPlanningRequest,
)
from orbitmind.persistence.observation_planning_models import (
    ObservationPlanningProvenanceLinkRow,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
)
from orbitmind.persistence.observation_planning_repository import (
    SqlAlchemyObservationPlanningRepository,
    normalize_owner_id,
)

LINK_SCHEMA_VERSION = "observation-planning-provenance-link-v1"


class StoredProvenancePlanningLink(BaseModel):
    """Typed persisted provenance-to-planning derivation link."""

    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    provenance_record_id: str
    provenance_checksum: str
    eligibility_set_record_id: str
    eligibility_set_checksum: str
    preparation_checksum: str
    planning_request_checksum: str
    planning_scientific_identity_checksum: str
    planning_request_id: str
    planning_run_id: str
    observation_plan_id: str | None
    selected_window_ids: tuple[str, ...]
    planning_status: str
    authoritative_solver: str | None
    optimality_label: str
    feasible: bool
    objective_value: float | None
    limitations: tuple[str, ...]
    link_checksum: str
    link_json: dict[str, Any]


class SqlAlchemyObservationPlanningLinkRepository:
    """Owner-scoped append-only persistence for provenance-anchored planning links."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create_provenance_planning_link(
        self,
        *,
        owner_id: str,
        preparation: PreparedEligibilityPlanningRequest,
        planning_request_id: str,
        planning_run_id: str,
        observation_plan_id: str | None,
        result: ObservationPlanningResult,
        planning_scientific_identity_checksum: str,
        use_savepoint: bool = True,
    ) -> StoredProvenancePlanningLink:
        owner = normalize_owner_id(owner_id)
        link = _link_identity(
            preparation=preparation,
            result=result,
            planning_scientific_identity_checksum=planning_scientific_identity_checksum,
            observation_plan_id=observation_plan_id,
        )
        checksum = link_checksum(link)
        existing = self._find_link_by_checksum(owner, checksum)
        if existing is not None:
            stored = self._row_to_link(existing)
            if stored.link_json != _link_snapshot(
                owner_id=owner,
                preparation=preparation,
                planning_request_id=planning_request_id,
                planning_run_id=planning_run_id,
                observation_plan_id=observation_plan_id,
                link_identity=link,
            ):
                raise ValidationError("stored provenance-planning link disagrees with checksum")
            return stored

        existing = self._find_link_by_preparation_and_run(
            owner,
            preparation.preparation_checksum,
            planning_run_id,
        )
        if existing is not None:
            stored = self._row_to_link(existing)
            if stored.link_checksum != checksum:
                raise ValidationError("stored provenance-planning link identity conflict")
            return stored

        self._validate_references(
            owner_id=owner,
            preparation=preparation,
            planning_request_id=planning_request_id,
            planning_run_id=planning_run_id,
            observation_plan_id=observation_plan_id,
            result=result,
            planning_scientific_identity_checksum=planning_scientific_identity_checksum,
        )
        snapshot = _link_snapshot(
            owner_id=owner,
            preparation=preparation,
            planning_request_id=planning_request_id,
            planning_run_id=planning_run_id,
            observation_plan_id=observation_plan_id,
            link_identity=link,
        )
        row = ObservationPlanningProvenanceLinkRow(
            id=new_id(),
            owner_id=owner,
            provenance_record_id=preparation.provenance_record_id,
            provenance_checksum=preparation.provenance_checksum,
            eligibility_set_record_id=preparation.eligibility_set_record_id,
            eligibility_set_checksum=preparation.eligibility_set_checksum,
            preparation_checksum=preparation.preparation_checksum,
            planning_request_checksum=preparation.planning_request_checksum,
            planning_scientific_identity_checksum=planning_scientific_identity_checksum,
            planning_request_id=planning_request_id,
            planning_run_id=planning_run_id,
            observation_plan_id=observation_plan_id,
            selected_window_ids_json=list(preparation.selected_window_ids),
            planning_status=result.status.value,
            authoritative_solver=result.selected_solver.value if result.selected_solver else None,
            optimality_label=result.optimality_label.value,
            feasible=result.feasible,
            objective_value=result.objective_value,
            limitations_json=list(link["limitations"]),
            link_schema_version=LINK_SCHEMA_VERSION,
            link_json=snapshot,
            link_checksum=checksum,
            created_at=utcnow(),
        )

        def insert() -> None:
            self._s.add(row)
            self._s.flush()

        if use_savepoint:
            try:
                with self._s.begin_nested():
                    insert()
            except IntegrityError:
                self._s.expire_all()
                existing = self._find_link_by_checksum(owner, checksum)
                if existing is None:
                    raise
                stored = self._row_to_link(existing)
                if stored.link_json != snapshot:
                    raise ValidationError(
                        "stored provenance-planning link disagrees with checksum"
                    ) from None
                return stored
        else:
            insert()
        return self._row_to_link(row)

    def get_provenance_planning_link(
        self,
        link_id: str,
        *,
        owner_id: str,
    ) -> StoredProvenancePlanningLink | None:
        row = self._link_row(link_id, normalize_owner_id(owner_id))
        return self._row_to_link(row) if row is not None else None

    def get_link_by_preparation_and_run(
        self,
        *,
        owner_id: str,
        preparation_checksum: str,
        planning_run_id: str,
    ) -> StoredProvenancePlanningLink | None:
        row = self._find_link_by_preparation_and_run(
            normalize_owner_id(owner_id),
            preparation_checksum,
            planning_run_id,
        )
        return self._row_to_link(row) if row is not None else None

    def _validate_references(
        self,
        *,
        owner_id: str,
        preparation: PreparedEligibilityPlanningRequest,
        planning_request_id: str,
        planning_run_id: str,
        observation_plan_id: str | None,
        result: ObservationPlanningResult,
        planning_scientific_identity_checksum: str,
    ) -> None:
        provenance_repo = SqlAlchemyObservationPlanningProvenanceRepository(self._s)
        planning_repo = SqlAlchemyObservationPlanningRepository(self._s)
        provenance = provenance_repo.get_provenance(
            preparation.provenance_record_id,
            owner_id=owner_id,
        )
        if provenance is None:
            raise NotFoundError("input provenance not found")
        if provenance.provenance_checksum != preparation.provenance_checksum:
            raise ValidationError("input provenance checksum mismatch")
        window_set = provenance_repo.get_eligibility_window_set(
            preparation.eligibility_set_record_id,
            owner_id=owner_id,
        )
        if window_set is None:
            raise NotFoundError("eligibility-window set not found")
        if window_set.eligibility_set_checksum != preparation.eligibility_set_checksum:
            raise ValidationError("eligibility-window set checksum mismatch")
        if window_set.source_provenance_id != provenance.id:
            raise ValidationError("eligibility-window set source provenance mismatch")
        if window_set.window_set.source_provenance.checksum != provenance.provenance_checksum:
            raise ValidationError("eligibility-window set source checksum mismatch")
        window_ids = {window.id for window in window_set.window_set.windows}
        if any(window_id not in window_ids for window_id in preparation.selected_window_ids):
            raise ValidationError("selected eligibility window ID not found")

        request = planning_repo.get_planning_request(planning_request_id, owner_id=owner_id)
        if request is None:
            raise NotFoundError("observation-planning request not found")
        if request.request_checksum != preparation.planning_request_checksum:
            raise ValidationError("planning request checksum mismatch")
        if _without_idempotency(request.request) != preparation.prepared_request:
            raise ValidationError("planning request snapshot mismatch")
        run = planning_repo.get_planning_run(planning_run_id, owner_id=owner_id)
        if run is None:
            raise NotFoundError("observation-planning run not found")
        if run.request_id != request.id:
            raise ValidationError("planning run does not belong to planning request")
        if run.result != result:
            raise ValidationError("planning run result mismatch")
        if run.scientific_identity_checksum != planning_scientific_identity_checksum:
            raise ValidationError("planning run scientific identity checksum mismatch")
        if result.request_checksum != preparation.planning_request_checksum:
            raise ValidationError("planning result request checksum mismatch")
        if observation_plan_id is None:
            if run.plan_id is not None:
                raise ValidationError("planning link missing persisted plan reference")
        else:
            if run.plan_id != observation_plan_id:
                raise ValidationError("observation plan does not belong to planning run")
            plan = planning_repo.get_observation_plan(observation_plan_id, owner_id=owner_id)
            if plan is None:
                raise NotFoundError("observation plan not found")
            if plan.run_id != run.id:
                raise ValidationError("observation plan run mismatch")
            if plan.scientific_identity_checksum != planning_scientific_identity_checksum:
                raise ValidationError("observation plan scientific identity checksum mismatch")

    def _find_link_by_checksum(
        self,
        owner_id: str,
        checksum: str,
    ) -> ObservationPlanningProvenanceLinkRow | None:
        return (
            self._s.execute(
                select(ObservationPlanningProvenanceLinkRow).where(
                    ObservationPlanningProvenanceLinkRow.owner_id == owner_id,
                    ObservationPlanningProvenanceLinkRow.link_checksum == checksum,
                )
            )
            .scalars()
            .first()
        )

    def _find_link_by_preparation_and_run(
        self,
        owner_id: str,
        preparation_checksum: str,
        planning_run_id: str,
    ) -> ObservationPlanningProvenanceLinkRow | None:
        return (
            self._s.execute(
                select(ObservationPlanningProvenanceLinkRow).where(
                    ObservationPlanningProvenanceLinkRow.owner_id == owner_id,
                    ObservationPlanningProvenanceLinkRow.preparation_checksum
                    == preparation_checksum,
                    ObservationPlanningProvenanceLinkRow.planning_run_id == planning_run_id,
                )
            )
            .scalars()
            .first()
        )

    def _link_row(
        self,
        link_id: str,
        owner_id: str,
    ) -> ObservationPlanningProvenanceLinkRow | None:
        return (
            self._s.execute(
                select(ObservationPlanningProvenanceLinkRow).where(
                    ObservationPlanningProvenanceLinkRow.owner_id == owner_id,
                    ObservationPlanningProvenanceLinkRow.id == link_id,
                )
            )
            .scalars()
            .first()
        )

    def _row_to_link(
        self,
        row: ObservationPlanningProvenanceLinkRow,
    ) -> StoredProvenancePlanningLink:
        if row.link_schema_version != LINK_SCHEMA_VERSION:
            raise ValidationError("unsupported provenance-planning link schema version")
        snapshot = dict(row.link_json)
        _assert_snapshot_matches_row(row, snapshot)
        identity = dict(snapshot["link_identity"])
        checksum = link_checksum(identity)
        if checksum != row.link_checksum:
            raise ValidationError("provenance-planning link checksum mismatch")
        selected = tuple(str(item) for item in row.selected_window_ids_json)
        if selected != tuple(identity["selected_window_ids"]):
            raise ValidationError("provenance-planning link selected windows mismatch")
        limitations = tuple(str(item) for item in row.limitations_json)
        if limitations != tuple(identity["limitations"]):
            raise ValidationError("provenance-planning link limitations mismatch")
        objective = identity["independent_objective"]
        if not _objectives_match(row.objective_value, objective):
            raise ValidationError("provenance-planning link objective mismatch")
        provenance_repo = SqlAlchemyObservationPlanningProvenanceRepository(self._s)
        provenance = provenance_repo.get_provenance(row.provenance_record_id, owner_id=row.owner_id)
        if provenance is None:
            raise ValidationError("provenance-planning link provenance missing")
        if provenance.provenance_checksum != row.provenance_checksum:
            raise ValidationError("provenance-planning link provenance checksum mismatch")
        window_set = provenance_repo.get_eligibility_window_set(
            row.eligibility_set_record_id,
            owner_id=row.owner_id,
        )
        if window_set is None:
            raise ValidationError("provenance-planning link eligibility set missing")
        if window_set.eligibility_set_checksum != row.eligibility_set_checksum:
            raise ValidationError("provenance-planning link eligibility checksum mismatch")
        if window_set.source_provenance_id != provenance.id:
            raise ValidationError("provenance-planning link eligibility provenance mismatch")
        window_ids = {window.id for window in window_set.window_set.windows}
        if any(window_id not in window_ids for window_id in selected):
            raise ValidationError("provenance-planning link selected windows mismatch")
        planning_repo = SqlAlchemyObservationPlanningRepository(self._s)
        request = planning_repo.get_planning_request(
            row.planning_request_id,
            owner_id=row.owner_id,
        )
        if request is None:
            raise ValidationError("provenance-planning link request missing")
        if request.request_checksum != row.planning_request_checksum:
            raise ValidationError("provenance-planning link request checksum mismatch")
        run = planning_repo.get_planning_run(row.planning_run_id, owner_id=row.owner_id)
        if run is None:
            raise ValidationError("provenance-planning link run missing")
        if run.request_id != row.planning_request_id:
            raise ValidationError("provenance-planning link run/request mismatch")
        if run.scientific_identity_checksum != row.planning_scientific_identity_checksum:
            raise ValidationError("provenance-planning link scientific identity mismatch")
        if row.observation_plan_id is None:
            if run.plan_id is not None:
                raise ValidationError("provenance-planning link missing plan")
        elif run.plan_id != row.observation_plan_id:
            raise ValidationError("provenance-planning link plan/run mismatch")
        if row.planning_status != run.result.status.value:
            raise ValidationError("provenance-planning link status mismatch")
        solver = run.result.selected_solver.value if run.result.selected_solver else None
        if row.authoritative_solver != solver:
            raise ValidationError("provenance-planning link solver mismatch")
        if row.optimality_label != run.result.optimality_label.value:
            raise ValidationError("provenance-planning link optimality mismatch")
        if row.feasible != run.result.feasible:
            raise ValidationError("provenance-planning link feasible mismatch")
        if not _objectives_match(row.objective_value, run.result.objective_value):
            raise ValidationError("provenance-planning link run objective mismatch")
        return StoredProvenancePlanningLink(
            id=row.id,
            owner_id=row.owner_id,
            provenance_record_id=row.provenance_record_id,
            provenance_checksum=row.provenance_checksum,
            eligibility_set_record_id=row.eligibility_set_record_id,
            eligibility_set_checksum=row.eligibility_set_checksum,
            preparation_checksum=row.preparation_checksum,
            planning_request_checksum=row.planning_request_checksum,
            planning_scientific_identity_checksum=row.planning_scientific_identity_checksum,
            planning_request_id=row.planning_request_id,
            planning_run_id=row.planning_run_id,
            observation_plan_id=row.observation_plan_id,
            selected_window_ids=selected,
            planning_status=row.planning_status,
            authoritative_solver=row.authoritative_solver,
            optimality_label=row.optimality_label,
            feasible=row.feasible,
            objective_value=row.objective_value,
            limitations=limitations,
            link_checksum=row.link_checksum,
            link_json=snapshot,
        )


def link_checksum(link_identity: dict[str, Any]) -> str:
    """Checksum deterministic link identity, excluding row/database metadata."""

    return sha256_canonical_json(link_identity)


def _link_identity(
    *,
    preparation: PreparedEligibilityPlanningRequest,
    result: ObservationPlanningResult,
    planning_scientific_identity_checksum: str,
    observation_plan_id: str | None,
) -> dict[str, Any]:
    limitations = tuple(dict.fromkeys((*preparation.limitations, *result.limitations)))
    return {
        "schema_version": LINK_SCHEMA_VERSION,
        "provenance_checksum": preparation.provenance_checksum,
        "eligibility_set_checksum": preparation.eligibility_set_checksum,
        "preparation_checksum": preparation.preparation_checksum,
        "planning_request_checksum": preparation.planning_request_checksum,
        "planning_scientific_identity_checksum": planning_scientific_identity_checksum,
        "selected_window_ids": list(preparation.selected_window_ids),
        "planning_status": result.status.value,
        "authoritative_solver": result.selected_solver.value if result.selected_solver else None,
        "optimality_label": result.optimality_label.value,
        "feasible": result.feasible,
        "independent_objective": result.objective_value,
        "plan_present": observation_plan_id is not None,
        "plan_scientific_identity_checksum": (
            planning_scientific_identity_checksum if observation_plan_id is not None else None
        ),
        "limitations": list(limitations),
    }


def _link_snapshot(
    *,
    owner_id: str,
    preparation: PreparedEligibilityPlanningRequest,
    planning_request_id: str,
    planning_run_id: str,
    observation_plan_id: str | None,
    link_identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": LINK_SCHEMA_VERSION,
        "owner_id": owner_id,
        "provenance_record_id": preparation.provenance_record_id,
        "provenance_checksum": preparation.provenance_checksum,
        "eligibility_set_record_id": preparation.eligibility_set_record_id,
        "eligibility_set_checksum": preparation.eligibility_set_checksum,
        "preparation_checksum": preparation.preparation_checksum,
        "planning_request_checksum": preparation.planning_request_checksum,
        "planning_request_id": planning_request_id,
        "planning_run_id": planning_run_id,
        "observation_plan_id": observation_plan_id,
        "selected_window_ids": list(preparation.selected_window_ids),
        "link_identity": link_identity,
    }


def _assert_snapshot_matches_row(
    row: ObservationPlanningProvenanceLinkRow,
    snapshot: dict[str, Any],
) -> None:
    expected: dict[str, object] = {
        "schema_version": row.link_schema_version,
        "owner_id": row.owner_id,
        "provenance_record_id": row.provenance_record_id,
        "provenance_checksum": row.provenance_checksum,
        "eligibility_set_record_id": row.eligibility_set_record_id,
        "eligibility_set_checksum": row.eligibility_set_checksum,
        "preparation_checksum": row.preparation_checksum,
        "planning_request_checksum": row.planning_request_checksum,
        "planning_request_id": row.planning_request_id,
        "planning_run_id": row.planning_run_id,
        "observation_plan_id": row.observation_plan_id,
        "selected_window_ids": list(row.selected_window_ids_json),
    }
    for key, value in expected.items():
        if snapshot.get(key) != value:
            raise ValidationError(f"provenance-planning link {key} mismatch")
    identity = snapshot.get("link_identity")
    if not isinstance(identity, dict):
        raise ValidationError("provenance-planning link identity snapshot mismatch")
    identity_expected: dict[str, object] = {
        "schema_version": row.link_schema_version,
        "provenance_checksum": row.provenance_checksum,
        "eligibility_set_checksum": row.eligibility_set_checksum,
        "preparation_checksum": row.preparation_checksum,
        "planning_request_checksum": row.planning_request_checksum,
        "planning_scientific_identity_checksum": row.planning_scientific_identity_checksum,
        "selected_window_ids": list(row.selected_window_ids_json),
        "planning_status": row.planning_status,
        "authoritative_solver": row.authoritative_solver,
        "optimality_label": row.optimality_label,
        "feasible": row.feasible,
        "independent_objective": row.objective_value,
        "plan_present": row.observation_plan_id is not None,
        "plan_scientific_identity_checksum": (
            row.planning_scientific_identity_checksum
            if row.observation_plan_id is not None
            else None
        ),
        "limitations": list(row.limitations_json),
    }
    for key, value in identity_expected.items():
        if identity.get(key) != value:
            raise ValidationError(f"provenance-planning link identity {key} mismatch")


def _objectives_match(left: float | None, right: object) -> bool:
    if left is None:
        return right is None
    if not isinstance(right, int | float):
        return False
    return math.isclose(left, float(right), rel_tol=0.0, abs_tol=1e-9)


def _without_idempotency(request: object) -> object:
    if hasattr(request, "model_copy"):
        return request.model_copy(update={"idempotency_key": None})
    return request
