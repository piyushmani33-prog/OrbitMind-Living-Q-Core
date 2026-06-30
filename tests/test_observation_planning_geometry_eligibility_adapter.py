"""Tests for deriving planning eligibility from authenticated geometry runs."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import func, select, update

import orbitmind.persistence.observation_geometry_models
import orbitmind.persistence.observation_planning_models  # noqa: F401 - register metadata
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_geometry.models import (
    ComputedVisibilityInterval,
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.service import compute_observation_geometry
from orbitmind.observation_planning import geometry_eligibility_adapter as adapter
from orbitmind.observation_planning.geometry_eligibility_adapter import (
    GEOMETRY_DERIVED_LIMITATION,
    GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION,
    GeometryDerivedEligibilityResult,
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.provenance import (
    EligibilityDeclarationMode,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.persistence.database import Base, Database
from orbitmind.persistence.observation_geometry_models import (
    ObservationGeometryRunRow,
)
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
    StoredObservationGeometryRequest,
    StoredObservationGeometryRun,
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
)
from orbitmind.sources.registry import SourceRegistry

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC)


@pytest.fixture()
def sqlite_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'geometry-derived-eligibility.db').as_posix()}")
    Base.metadata.create_all(db.engine)
    return db


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _request(
    *,
    site_id: str = "SITE-001",
    minimum_elevation_deg: float = 0.0,
) -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name="Geometry adapter test site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=START,
        end=START + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=minimum_elevation_deg,
    )


def _persist_geometry_run(
    db: Database,
    request: GeometryComputationRequest | None = None,
    *,
    owner_id: str = "owner-a",
) -> tuple[str, str, GeometryComputationRequest, GeometryComputationResult]:
    geometry_request = request or _request()
    result = compute_observation_geometry(geometry_request)
    with db.session() as session:
        repository = SqlAlchemyObservationGeometryRepository(session)
        request_write = repository.create_geometry_request(geometry_request, owner_id=owner_id)
        run_write = repository.persist_geometry_result(
            request_id=request_write.request.id,
            owner_id=owner_id,
            result=result,
        )
        session.commit()
        return request_write.request.id, run_write.run.id, geometry_request, result


def _count(session: object, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)  # type: ignore[attr-defined]


def _planning_counts(db: Database) -> tuple[int, int, int]:
    with db.session() as session:
        return (
            _count(session, ObservationInputProvenanceRow),
            _count(session, ObservationEligibilityWindowSetRow),
            _count(session, ObservationEligibilityWindowRow),
        )


def test_derive_geometry_intervals_to_authenticated_eligibility(sqlite_db: Database) -> None:
    request_id, run_id, geometry_request, result = _persist_geometry_run(sqlite_db)
    assert result.intervals

    with sqlite_db.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
        )

    assert isinstance(derived, GeometryDerivedEligibilityResult)
    assert derived.owner_id == "owner-a"
    assert derived.requested_by == "analyst-a"
    assert derived.geometry_run_id == run_id
    assert derived.geometry_request_id == request_id
    assert derived.geometry_checksum == result.geometry_checksum
    assert derived.geometry_request_checksum == geometry_request.request_checksum
    assert derived.window_count == len(result.intervals)
    assert derived.provenance_created is True
    assert derived.eligibility_set_created is True
    assert derived.derived_source_type == PinnedInputSourceType.DERIVED
    assert derived.derived_verification_status == ScientificInputVerificationStatus.GEOMETRY_DERIVED
    assert GEOMETRY_DERIVED_LIMITATION in derived.limitations

    with sqlite_db.session() as session:
        repository = SqlAlchemyObservationPlanningProvenanceRepository(session)
        stored_provenance = repository.get_provenance(
            derived.provenance_record_id,
            owner_id="owner-a",
        )
        stored_set = repository.get_eligibility_window_set(
            derived.eligibility_set_record_id,
            owner_id="owner-a",
        )

    assert stored_provenance is not None
    assert stored_provenance.provenance.source.source_mode == (
        PinnedInputSourceMode.DERIVED_FROM_GEOMETRY
    )
    assert stored_provenance.provenance.verification_status == (
        ScientificInputVerificationStatus.GEOMETRY_DERIVED
    )
    assert stored_provenance.provenance.parent_provenance_checksums == ()
    assert stored_set is not None
    assert stored_set.window_set.generation_rule_version == (
        GEOMETRY_ELIGIBILITY_DERIVATION_RULE_VERSION
    )
    assert tuple(window.asset_id for window in stored_set.window_set.windows) == (
        geometry_request.elements.source.satellite_id,
    )
    assert tuple(window.target_id for window in stored_set.window_set.windows) == (
        geometry_request.site.site_id,
    )
    assert stored_set.window_set.windows[0].start == result.intervals[0].rise_time
    assert stored_set.window_set.windows[0].end == result.intervals[0].set_time
    assert stored_set.window_set.windows[0].declaration_mode == (
        EligibilityDeclarationMode.DERIVED_FROM_GEOMETRY
    )


def test_zero_interval_geometry_creates_empty_eligibility_set(sqlite_db: Database) -> None:
    _, run_id, _, result = _persist_geometry_run(
        sqlite_db,
        _request(minimum_elevation_deg=80.0),
    )
    assert result.intervals == ()

    with sqlite_db.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
        )

    assert derived.window_count == 0
    with sqlite_db.session() as session:
        stored_set = SqlAlchemyObservationPlanningProvenanceRepository(
            session
        ).get_eligibility_window_set(derived.eligibility_set_record_id, owner_id="owner-a")
    assert stored_set is not None
    assert stored_set.window_set.windows == ()


def test_exact_replay_reuses_existing_provenance_and_eligibility(sqlite_db: Database) -> None:
    _, run_id, _, _ = _persist_geometry_run(sqlite_db)

    with sqlite_db.session() as session:
        first = derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
        )
    with sqlite_db.session() as session:
        replay = derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="different-attribution",
        )
    with sqlite_db.session() as session:
        changed_label = derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
            derivation_label="alternate-filter-context",
        )

    assert replay.provenance_record_id == first.provenance_record_id
    assert replay.eligibility_set_record_id == first.eligibility_set_record_id
    assert replay.provenance_created is False
    assert replay.eligibility_set_created is False
    assert replay.derivation_checksum == first.derivation_checksum
    assert replay.requested_by == "different-attribution"
    assert changed_label.provenance_record_id != first.provenance_record_id
    assert changed_label.eligibility_set_record_id != first.eligibility_set_record_id
    assert changed_label.derivation_checksum != first.derivation_checksum


def test_owner_isolation_and_requested_by_not_authority(sqlite_db: Database) -> None:
    _, run_id, _, _ = _persist_geometry_run(sqlite_db, owner_id="owner-a")

    with sqlite_db.session() as session, pytest.raises(NotFoundError):
        derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-b",
            geometry_run_id=run_id,
            requested_by="owner-a",
        )

    with sqlite_db.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="owner-b",
        )
    assert derived.owner_id == "owner-a"
    assert derived.requested_by == "owner-b"


def test_filter_label_and_window_bounds_are_rejected(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, run_id, request, result = _persist_geometry_run(sqlite_db)

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="derivation_label"):
        derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
            derivation_label=" padded ",
        )
    with sqlite_db.session() as session, pytest.raises(ValidationError, match="minimum_peak"):
        derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
            minimum_peak_elevation_deg=90.0,
        )

    intervals = tuple(
        ComputedVisibilityInterval(
            rise_time=START + dt.timedelta(seconds=index * 2),
            set_time=START + dt.timedelta(seconds=index * 2 + 1),
            peak_time=START + dt.timedelta(seconds=index * 2),
            peak_elevation_deg=1.0,
            rise_azimuth_deg=0.0,
            set_azimuth_deg=1.0,
        )
        for index in range(25)
    )
    expanded_result = GeometryComputationResult(
        request_checksum=result.request_checksum,
        element_checksum=result.element_checksum,
        source_identity_checksum=result.source_identity_checksum,
        samples=result.samples,
        intervals=intervals,
        sample_count=result.sample_count,
        failed_sample_count=result.failed_sample_count,
        limitations=result.limitations,
    )

    class FakeGeometryRepository:
        def __init__(self, _session: object) -> None:
            pass

        def get_geometry_run(
            self, _run_id: str, *, owner_id: str
        ) -> StoredObservationGeometryRun | None:
            return StoredObservationGeometryRun(
                id=run_id,
                request_id="request-id",
                owner_id=owner_id,
                request_checksum=expanded_result.request_checksum,
                geometry_checksum=expanded_result.geometry_checksum,
                result=expanded_result,
            )

        def get_geometry_request(
            self, _request_id: str, *, owner_id: str
        ) -> StoredObservationGeometryRequest | None:
            return StoredObservationGeometryRequest(
                id="request-id",
                owner_id=owner_id,
                request_checksum=request.request_checksum,
                request=request,
                element_checksum=request.elements.element_checksum,
                source_identity_checksum=expanded_result.source_identity_checksum,
                idempotency_key=None,
            )

    monkeypatch.setattr(adapter, "SqlAlchemyObservationGeometryRepository", FakeGeometryRepository)
    with sqlite_db.session() as session, pytest.raises(ValidationError, match="variable bound"):
        derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
        )


def test_tampered_geometry_run_is_rejected(sqlite_db: Database) -> None:
    _, run_id, _, _ = _persist_geometry_run(sqlite_db)
    with sqlite_db.session() as session:
        session.execute(
            update(ObservationGeometryRunRow)
            .where(ObservationGeometryRunRow.id == run_id)
            .values(geometry_checksum="0" * 64)
        )
        session.commit()

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="checksum"):
        derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
        )


def test_rolls_back_when_eligibility_creation_fails(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, run_id, _, _ = _persist_geometry_run(sqlite_db)

    def fail_create_set(self: object, *args: object, **kwargs: object) -> object:
        raise ValidationError("forced eligibility creation failure")

    monkeypatch.setattr(
        SqlAlchemyObservationPlanningProvenanceRepository,
        "create_eligibility_window_set",
        fail_create_set,
    )
    before = _planning_counts(sqlite_db)
    with sqlite_db.session() as session, pytest.raises(ValidationError, match="forced"):
        derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
        )

    assert _planning_counts(sqlite_db) == before
    with sqlite_db.session() as session:
        assert session.scalar(select(func.count()).select_from(ObservationPlanningRequestRow)) == 0
        assert session.scalar(select(func.count()).select_from(ObservationPlanningRunRow)) == 0
        assert session.scalar(select(func.count()).select_from(ObservationPlanRow)) == 0


def test_no_execution_api_provider_or_quantum_imports_and_result_is_frozen(
    sqlite_db: Database,
) -> None:
    _, run_id, _, _ = _persist_geometry_run(sqlite_db)
    with sqlite_db.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id="owner-a",
            geometry_run_id=run_id,
            requested_by="analyst-a",
        )

    with pytest.raises(PydanticValidationError):
        derived.window_count = 99  # type: ignore[misc]

    source = Path("src/orbitmind/observation_planning/geometry_eligibility_adapter.py").read_text(
        encoding="utf-8"
    )
    forbidden = (
        "compute_observation_geometry",
        "execute_observation_planning",
        "execute_provenance_anchored_planning",
        "plan_observation_request",
        "orbitmind.api",
        "orbitmind.sources",
        "orbitmind.quantum",
    )
    for name in forbidden:
        assert name not in source
