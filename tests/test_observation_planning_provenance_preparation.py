"""Tests for read-only eligibility-backed observation-planning preparation."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

import orbitmind.observation_planning.provenance_preparation as preparation_module
import orbitmind.persistence.observation_geometry_models  # noqa: F401 - register metadata
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.service import compute_observation_geometry
from orbitmind.observation_planning.geometry_eligibility_adapter import (
    GEOMETRY_DERIVED_ACCESS_LIMITATION,
    GEOMETRY_DERIVED_LIMITATION,
    GeometryDerivedEligibilityResult,
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.models import planning_request_checksum
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
    validate_request_against_eligibility,
)
from orbitmind.observation_planning.provenance_preparation import (
    PreparedEligibilityPlanningRequest,
    prepare_eligibility_backed_planning_request,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
)
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationEligibilityWindowSetRow,
    ObservationInputProvenanceRow,
    ObservationPlanningRequestRow,
    ObservationPlanningRunRow,
    ObservationPlanRow,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
    StoredEligibilityWindowSet,
)
from orbitmind.sources.registry import SourceRegistry


def _checksum(label: str) -> str:
    return sha256_text(label)


def _db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'planning-preparation.db').as_posix()}")
    db.create_all()
    return db


def _session(tmp_path: Path) -> Session:
    return _db(tmp_path).session()


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _geometry_request(
    *,
    site_id: str = "SITE-PREP",
    minimum_elevation_deg: float = 0.0,
) -> GeometryComputationRequest:
    start = dt.datetime(2019, 12, 9, 19, 50, tzinfo=dt.UTC)
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} geometry-derived preparation site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=start,
        end=start + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=minimum_elevation_deg,
    )


def _derive_geometry_eligibility(
    db: Database,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-PREP",
    minimum_elevation_deg: float = 0.0,
) -> GeometryDerivedEligibilityResult:
    request = _geometry_request(site_id=site_id, minimum_elevation_deg=minimum_elevation_deg)
    result = compute_observation_geometry(request)
    with db.session() as session:
        geometry_repo = SqlAlchemyObservationGeometryRepository(session)
        stored_request = geometry_repo.create_geometry_request(request, owner_id=owner_id)
        stored_run = geometry_repo.persist_geometry_result(
            request_id=stored_request.request.id,
            owner_id=owner_id,
            result=result,
        )
        session.commit()
        run_id = stored_run.run.id
    with db.session() as session:
        return derive_eligibility_from_geometry_run(
            session=session,
            owner_id=owner_id,
            geometry_run_id=run_id,
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


def _fixture_provenance(
    label: str = "fixture",
    *,
    retrieved_at: dt.datetime | None = None,
) -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=PinnedInputSourceType.FIXTURE,
            source_mode=PinnedInputSourceMode.FIXTURE_BACKED,
            publisher="OrbitMind",
            dataset_name="fixture-observation-eligibility",
            dataset_version="v1",
            dataset_revision="rev-a",
        ),
        artifact=_artifact(label),
        retrieved_at=retrieved_at or dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.VERIFIED),
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _declared_provenance(label: str = "declared") -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=PinnedInputSourceType.USER_DECLARED,
            source_mode=PinnedInputSourceMode.USER_DECLARED,
        ),
        artifact=_artifact(label),
        declared_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.DECLARED),
        verification_status=ScientificInputVerificationStatus.USER_DECLARED,
    )


def _derived_provenance(parent: PinnedInputProvenance) -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id="derived-source",
            source_type=PinnedInputSourceType.DERIVED,
            source_mode=PinnedInputSourceMode.DERIVED_FROM_DECLARED_INPUT,
            dataset_name="derived-eligibility",
            dataset_version="v1",
        ),
        artifact=_artifact("derived"),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 5, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.DECLARED),
        verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
        parent_provenance_checksums=(parent.checksum,),
    )


def _window(
    window_id: str,
    provenance: PinnedInputProvenance,
    *,
    start_minute: int = 0,
    end_minute: int = 30,
    asset_id: str = "SAT-A",
    target_id: str = "T1",
    start: dt.datetime | None = None,
    end: dt.datetime | None = None,
) -> EligibilityWindow:
    base = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC)
    declaration_mode = (
        EligibilityDeclarationMode.FIXTURE_BACKED
        if provenance.source.source_type == PinnedInputSourceType.FIXTURE
        else EligibilityDeclarationMode.USER_DECLARED
        if provenance.source.source_type == PinnedInputSourceType.USER_DECLARED
        else EligibilityDeclarationMode.DERIVED_FROM_DECLARED_INPUT
    )
    verification_status = (
        ScientificInputVerificationStatus.FIXTURE_VERIFIED
        if declaration_mode == EligibilityDeclarationMode.FIXTURE_BACKED
        else ScientificInputVerificationStatus.USER_DECLARED
        if declaration_mode == EligibilityDeclarationMode.USER_DECLARED
        else ScientificInputVerificationStatus.DERIVED_FROM_DECLARED
    )
    return EligibilityWindow(
        id=window_id,
        asset_id=asset_id,
        target_id=target_id,
        start=start or base + dt.timedelta(minutes=start_minute),
        end=end or base + dt.timedelta(minutes=end_minute),
        source_provenance_checksum=provenance.checksum,
        declaration_mode=declaration_mode,
        eligibility_reason="declared-candidate",
        verification_status=verification_status,
    )


def _window_set(
    provenance: PinnedInputProvenance,
    windows: tuple[EligibilityWindow, ...] | None = None,
) -> EligibilityWindowSet:
    return EligibilityWindowSet(
        source_provenance=provenance,
        windows=windows
        if windows is not None
        else (
            _window("W1", provenance),
            _window("W2", provenance, start_minute=40, end_minute=70, asset_id="SAT-B"),
        ),
    )


def _repo(session: Session) -> SqlAlchemyObservationPlanningProvenanceRepository:
    return SqlAlchemyObservationPlanningProvenanceRepository(session)


def _persist_set(
    session: Session,
    provenance: PinnedInputProvenance,
    *,
    owner_id: str = "owner-a",
    windows: tuple[EligibilityWindow, ...] | None = None,
) -> StoredEligibilityWindowSet:
    repo = _repo(session)
    repo.create_provenance(provenance, owner_id=owner_id)
    return repo.create_eligibility_window_set(_window_set(provenance, windows), owner_id=owner_id)


def _prepare(
    session: Session,
    stored_set: StoredEligibilityWindowSet,
    *,
    owner_id: str = "owner-a",
    requested_by: str = "analyst-a",
    selected_window_ids: tuple[str, ...] | None = None,
) -> PreparedEligibilityPlanningRequest:
    return prepare_eligibility_backed_planning_request(
        session=session,
        owner_id=owner_id,
        eligibility_set_id=stored_set.id,
        requested_by=requested_by,
        selected_window_ids=selected_window_ids,
    )


def _count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _planning_counts(session: Session) -> tuple[int, int, int]:
    return (
        _count(session, ObservationPlanningRequestRow),
        _count(session, ObservationPlanningRunRow),
        _count(session, ObservationPlanRow),
    )


def test_prepare_fixture_backed_eligibility(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance)
        prepared = _prepare(session, stored_set)

    assert prepared.provenance_checksum == provenance.checksum
    assert prepared.eligibility_set_checksum == stored_set.eligibility_set_checksum
    assert prepared.eligibility_source_type == PinnedInputSourceType.FIXTURE
    assert prepared.eligibility_verification_status == (
        ScientificInputVerificationStatus.FIXTURE_VERIFIED
    )
    assert prepared.selected_window_ids == ("W1", "W2")
    assert len(prepared.prepared_request.opportunities) == 2
    assert "geometry-derived eligibility windows" in prepared.limitations[-1]
    assert "no live tracking" in prepared.limitations[-1]


def test_prepare_user_declared_and_derived_eligibility(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        declared = _declared_provenance()
        declared_set = _persist_set(session, declared)
        declared_prepared = _prepare(session, declared_set, requested_by="declaring-user")

        parent = _declared_provenance("parent")
        derived = _derived_provenance(parent)
        repo = _repo(session)
        repo.create_provenance(parent, owner_id="owner-a")
        derived_set = _persist_set(session, derived)
        derived_prepared = _prepare(session, derived_set)

    assert declared_prepared.eligibility_source_type == PinnedInputSourceType.USER_DECLARED
    assert declared_prepared.prepared_request.requested_by == "declaring-user"
    assert derived_prepared.eligibility_source_type == PinnedInputSourceType.DERIVED
    assert derived_prepared.eligibility_verification_status == (
        ScientificInputVerificationStatus.DERIVED_FROM_DECLARED
    )


def test_prepare_geometry_derived_eligibility_preserves_status_and_honesty(
    tmp_path: Path,
) -> None:
    db = _db(tmp_path)
    derived = _derive_geometry_eligibility(db)

    with db.session() as session:
        stored_set = _repo(session).get_eligibility_window_set(
            derived.eligibility_set_record_id,
            owner_id="owner-a",
        )
        assert stored_set is not None
        prepared = prepare_eligibility_backed_planning_request(
            session=session,
            owner_id="owner-a",
            requested_by="planning-analyst",
            eligibility_set_id=stored_set.id,
        )

    assert prepared.eligibility_source_type == PinnedInputSourceType.DERIVED
    assert prepared.eligibility_verification_status == (
        ScientificInputVerificationStatus.GEOMETRY_DERIVED
    )
    assert prepared.selected_window_ids == tuple(
        window.id for window in stored_set.window_set.windows
    )
    assert GEOMETRY_DERIVED_LIMITATION in prepared.limitations
    assert GEOMETRY_DERIVED_ACCESS_LIMITATION in prepared.limitations
    assert any("geometry-derived eligibility windows" in item for item in prepared.limitations)
    assert prepared.prepared_request.source_mode.value == "declared"
    assert len(prepared.prepared_request.opportunities) == derived.window_count

    joined = " ".join(prepared.limitations).lower()
    for required_denial in (
        "no live tracking",
        "operational access",
        "taskability",
        "command readiness",
        "approval",
        "signed receipt",
        "quantum authority",
    ):
        assert required_denial in joined
    for forbidden_claim in (
        "operationally verified",
        "access confirmed",
        "verified visibility",
        "taskable",
        "command approved",
        "live validated",
        "quantum-authoritative",
    ):
        assert forbidden_claim not in joined


def test_zero_window_geometry_derived_eligibility_is_not_prepared(tmp_path: Path) -> None:
    db = _db(tmp_path)
    derived = _derive_geometry_eligibility(
        db,
        site_id="SITE-NO-WINDOWS",
        minimum_elevation_deg=80.0,
    )
    assert derived.window_count == 0

    with db.session() as session:
        with pytest.raises(ValidationError, match="contains no windows"):
            prepare_eligibility_backed_planning_request(
                session=session,
                owner_id="owner-a",
                requested_by="planning-analyst",
                eligibility_set_id=derived.eligibility_set_record_id,
            )
        assert _planning_counts(session) == (0, 0, 0)


def test_geometry_derived_preparation_preserves_owner_isolation(tmp_path: Path) -> None:
    db = _db(tmp_path)
    derived = _derive_geometry_eligibility(db)

    with db.session() as session, pytest.raises(NotFoundError):
        prepare_eligibility_backed_planning_request(
            session=session,
            owner_id="owner-b",
            requested_by="owner-a",
            eligibility_set_id=derived.eligibility_set_record_id,
        )


def test_geometry_derived_tamper_is_detected_during_preparation(tmp_path: Path) -> None:
    db = _db(tmp_path)
    provenance_tamper = _derive_geometry_eligibility(db, site_id="SITE-PROV-TAMPER")
    with db.session() as session:
        source_row = session.get(
            ObservationInputProvenanceRow,
            provenance_tamper.provenance_record_id,
        )
        assert source_row is not None
        source_row.artifact_checksum = _checksum("tampered-geometry-provenance")
        session.commit()

    with db.session() as session, pytest.raises(ValidationError, match="artifact checksum"):
        prepare_eligibility_backed_planning_request(
            session=session,
            owner_id="owner-a",
            requested_by="planning-analyst",
            eligibility_set_id=provenance_tamper.eligibility_set_record_id,
        )

    set_tamper = _derive_geometry_eligibility(db, site_id="SITE-SET-TAMPER")
    with db.session() as session:
        set_row = session.get(
            ObservationEligibilityWindowSetRow,
            set_tamper.eligibility_set_record_id,
        )
        assert set_row is not None
        snapshot = dict(set_row.eligibility_set_json)
        snapshot["limitations"] = ["tampered geometry-derived limitation"]
        set_row.eligibility_set_json = snapshot
        session.commit()

    with (
        db.session() as session,
        pytest.raises(
            ValidationError,
            match=r"limitation|checksum|snapshot",
        ),
    ):
        prepare_eligibility_backed_planning_request(
            session=session,
            owner_id="owner-a",
            requested_by="planning-analyst",
            eligibility_set_id=set_tamper.eligibility_set_record_id,
        )


def test_selection_policy_uses_all_by_default_and_canonical_subset_order(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    sat_a_later = _window("W-A-LATE", provenance, asset_id="SAT-A", start_minute=60, end_minute=90)
    sat_b_earlier = _window(
        "W-B-EARLY", provenance, asset_id="SAT-B", start_minute=0, end_minute=30
    )
    sat_c_middle = _window("W-C-MID", provenance, asset_id="SAT-C", start_minute=40, end_minute=70)
    with _session(tmp_path) as session:
        stored_set = _persist_set(
            session,
            provenance,
            windows=(sat_b_earlier, sat_c_middle, sat_a_later),
        )
        all_windows = _prepare(session, stored_set)
        subset = _prepare(
            session,
            stored_set,
            selected_window_ids=("W-C-MID", "W-A-LATE"),
        )
        reversed_subset = _prepare(
            session,
            stored_set,
            selected_window_ids=("W-A-LATE", "W-C-MID"),
        )

    assert all_windows.selected_window_ids == ("W-A-LATE", "W-B-EARLY", "W-C-MID")
    assert subset.selected_window_ids == ("W-A-LATE", "W-C-MID")
    assert tuple(opp.id for opp in subset.prepared_request.opportunities) == (
        "eligibility-W-A-LATE",
        "eligibility-W-C-MID",
    )
    assert subset.planning_request_checksum == reversed_subset.planning_request_checksum
    assert subset.preparation_checksum == reversed_subset.preparation_checksum


@pytest.mark.parametrize(
    ("selected_ids", "message"),
    [
        ((), "cannot be empty"),
        (("W1", "W1"), "must be unique"),
        (("W-MISSING",), "not found"),
        ((" W1",), "unpadded"),
    ],
)
def test_invalid_selection_rejected(
    tmp_path: Path,
    selected_ids: tuple[str, ...],
    message: str,
) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance)
        with pytest.raises(ValidationError, match=message):
            _prepare(session, stored_set, selected_window_ids=selected_ids)


def test_empty_eligibility_set_is_not_fabricated(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance, windows=())
        with pytest.raises(ValidationError, match="contains no windows"):
            _prepare(session, stored_set)
        assert _planning_counts(session) == (0, 0, 0)


def test_deterministic_identity_and_utc_equivalence(tmp_path: Path) -> None:
    utc_time = dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC)
    shifted_time = dt.datetime(
        2026,
        6,
        21,
        14,
        30,
        tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)),
    )
    provenance_a = _fixture_provenance("utc-equivalent", retrieved_at=utc_time)
    provenance_b = _fixture_provenance("utc-equivalent", retrieved_at=shifted_time)
    assert provenance_a.checksum == provenance_b.checksum
    with _session(tmp_path) as session:
        stored_a = _persist_set(session, provenance_a, owner_id="owner-a")
        stored_b = _persist_set(session, provenance_b, owner_id="owner-b")
        first = _prepare(session, stored_a, owner_id="owner-a", requested_by="same-user")
        second = _prepare(session, stored_a, owner_id="owner-a", requested_by="same-user")
        other_owner = _prepare(session, stored_b, owner_id="owner-b", requested_by="same-user")

    assert first.planning_request_checksum == planning_request_checksum(first.prepared_request)
    assert first.planning_request_checksum == second.planning_request_checksum
    assert first.preparation_checksum == second.preparation_checksum
    assert first.preparation_checksum == other_owner.preparation_checksum
    assert first.provenance_record_id != other_owner.provenance_record_id


def test_changed_provenance_or_window_set_changes_preparation_checksum(tmp_path: Path) -> None:
    provenance = _fixture_provenance("change-a")
    changed_provenance = _fixture_provenance("change-b")
    with _session(tmp_path) as session:
        original = _prepare(session, _persist_set(session, provenance))
        changed_source = _prepare(session, _persist_set(session, changed_provenance))
        changed_window = _prepare(
            session,
            _persist_set(
                session,
                _fixture_provenance("change-c"),
                windows=(_window("W1", _fixture_provenance("change-c"), start_minute=5),),
            ),
        )

    assert original.preparation_checksum != changed_source.preparation_checksum
    assert original.preparation_checksum != changed_window.preparation_checksum


def test_owner_isolation_and_requested_by_is_provenance_only(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance, owner_id="owner-a")

        with pytest.raises(NotFoundError):
            _prepare(
                session,
                stored_set,
                owner_id="owner-b",
                requested_by="owner-a",
            )

        prepared = _prepare(
            session,
            stored_set,
            owner_id="owner-a",
            requested_by="not-the-owner",
        )

    assert prepared.prepared_request.requested_by == "not-the-owner"


def test_prepared_request_validates_and_preserves_scientific_identity(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    window = _window(
        "W-IDENTITY",
        provenance,
        asset_id="SAT-Z",
        target_id="TARGET-Z",
        start_minute=15,
        end_minute=45,
    )
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance, windows=(window,))
        prepared = _prepare(session, stored_set)

    validate_request_against_eligibility(prepared.prepared_request, stored_set.window_set)
    opportunity = prepared.prepared_request.opportunities[0]
    assert opportunity.satellite_id == window.asset_id
    assert opportunity.target_id == window.target_id
    assert opportunity.window.start == window.start
    assert opportunity.window.end == window.end
    assert opportunity.mission_value == 1.0
    assert "no computed access geometry" in opportunity.provenance


def test_maximum_window_bound_is_preserved_without_truncation(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    windows = tuple(
        _window(
            f"W-{index:02d}",
            provenance,
            asset_id=f"SAT-{index:02d}",
            target_id=f"T-{index:02d}",
            start_minute=index * 5,
            end_minute=index * 5 + 3,
        )
        for index in range(24)
    )
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance, windows=windows)
        prepared = _prepare(session, stored_set)

    assert len(prepared.selected_window_ids) == 24
    assert len(prepared.prepared_request.opportunities) == 24
    assert (
        tuple(
            opp.id.removeprefix("eligibility-") for opp in prepared.prepared_request.opportunities
        )
        == prepared.selected_window_ids
    )


def test_persistence_tamper_is_detected_during_preparation(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance)
        source_row = session.scalar(select(ObservationInputProvenanceRow))
        assert source_row is not None
        source_row.artifact_checksum = _checksum("wrong")
        with pytest.raises(ValidationError, match="artifact checksum"):
            _prepare(session, stored_set)
        session.rollback()

        stored_set = _repo(session).get_eligibility_window_set(stored_set.id, owner_id="owner-a")
        assert stored_set is not None
        set_row = session.get(ObservationEligibilityWindowSetRow, stored_set.id)
        assert set_row is not None
        set_row.eligibility_set_checksum = _checksum("wrong-set")
        with pytest.raises(ValidationError, match="checksum"):
            _prepare(session, stored_set)
        session.rollback()

        stored_set = _repo(session).get_eligibility_window_set(stored_set.id, owner_id="owner-a")
        assert stored_set is not None
        window_row = session.scalar(select(ObservationEligibilityWindowRow))
        assert window_row is not None
        window_row.asset_id = "SAT-TAMPER"
        with pytest.raises(ValidationError, match="asset"):
            _prepare(session, stored_set)


def test_missing_window_and_unsupported_schema_are_detected(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance)
        window_row = session.scalar(select(ObservationEligibilityWindowRow))
        assert window_row is not None
        session.execute(
            delete(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.id == window_row.id
            )
        )
        session.flush()
        with pytest.raises(ValidationError, match="window count"):
            _prepare(session, stored_set)
        session.rollback()

        set_row = session.get(ObservationEligibilityWindowSetRow, stored_set.id)
        assert set_row is not None
        snapshot = dict(set_row.eligibility_set_json)
        snapshot["schema_version"] = "2"
        session.execute(
            update(ObservationEligibilityWindowSetRow)
            .where(ObservationEligibilityWindowSetRow.id == stored_set.id)
            .values(eligibility_set_json=snapshot)
        )
        session.flush()
        with pytest.raises(ValidationError, match="malformed eligibility-window set"):
            _prepare(session, stored_set)


def test_preparation_is_read_only_and_returns_no_orm_rows(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance)
        before = _planning_counts(session)
        prepared = _prepare(session, stored_set)
        after = _planning_counts(session)
        session.execute(select(ObservationInputProvenanceRow)).first()

    assert before == (0, 0, 0)
    assert after == before
    assert isinstance(prepared, PreparedEligibilityPlanningRequest)
    assert not isinstance(prepared, ObservationInputProvenanceRow)
    assert not isinstance(prepared, ObservationEligibilityWindowSetRow)


def test_no_solver_provider_geometry_or_quantum_path_is_invoked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("planner should not be called during preparation")

    monkeypatch.setattr(
        "orbitmind.observation_planning.service.plan_observation_request",
        fail_if_called,
    )
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        stored_set = _persist_set(session, provenance)
        _prepare(session, stored_set)

    source = Path(preparation_module.__file__).read_text(encoding="utf-8")
    assert "plan_observation_request" not in source
    assert "execute_observation_planning" not in source
    assert "execute_provenance_anchored_planning" not in source
    assert "derive_eligibility_from_geometry_run" not in source
    assert "compute_observation_geometry" not in source
    assert "orbitmind.space" not in source
    assert "orbitmind.sources" not in source
    assert "orbitmind.api" not in source
    assert "orbitmind.optimization.solvers" not in source
    assert "orbitmind.quantum" not in source


def test_frozen_preparation_result_rejects_mutation(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        prepared = _prepare(session, _persist_set(session, provenance))

    with pytest.raises(PydanticValidationError):
        prepared.selected_window_ids = ("changed",)
