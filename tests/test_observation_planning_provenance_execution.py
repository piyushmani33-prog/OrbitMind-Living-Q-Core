"""Tests for transactional provenance-anchored planning execution."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import orbitmind.observation_geometry.persistence_service as geometry_persistence_service
import orbitmind.observation_geometry.service as geometry_service
import orbitmind.observation_planning.orchestration as orchestration_module
import orbitmind.observation_planning.provenance_execution as execution_module
import orbitmind.persistence.observation_geometry_models  # noqa: F401 - register metadata
import orbitmind.persistence.observation_planning_link_repository as link_repository_module
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import IdempotencyConflictError, NotFoundError, ValidationError
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_planning import ProvenanceAnchoredPlanningExecution
from orbitmind.observation_planning.geometry_eligibility_adapter import (
    GEOMETRY_DERIVED_ACCESS_LIMITATION,
    GEOMETRY_DERIVED_LIMITATION,
    GeometryDerivedEligibilityResult,
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.provenance import (
    EligibilityDeclarationMode,
    EligibilityWindow,
    EligibilityWindowSet,
    InputRightsDeclaration,
    InputRightsPermission,
    InputRightsStatus,
    InputSourceIdentity,
    PinnedInputArtifact,
    PinnedInputProvenance,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.observation_planning.provenance_execution import (
    execute_provenance_anchored_planning,
)
from orbitmind.observation_planning.service import plan_observation_request
from orbitmind.optimization.models import (
    ExperimentStatus,
    OptimalityStatus,
    SchedulingProblem,
    SchedulingProblemLimits,
    SolverConfiguration,
    SolverKind,
    SolverResult,
)
from orbitmind.optimization.solvers.base import build_result
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_planning_link_repository import (
    SqlAlchemyObservationPlanningLinkRepository,
    StoredProvenancePlanningLink,
    link_checksum,
)
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationInputProvenanceRow,
    ObservationPlanningProvenanceLinkRow,
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
    ObservationPlanRow,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
)
from orbitmind.sources.registry import SourceRegistry


def _checksum(label: str) -> str:
    return sha256_text(label)


def _db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'anchored-planning.db').as_posix()}")
    db.create_all()
    return db


def _session(tmp_path: Path) -> Session:
    return _db(tmp_path).session()


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _geometry_request(site_id: str = "SITE-ANCHOR") -> GeometryComputationRequest:
    start = dt.datetime(2019, 12, 9, 19, 50, tzinfo=dt.UTC)
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} geometry-derived anchored execution site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=start,
        end=start + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _persist_geometry_derived_eligibility(
    session: Session,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-ANCHOR",
) -> GeometryDerivedEligibilityResult:
    geometry_execution = execute_and_persist_geometry(
        session=session,
        owner_id=owner_id,
        request=_geometry_request(site_id),
        idempotency_key=f"geometry-derived-anchored:{site_id}",
    )
    return derive_eligibility_from_geometry_run(
        session=session,
        owner_id=owner_id,
        geometry_run_id=geometry_execution.run_id,
        requested_by="geometry-analyst",
    )


def _rights(status: InputRightsStatus = InputRightsStatus.DECLARED) -> InputRightsDeclaration:
    return InputRightsDeclaration(
        rights_status=status,
        redistribution=InputRightsPermission.UNKNOWN,
        commercial_use=InputRightsPermission.UNKNOWN,
        attribution_required=status == InputRightsStatus.VERIFIED,
        user_responsibility="caller retains responsibility for declared input rights",
        limitations=("recorded declaration only",),
    )


def _artifact(label: str) -> PinnedInputArtifact:
    return PinnedInputArtifact(
        artifact_id=f"artifact-{label}",
        content_checksum=_checksum(label),
        media_type="application/json",
        record_count=2,
    )


def _provenance(
    source_type: PinnedInputSourceType = PinnedInputSourceType.FIXTURE,
    *,
    label: str = "fixture",
    parent: PinnedInputProvenance | None = None,
) -> PinnedInputProvenance:
    if source_type == PinnedInputSourceType.USER_DECLARED:
        return PinnedInputProvenance(
            source=InputSourceIdentity(
                source_id=f"{label}-source",
                source_type=source_type,
                source_mode=PinnedInputSourceMode.USER_DECLARED,
            ),
            artifact=_artifact(label),
            declared_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
            rights=_rights(InputRightsStatus.DECLARED),
            verification_status=ScientificInputVerificationStatus.USER_DECLARED,
        )
    if source_type == PinnedInputSourceType.DERIVED:
        assert parent is not None
        return PinnedInputProvenance(
            source=InputSourceIdentity(
                source_id=f"{label}-source",
                source_type=source_type,
                source_mode=PinnedInputSourceMode.DERIVED_FROM_DECLARED_INPUT,
                dataset_name="derived-eligibility",
                dataset_version="v1",
            ),
            artifact=_artifact(label),
            retrieved_at=dt.datetime(2026, 6, 21, 9, 5, tzinfo=dt.UTC),
            rights=_rights(InputRightsStatus.DECLARED),
            verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
            parent_provenance_checksums=(parent.checksum,),
        )
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=source_type,
            source_mode=PinnedInputSourceMode.FIXTURE_BACKED,
            publisher="OrbitMind",
            dataset_name="fixture-observation-eligibility",
            dataset_version="v1",
        ),
        artifact=_artifact(label),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.VERIFIED),
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _window(
    window_id: str,
    provenance: PinnedInputProvenance,
    *,
    start_minute: int = 0,
    end_minute: int = 30,
    asset_id: str = "SAT-A",
    target_id: str = "T1",
) -> EligibilityWindow:
    mode = (
        EligibilityDeclarationMode.FIXTURE_BACKED
        if provenance.source.source_type == PinnedInputSourceType.FIXTURE
        else EligibilityDeclarationMode.USER_DECLARED
        if provenance.source.source_type == PinnedInputSourceType.USER_DECLARED
        else EligibilityDeclarationMode.DERIVED_FROM_DECLARED_INPUT
    )
    status = (
        ScientificInputVerificationStatus.FIXTURE_VERIFIED
        if mode == EligibilityDeclarationMode.FIXTURE_BACKED
        else ScientificInputVerificationStatus.USER_DECLARED
        if mode == EligibilityDeclarationMode.USER_DECLARED
        else ScientificInputVerificationStatus.DERIVED_FROM_DECLARED
    )
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    return EligibilityWindow(
        id=window_id,
        asset_id=asset_id,
        target_id=target_id,
        start=base + dt.timedelta(minutes=start_minute),
        end=base + dt.timedelta(minutes=end_minute),
        source_provenance_checksum=provenance.checksum,
        declaration_mode=mode,
        eligibility_reason="declared-candidate",
        verification_status=status,
    )


def _persist_set(
    session: Session,
    provenance: PinnedInputProvenance,
    *,
    owner_id: str = "owner-a",
    windows: tuple[EligibilityWindow, ...] | None = None,
) -> str:
    repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
    if provenance.source.source_type == PinnedInputSourceType.DERIVED:
        for checksum in provenance.parent_provenance_checksums:
            if repo.get_provenance_by_checksum(checksum, owner_id=owner_id) is None:
                raise AssertionError("derived parent must be persisted before child")
    repo.create_provenance(provenance, owner_id=owner_id)
    window_set = EligibilityWindowSet(
        source_provenance=provenance,
        windows=windows if windows is not None else (_window("W1", provenance),),
    )
    stored = repo.create_eligibility_window_set(window_set, owner_id=owner_id)
    session.commit()
    return stored.id


def _execute(
    session: Session,
    set_id: str,
    *,
    owner_id: str = "owner-a",
    requested_by: str = "analyst-a",
    selected_window_ids: tuple[str, ...] | None = None,
    idempotency_key: str | None = None,
) -> ProvenanceAnchoredPlanningExecution:
    return execute_provenance_anchored_planning(
        session=session,
        owner_id=owner_id,
        eligibility_set_id=set_id,
        requested_by=requested_by,
        selected_window_ids=selected_window_ids,
        idempotency_key=idempotency_key,
    )


def _timed_out_planner(request: object) -> object:
    def timeout_exact(
        problem: SchedulingProblem,
        config: SolverConfiguration,
        evaluator: object,
    ) -> SolverResult:
        return build_result(
            solver_kind=SolverKind.EXACT,
            solver_name="fake-timeout",
            solver_version="test",
            problem_checksum=problem.checksum,
            config=config,
            evaluation=None,
            status=ExperimentStatus.TIMED_OUT,
            optimality=OptimalityStatus.UNKNOWN,
            known_optimum=None,
            runtime_seconds=0.0,
            evaluated_candidates=0,
            limitations="deterministic timeout for anchored execution test",
        )

    return plan_observation_request(
        request,
        exact_solver=timeout_exact,
        allow_greedy_fallback=False,
    )


def _count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _graph_counts(session: Session) -> tuple[int, int, int, int]:
    return (
        _count(session, ObservationPlanningRequestRow),
        _count(session, ObservationPlanningRunRow),
        _count(session, ObservationPlanRow),
        _count(session, ObservationPlanningProvenanceLinkRow),
    )


def test_successful_fixture_backed_anchored_execution(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        set_id = _persist_set(session, _provenance())
        execution = _execute(session, set_id)
        fetched = SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
            execution.link_record_id, owner_id="owner-a"
        )

    assert execution.request_created is True
    assert execution.run_created is True
    assert execution.plan_created is True
    assert execution.observation_plan_id is not None
    assert fetched is not None
    assert execution.link_checksum == fetched.link_checksum
    assert execution.selected_window_ids == ("W1",)


def test_user_declared_and_derived_anchored_execution(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        declared_set = _persist_set(
            session,
            _provenance(PinnedInputSourceType.USER_DECLARED, label="declared"),
        )
        declared = _execute(session, declared_set, requested_by="declared-user")

        parent = _provenance(PinnedInputSourceType.USER_DECLARED, label="parent")
        repo = SqlAlchemyObservationPlanningProvenanceRepository(session)
        repo.create_provenance(parent, owner_id="owner-a")
        derived = _provenance(PinnedInputSourceType.DERIVED, label="derived", parent=parent)
        derived_set = _persist_set(session, derived)
        derived_execution = _execute(session, derived_set)

    assert declared.source_type == PinnedInputSourceType.USER_DECLARED
    assert declared.preparation.prepared_request.requested_by == "declared-user"
    assert derived_execution.source_type == PinnedInputSourceType.DERIVED


def test_subset_canonical_order_and_changed_subset_identity(tmp_path: Path) -> None:
    provenance = _provenance(label="subset")
    windows = (
        _window("W-B", provenance, asset_id="SAT-B", start_minute=0, end_minute=30),
        _window("W-A", provenance, asset_id="SAT-A", start_minute=40, end_minute=70),
        _window("W-C", provenance, asset_id="SAT-C", start_minute=80, end_minute=110),
    )
    with _session(tmp_path) as session:
        set_id = _persist_set(session, provenance, windows=windows)
        first = _execute(session, set_id, selected_window_ids=("W-C", "W-A"))
        replay = _execute(session, set_id, selected_window_ids=("W-A", "W-C"))
        changed = _execute(session, set_id, selected_window_ids=("W-A", "W-B"))

    assert first.selected_window_ids == ("W-A", "W-C")
    assert replay.link_record_id == first.link_record_id
    assert replay.request_created is False
    assert replay.run_created is False
    assert changed.link_record_id != first.link_record_id
    assert changed.preparation_checksum != first.preparation_checksum


def test_greedy_path_with_more_than_exact_limit(tmp_path: Path) -> None:
    provenance = _provenance(label="greedy")
    windows = tuple(
        _window(
            f"W-{index:02d}",
            provenance,
            asset_id=f"SAT-{index:02d}",
            target_id=f"T-{index:02d}",
            start_minute=index * 5,
            end_minute=index * 5 + 3,
        )
        for index in range(23)
    )
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, provenance, windows=windows))

    assert execution.authoritative_solver is not None
    assert execution.authoritative_solver.value == "greedy"
    assert execution.planning_execution.result.problem_checksum


def test_non_success_anchored_execution_persists_run_and_link_without_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session(tmp_path) as session:
        set_id = _persist_set(session, _provenance(label="timed-out"))
        monkeypatch.setattr(orchestration_module, "plan_observation_request", _timed_out_planner)
        execution = _execute(session, set_id)
        fetched = SqlAlchemyObservationPlanningLinkRepository(
            session
        ).get_link_by_preparation_and_run(
            owner_id="owner-a",
            preparation_checksum=execution.preparation_checksum,
            planning_run_id=execution.planning_run_id,
        )

    assert execution.planning_status.value == "timed-out"
    assert execution.observation_plan_id is None
    assert execution.feasible is False
    assert execution.independent_objective is None
    assert fetched is not None
    assert fetched.observation_plan_id is None
    assert fetched.link_checksum == execution.link_checksum


def test_exact_replay_reuses_request_run_plan_and_link(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        set_id = _persist_set(session, _provenance(label="replay"))
        first = _execute(session, set_id)
        second = _execute(session, set_id)

    assert second.request_created is False
    assert second.run_created is False
    assert second.plan_created is False
    assert second.planning_request_id == first.planning_request_id
    assert second.planning_run_id == first.planning_run_id
    assert second.observation_plan_id == first.observation_plan_id
    assert second.link_record_id == first.link_record_id
    assert second.link_checksum == first.link_checksum


def test_geometry_derived_eligibility_enters_provenance_anchored_execution_and_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session(tmp_path) as session:
        derived = _persist_geometry_derived_eligibility(session)
        stored_set = SqlAlchemyObservationPlanningProvenanceRepository(
            session
        ).get_eligibility_window_set(
            derived.eligibility_set_record_id,
            owner_id="owner-a",
        )
        assert stored_set is not None
        selected_window_ids = tuple(window.id for window in stored_set.window_set.windows)
        assert selected_window_ids
        session.commit()

        first = _execute(
            session,
            derived.eligibility_set_record_id,
            requested_by="geometry-requester",
            selected_window_ids=tuple(reversed(selected_window_ids)),
        )
        fetched = SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
            first.link_record_id,
            owner_id="owner-a",
        )
        session.commit()

        def fail_geometry_compute(*_args: object, **_kwargs: object) -> object:
            raise AssertionError("anchored execution must not recompute geometry")

        def fail_planner(request: object) -> object:
            raise AssertionError("planner should not run on anchored replay")

        monkeypatch.setattr(
            geometry_persistence_service,
            "compute_observation_geometry",
            fail_geometry_compute,
        )
        monkeypatch.setattr(geometry_service, "compute_observation_geometry", fail_geometry_compute)
        monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)
        replay = _execute(
            session,
            derived.eligibility_set_record_id,
            requested_by="geometry-requester",
            selected_window_ids=selected_window_ids,
        )

    assert first.preparation.prepared_request.source_mode.value == "declared"
    assert first.source_type == PinnedInputSourceType.DERIVED
    assert first.source_verification_status == ScientificInputVerificationStatus.GEOMETRY_DERIVED
    assert first.selected_window_ids == selected_window_ids
    assert GEOMETRY_DERIVED_LIMITATION in first.preparation.limitations
    assert GEOMETRY_DERIVED_ACCESS_LIMITATION in first.preparation.limitations
    assert GEOMETRY_DERIVED_LIMITATION in first.link.limitations
    assert GEOMETRY_DERIVED_ACCESS_LIMITATION in first.link.limitations
    assert fetched is not None
    assert fetched.selected_window_ids == selected_window_ids
    assert fetched.link_checksum == first.link_checksum
    assert replay.request_created is False
    assert replay.run_created is False
    assert replay.plan_created is False
    assert replay.planning_request_id == first.planning_request_id
    assert replay.planning_run_id == first.planning_run_id
    assert replay.observation_plan_id == first.observation_plan_id
    assert replay.link_record_id == first.link_record_id
    assert replay.link_checksum == first.link_checksum


def test_geometry_derived_anchored_execution_blocks_cross_owner(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        derived = _persist_geometry_derived_eligibility(session)
        with pytest.raises(NotFoundError):
            _execute(
                session,
                derived.eligibility_set_record_id,
                owner_id="owner-b",
                requested_by="owner-a",
            )


def test_geometry_derived_anchored_execution_rejects_authenticated_tamper(
    tmp_path: Path,
) -> None:
    with _session(tmp_path) as session:
        provenance_tamper = _persist_geometry_derived_eligibility(
            session,
            site_id="SITE-GEOM-PROV-TAMPER",
        )
        provenance_row = session.get(
            ObservationInputProvenanceRow,
            provenance_tamper.provenance_record_id,
        )
        assert provenance_row is not None
        provenance_row.artifact_checksum = _checksum("geometry-derived-wrong-artifact")
        session.commit()
        with pytest.raises(ValidationError, match="artifact checksum"):
            _execute(session, provenance_tamper.eligibility_set_record_id)

        eligibility_tamper = _persist_geometry_derived_eligibility(
            session,
            site_id="SITE-GEOM-WINDOW-TAMPER",
        )
        window_row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id
                == eligibility_tamper.eligibility_set_record_id
            )
        )
        assert window_row is not None
        window_row.asset_id = "SAT-TAMPERED"
        session.commit()
        with pytest.raises(ValidationError, match="asset"):
            _execute(session, eligibility_tamper.eligibility_set_record_id)

        link_tamper = _persist_geometry_derived_eligibility(
            session,
            site_id="SITE-GEOM-LINK-TAMPER",
        )
        execution = _execute(session, link_tamper.eligibility_set_record_id)
        link_row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert link_row is not None
        link_row.selected_window_ids_json = ["missing-geometry-window"]
        with session.no_autoflush, pytest.raises(ValidationError, match="selected_window"):
            SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
                execution.link_record_id,
                owner_id="owner-a",
            )


def test_owner_isolation_and_requested_by_is_not_authority(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        provenance = _provenance(label="owner")
        set_id = _persist_set(session, provenance, owner_id="owner-a")
        _persist_set(session, provenance, owner_id="owner-b")
        with pytest.raises(NotFoundError):
            _execute(session, set_id, owner_id="owner-b", requested_by="owner-a")
        execution = _execute(session, set_id, owner_id="owner-a", requested_by="owner-b")

    assert execution.owner_id == "owner-a"
    assert execution.preparation.prepared_request.requested_by == "owner-b"


def test_idempotency_conflict_happens_before_solver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provenance = _provenance(label="conflict")
    windows = (
        _window("W1", provenance, asset_id="SAT-A"),
        _window("W2", provenance, asset_id="SAT-B", start_minute=40, end_minute=70),
    )

    def fail_planner(request: object) -> object:
        raise AssertionError("solver should not run after idempotency conflict")

    with _session(tmp_path) as session:
        set_id = _persist_set(session, provenance, windows=windows)
        _execute(session, set_id, selected_window_ids=("W1",), idempotency_key="shared-key")
        monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)
        with pytest.raises(IdempotencyConflictError):
            _execute(session, set_id, selected_window_ids=("W2",), idempotency_key="shared-key")
        assert _graph_counts(session) == (1, 1, 1, 1)


def test_preparation_and_planning_failures_roll_back_new_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session(tmp_path) as session:
        empty_set = _persist_set(session, _provenance(label="empty"), windows=())
        with pytest.raises(ValidationError, match="contains no windows"):
            _execute(session, empty_set)
        assert _graph_counts(session) == (0, 0, 0, 0)

        set_id = _persist_set(session, _provenance(label="planning-fails"))

        def fail_planner(request: object) -> object:
            raise RuntimeError("planning failed")

        monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)
        with pytest.raises(RuntimeError, match="planning failed"):
            _execute(session, set_id)
        assert _graph_counts(session) == (0, 0, 0, 0)


def test_link_failure_rolls_back_new_planning_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_link(self: object, **kwargs: object) -> object:
        raise RuntimeError("link failed")

    with _session(tmp_path) as session:
        set_id = _persist_set(session, _provenance(label="link-fails"))
        monkeypatch.setattr(
            SqlAlchemyObservationPlanningLinkRepository,
            "create_provenance_planning_link",
            fail_link,
        )
        with pytest.raises(RuntimeError, match="link failed"):
            _execute(session, set_id)
        assert _graph_counts(session) == (0, 0, 0, 0)


def test_provenance_and_window_tamper_propagate(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        set_id = _persist_set(session, _provenance(label="tamper"))
        provenance_row = session.scalar(select(ObservationInputProvenanceRow))
        assert provenance_row is not None
        provenance_row.artifact_checksum = _checksum("wrong")
        session.commit()
        with pytest.raises(ValidationError, match="artifact checksum"):
            _execute(session, set_id)

        set_id = _persist_set(session, _provenance(label="window-tamper"))
        window_row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id == set_id
            )
        )
        assert window_row is not None
        window_row.asset_id = "SAT-TAMPERED"
        session.commit()
        with pytest.raises(ValidationError, match="asset"):
            _execute(session, set_id)


def test_link_tamper_detection(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="link-tamper")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        row.objective_value = 999.0
        with pytest.raises(ValidationError, match="objective"):
            SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
                execution.link_record_id,
                owner_id="owner-a",
            )
        session.rollback()

        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        snapshot = dict(row.link_json)
        snapshot["planning_run_id"] = "wrong"
        session.execute(
            update(ObservationPlanningProvenanceLinkRow)
            .where(ObservationPlanningProvenanceLinkRow.id == execution.link_record_id)
            .values(link_json=snapshot)
        )
        session.flush()
        with pytest.raises(ValidationError, match="planning_run_id"):
            SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
                execution.link_record_id,
                owner_id="owner-a",
            )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("link_schema_version", "unsupported", "schema version"),
        ("link_checksum", _checksum("wrong-link"), "checksum"),
        ("selected_window_ids_json", ["missing-window"], "selected_window_ids"),
        ("limitations_json", ["changed limitation"], "limitations"),
        ("provenance_checksum", _checksum("wrong-provenance"), "provenance_checksum"),
        ("eligibility_set_checksum", _checksum("wrong-set"), "eligibility_set_checksum"),
        ("planning_request_checksum", _checksum("wrong-request"), "planning_request_checksum"),
        (
            "planning_scientific_identity_checksum",
            _checksum("wrong-identity"),
            "planning_scientific_identity_checksum",
        ),
        ("planning_status", "infeasible", "status"),
        ("authoritative_solver", "greedy", "solver"),
        ("optimality_label", "heuristic", "optimality"),
        ("feasible", False, "feasible"),
    ],
)
def test_link_column_tamper_detection(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label=f"column-{field}")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        setattr(row, field, value)
        with session.no_autoflush, pytest.raises(ValidationError, match=message):
            SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
                execution.link_record_id,
                owner_id="owner-a",
            )


@pytest.mark.parametrize(
    ("snapshot_update", "message"),
    [
        ({"link_identity": "not-a-dict"}, "identity snapshot"),
        ({"link_identity": {"schema_version": "wrong"}}, "identity schema_version"),
        ({"owner_id": "wrong-owner"}, "owner_id"),
    ],
)
def test_link_snapshot_tamper_detection(
    tmp_path: Path,
    snapshot_update: dict[str, object],
    message: str,
) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="snapshot")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        snapshot = dict(row.link_json)
        if "link_identity" in snapshot_update and isinstance(
            snapshot_update["link_identity"], dict
        ):
            identity = dict(snapshot["link_identity"])
            identity.update(snapshot_update["link_identity"])
            snapshot["link_identity"] = identity
        else:
            snapshot.update(snapshot_update)
        session.execute(
            update(ObservationPlanningProvenanceLinkRow)
            .where(ObservationPlanningProvenanceLinkRow.id == execution.link_record_id)
            .values(link_json=snapshot)
        )
        session.flush()
        with pytest.raises(ValidationError, match=message):
            SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
                execution.link_record_id,
                owner_id="owner-a",
            )


def test_link_replay_rejects_same_checksum_with_modified_snapshot(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="checksum-replay")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        snapshot = dict(row.link_json)
        snapshot["extra_trace_field"] = "not part of the authenticated snapshot"
        session.execute(
            update(ObservationPlanningProvenanceLinkRow)
            .where(ObservationPlanningProvenanceLinkRow.id == execution.link_record_id)
            .values(link_json=snapshot)
        )
        session.flush()
        with pytest.raises(ValidationError, match="disagrees with checksum"):
            SqlAlchemyObservationPlanningLinkRepository(session).create_provenance_planning_link(
                owner_id="owner-a",
                preparation=execution.preparation,
                planning_request_id=execution.planning_request_id,
                planning_run_id=execution.planning_run_id,
                observation_plan_id=execution.observation_plan_id,
                result=execution.planning_execution.result,
                planning_scientific_identity_checksum=(
                    execution.planning_execution.scientific_identity_checksum
                ),
            )


def test_link_replay_rejects_same_preparation_run_with_different_identity(
    tmp_path: Path,
) -> None:
    provenance = _provenance(label="identity-replay")
    windows = (
        _window("W1", provenance),
        _window("W2", provenance, asset_id="SAT-B", start_minute=40, end_minute=70),
    )
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, provenance, windows=windows))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        snapshot = dict(row.link_json)
        identity = dict(snapshot["link_identity"])
        changed_selection: list[str] = []
        identity["selected_window_ids"] = changed_selection
        snapshot["selected_window_ids"] = changed_selection
        snapshot["link_identity"] = identity
        changed_checksum = link_checksum(identity)
        session.execute(
            update(ObservationPlanningProvenanceLinkRow)
            .where(ObservationPlanningProvenanceLinkRow.id == execution.link_record_id)
            .values(
                selected_window_ids_json=changed_selection,
                link_json=snapshot,
                link_checksum=changed_checksum,
            )
        )
        session.flush()
        with pytest.raises(ValidationError, match="identity conflict"):
            SqlAlchemyObservationPlanningLinkRepository(session).create_provenance_planning_link(
                owner_id="owner-a",
                preparation=execution.preparation,
                planning_request_id=execution.planning_request_id,
                planning_run_id=execution.planning_run_id,
                observation_plan_id=execution.observation_plan_id,
                result=execution.planning_execution.result,
                planning_scientific_identity_checksum=(
                    execution.planning_execution.scientific_identity_checksum
                ),
            )


def test_link_repository_savepoint_race_recovers_matching_existing_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="race")))
        existing_row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert existing_row is not None
        repo = SqlAlchemyObservationPlanningLinkRepository(session)
        checksum_calls = 0

        def fake_find_by_checksum(
            owner_id: str,
            checksum: str,
        ) -> ObservationPlanningProvenanceLinkRow | None:
            nonlocal checksum_calls
            checksum_calls += 1
            if checksum_calls == 1:
                return None
            return existing_row

        def fake_find_by_preparation_and_run(
            owner_id: str,
            preparation_checksum: str,
            planning_run_id: str,
        ) -> ObservationPlanningProvenanceLinkRow | None:
            return None

        real_flush = session.flush

        def fail_link_flush() -> None:
            if any(isinstance(obj, ObservationPlanningProvenanceLinkRow) for obj in session.new):
                raise IntegrityError("insert", {}, RuntimeError("simulated unique race"))
            real_flush()

        monkeypatch.setattr(repo, "_find_link_by_checksum", fake_find_by_checksum)
        monkeypatch.setattr(
            repo,
            "_find_link_by_preparation_and_run",
            fake_find_by_preparation_and_run,
        )
        monkeypatch.setattr(session, "flush", fail_link_flush)

        recovered = repo.create_provenance_planning_link(
            owner_id="owner-a",
            preparation=execution.preparation,
            planning_request_id=execution.planning_request_id,
            planning_run_id=execution.planning_run_id,
            observation_plan_id=execution.observation_plan_id,
            result=execution.planning_execution.result,
            planning_scientific_identity_checksum=(
                execution.planning_execution.scientific_identity_checksum
            ),
        )

    assert recovered.id == execution.link_record_id
    assert checksum_calls == 2


def test_link_repository_no_savepoint_insert_and_helper_guards(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="no-savepoint")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        session.delete(row)
        session.commit()
        recreated = SqlAlchemyObservationPlanningLinkRepository(
            session
        ).create_provenance_planning_link(
            owner_id="owner-a",
            preparation=execution.preparation,
            planning_request_id=execution.planning_request_id,
            planning_run_id=execution.planning_run_id,
            observation_plan_id=execution.observation_plan_id,
            result=execution.planning_execution.result,
            planning_scientific_identity_checksum=(
                execution.planning_execution.scientific_identity_checksum
            ),
            use_savepoint=False,
        )

    plain = object()
    assert recreated.link_checksum == execution.link_checksum
    assert link_repository_module._objectives_match(1.0, "not numeric") is False
    assert link_repository_module._without_idempotency(plain) is plain


def test_link_deep_selected_window_validation(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="deep-selected")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        snapshot = dict(row.link_json)
        identity = dict(snapshot["link_identity"])
        identity["selected_window_ids"] = ["missing-window"]
        snapshot["selected_window_ids"] = ["missing-window"]
        snapshot["link_identity"] = identity
        session.execute(
            update(ObservationPlanningProvenanceLinkRow)
            .where(ObservationPlanningProvenanceLinkRow.id == execution.link_record_id)
            .values(
                selected_window_ids_json=["missing-window"],
                link_json=snapshot,
                link_checksum=link_checksum(identity),
            )
        )
        session.flush()
        with pytest.raises(ValidationError, match="selected windows"):
            SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
                execution.link_record_id,
                owner_id="owner-a",
            )


def _apply_link_tamper(
    row: ObservationPlanningProvenanceLinkRow,
    *,
    row_updates: dict[str, object],
    snapshot_updates: dict[str, object] | None = None,
    identity_updates: dict[str, object] | None = None,
) -> None:
    snapshot = dict(row.link_json)
    identity = dict(snapshot["link_identity"])
    for field, value in row_updates.items():
        setattr(row, field, value)
        if field in snapshot:
            snapshot[field] = value
        if field in identity:
            identity[field] = value
    if snapshot_updates is not None:
        snapshot.update(snapshot_updates)
    if identity_updates is not None:
        identity.update(identity_updates)
    snapshot["link_identity"] = identity
    row.link_json = snapshot
    row.link_checksum = link_checksum(identity)


@pytest.mark.parametrize(
    ("row_updates", "snapshot_updates", "identity_updates", "message"),
    [
        (
            {"selected_window_ids_json": ["other-window"]},
            {"selected_window_ids": ["other-window"]},
            None,
            "selected_window_ids",
        ),
        ({"limitations_json": ["other limitation"]}, None, None, "limitations"),
        ({"objective_value": 999.0}, None, None, "objective"),
        (
            {"provenance_record_id": "missing-provenance"},
            {"provenance_record_id": "missing-provenance"},
            None,
            "provenance missing",
        ),
        (
            {"eligibility_set_record_id": "missing-set"},
            {"eligibility_set_record_id": "missing-set"},
            None,
            "eligibility set missing",
        ),
        (
            {"planning_request_id": "missing-request"},
            {"planning_request_id": "missing-request"},
            None,
            "request missing",
        ),
        (
            {"planning_run_id": "missing-run"},
            {"planning_run_id": "missing-run"},
            None,
            "run missing",
        ),
        (
            {"provenance_checksum": _checksum("coherent-provenance")},
            {"provenance_checksum": _checksum("coherent-provenance")},
            {"provenance_checksum": _checksum("coherent-provenance")},
            "provenance checksum",
        ),
        (
            {"eligibility_set_checksum": _checksum("coherent-set")},
            {"eligibility_set_checksum": _checksum("coherent-set")},
            {"eligibility_set_checksum": _checksum("coherent-set")},
            "eligibility checksum",
        ),
        (
            {"planning_request_checksum": _checksum("coherent-request")},
            {"planning_request_checksum": _checksum("coherent-request")},
            {"planning_request_checksum": _checksum("coherent-request")},
            "request checksum",
        ),
        (
            {"planning_scientific_identity_checksum": _checksum("coherent-identity")},
            {
                "planning_scientific_identity_checksum": _checksum("coherent-identity"),
            },
            {
                "planning_scientific_identity_checksum": _checksum("coherent-identity"),
                "plan_scientific_identity_checksum": _checksum("coherent-identity"),
            },
            "scientific identity",
        ),
        (
            {"observation_plan_id": None},
            {"observation_plan_id": None},
            {"plan_present": False, "plan_scientific_identity_checksum": None},
            "missing plan",
        ),
        (
            {"observation_plan_id": "wrong-plan"},
            {"observation_plan_id": "wrong-plan"},
            {"plan_present": True},
            "plan/run",
        ),
        (
            {"planning_status": "infeasible"},
            None,
            {"planning_status": "infeasible"},
            "status",
        ),
        (
            {"authoritative_solver": "greedy"},
            None,
            {"authoritative_solver": "greedy"},
            "solver",
        ),
        (
            {"optimality_label": "heuristic"},
            None,
            {"optimality_label": "heuristic"},
            "optimality",
        ),
        ({"feasible": False}, None, {"feasible": False}, "feasible"),
        (
            {"objective_value": 999.0},
            None,
            {"independent_objective": 999.0},
            "run objective",
        ),
    ],
)
def test_link_relationship_tamper_detection(
    tmp_path: Path,
    row_updates: dict[str, object],
    snapshot_updates: dict[str, object] | None,
    identity_updates: dict[str, object] | None,
    message: str,
) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label=f"deep-{message}")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        _apply_link_tamper(
            row,
            row_updates=row_updates,
            snapshot_updates=snapshot_updates,
            identity_updates=identity_updates,
        )
        with session.no_autoflush, pytest.raises(ValidationError, match=message):
            SqlAlchemyObservationPlanningLinkRepository(session).get_provenance_planning_link(
                execution.link_record_id,
                owner_id="owner-a",
            )


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"provenance_record_id": "missing-provenance"}, "input provenance not found"),
        ({"provenance_checksum": _checksum("wrong-provenance")}, "input provenance checksum"),
        ({"eligibility_set_record_id": "missing-set"}, "eligibility-window set not found"),
        ({"eligibility_set_checksum": _checksum("wrong-set")}, "eligibility-window set checksum"),
        ({"selected_window_ids": ("missing-window",)}, "selected eligibility window"),
        ({"planning_request_id": "missing-request"}, "observation-planning request not found"),
        ({"planning_request_checksum": _checksum("wrong-request")}, "planning request checksum"),
        (
            {
                "prepared_request": "tamper-request",
            },
            "planning request snapshot",
        ),
        ({"planning_run_id": "missing-run"}, "observation-planning run not found"),
        (
            {"planning_scientific_identity_checksum": _checksum("wrong-identity")},
            "planning run scientific identity",
        ),
        ({"observation_plan_id": None}, "missing persisted plan reference"),
        ({"observation_plan_id": "wrong-plan"}, "observation plan does not belong"),
    ],
)
def test_link_creation_validates_referenced_graph(
    tmp_path: Path,
    kwargs: dict[str, object],
    message: str,
) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="reference")))
        row = session.get(ObservationPlanningProvenanceLinkRow, execution.link_record_id)
        assert row is not None
        session.delete(row)
        session.commit()

        preparation = execution.preparation
        planning_request_id = execution.planning_request_id
        planning_run_id = execution.planning_run_id
        observation_plan_id = execution.observation_plan_id
        identity_checksum = execution.planning_execution.scientific_identity_checksum
        if "planning_request_id" in kwargs:
            planning_request_id = str(kwargs["planning_request_id"])
            kwargs = {key: value for key, value in kwargs.items() if key != "planning_request_id"}
        if "planning_run_id" in kwargs:
            planning_run_id = str(kwargs["planning_run_id"])
            kwargs = {key: value for key, value in kwargs.items() if key != "planning_run_id"}
        if "observation_plan_id" in kwargs:
            observation_plan_id = kwargs["observation_plan_id"]  # type: ignore[assignment]
            kwargs = {key: value for key, value in kwargs.items() if key != "observation_plan_id"}
        if "planning_scientific_identity_checksum" in kwargs:
            identity_checksum = str(kwargs["planning_scientific_identity_checksum"])
            kwargs = {
                key: value
                for key, value in kwargs.items()
                if key != "planning_scientific_identity_checksum"
            }
        if kwargs:
            preparation = preparation.model_copy(update=kwargs)

        with pytest.raises((NotFoundError, ValidationError), match=message):
            SqlAlchemyObservationPlanningLinkRepository(session).create_provenance_planning_link(
                owner_id="owner-a",
                preparation=preparation,
                planning_request_id=planning_request_id,
                planning_run_id=planning_run_id,
                observation_plan_id=observation_plan_id,
                result=execution.planning_execution.result,
                planning_scientific_identity_checksum=identity_checksum,
            )


def test_returns_typed_models_and_rejects_mutation(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        execution = _execute(session, _persist_set(session, _provenance(label="typed")))

    assert isinstance(execution, ProvenanceAnchoredPlanningExecution)
    assert isinstance(execution.link, StoredProvenancePlanningLink)
    assert not isinstance(execution.link, ObservationPlanningProvenanceLinkRow)
    with pytest.raises(PydanticValidationError):
        execution.link_checksum = "changed"


def test_geometry_derived_execution_source_guard_keeps_production_decoupled() -> None:
    source = Path(execution_module.__file__).read_text(encoding="utf-8")
    assert "orbitmind.observation_geometry" not in source
    assert "geometry_eligibility_adapter" not in source
    assert "derive_eligibility_from_geometry_run" not in source
    assert "compute_observation_geometry" not in source
    assert "orbitmind.api" not in source
    assert "orbitmind.space" not in source
    assert "orbitmind.sources" not in source
    assert "orbitmind.optimization.solvers" not in source
    assert "orbitmind.quantum" not in source
    assert "qiskit" not in source.lower()
    assert "Aer" not in source
    assert SchedulingProblemLimits(max_variables=24).max_variables == 24
