"""Tests for Phase 4D observation study chain read models."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

import orbitmind.observation_geometry.persistence_service as geometry_persistence_service
import orbitmind.observation_planning.orchestration as orchestration_module
import orbitmind.persistence.observation_geometry_models
import orbitmind.persistence.observation_planning_models  # noqa: F401 - register metadata
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_planning.geometry_eligibility_adapter import (
    GEOMETRY_DERIVED_ACCESS_LIMITATION,
    GEOMETRY_DERIVED_LIMITATION,
    GeometryDerivedEligibilityResult,
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.models import ObservationPlanningSourceMode
from orbitmind.observation_planning.provenance import (
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.observation_planning.provenance_execution import (
    ProvenanceAnchoredPlanningExecution,
    execute_provenance_anchored_planning,
)
from orbitmind.observation_studies import (
    OBSERVATION_STUDY_LIMITATION,
    ObservationStudyChain,
    get_geometry_planning_study_chain,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_geometry_models import ObservationGeometryRunRow
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationInputProvenanceRow,
    ObservationPlanningProvenanceLinkRow,
)
from orbitmind.sources.registry import SourceRegistry

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC)


@dataclass(frozen=True)
class StudyFixture:
    geometry_run_id: str
    geometry_request_id: str
    derived: GeometryDerivedEligibilityResult
    execution: ProvenanceAnchoredPlanningExecution


@pytest.fixture()
def sqlite_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'observation-study.db').as_posix()}")
    db.create_all()
    return db


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _geometry_request(site_id: str = "SITE-STUDY") -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} observation study test site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=START,
        end=START + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _persist_study_chain(
    session: Session,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-STUDY",
) -> StudyFixture:
    geometry_execution = execute_and_persist_geometry(
        session=session,
        owner_id=owner_id,
        request=_geometry_request(site_id),
        idempotency_key=f"study-geometry:{owner_id}:{site_id}",
    )
    derived = derive_eligibility_from_geometry_run(
        session=session,
        owner_id=owner_id,
        geometry_run_id=geometry_execution.run_id,
        requested_by="study-analyst",
    )
    execution = execute_provenance_anchored_planning(
        session=session,
        owner_id=owner_id,
        eligibility_set_id=derived.eligibility_set_record_id,
        requested_by="study-planner",
    )
    return StudyFixture(
        geometry_run_id=geometry_execution.run_id,
        geometry_request_id=geometry_execution.request_id,
        derived=derived,
        execution=execution,
    )


def test_geometry_planning_study_chain_authenticates_end_to_end(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with sqlite_db.session() as session:
        fixture = _persist_study_chain(session)

    def fail_geometry_compute(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise AssertionError("study query must not recompute geometry")

    def fail_planner(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("study query must not execute planning")

    monkeypatch.setattr(
        geometry_persistence_service, "compute_observation_geometry", fail_geometry_compute
    )
    monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)

    with sqlite_db.session() as session:
        chain = get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )

    assert isinstance(chain, ObservationStudyChain)
    assert chain.owner_id == "owner-a"
    assert chain.geometry.run_id == fixture.geometry_run_id
    assert chain.geometry.request_id == fixture.geometry_request_id
    assert chain.geometry.geometry_checksum == fixture.derived.geometry_checksum
    assert chain.geometry.request_checksum == fixture.derived.geometry_request_checksum
    assert chain.geometry.element_checksum == fixture.derived.element_checksum
    assert chain.geometry.source_identity_checksum == fixture.derived.source_identity_checksum
    assert chain.geometry.satellite_id == "ISS"
    assert chain.geometry.site_id == "SITE-STUDY"
    assert chain.eligibility.provenance_record_id == fixture.derived.provenance_record_id
    assert chain.eligibility.provenance_checksum == fixture.derived.provenance_checksum
    assert chain.eligibility.eligibility_set_record_id == fixture.derived.eligibility_set_record_id
    assert chain.eligibility.eligibility_set_checksum == fixture.derived.eligibility_set_checksum
    assert chain.eligibility.source_type == PinnedInputSourceType.DERIVED
    assert chain.eligibility.source_mode == PinnedInputSourceMode.DERIVED_FROM_GEOMETRY
    assert (
        chain.eligibility.verification_status == ScientificInputVerificationStatus.GEOMETRY_DERIVED
    )
    assert chain.eligibility.selected_window_ids == fixture.execution.selected_window_ids
    assert chain.eligibility.window_count == fixture.derived.window_count
    assert chain.planning.preparation_checksum == fixture.execution.preparation_checksum
    assert chain.planning.planning_request_id == fixture.execution.planning_request_id
    assert chain.planning.planning_request_checksum == fixture.execution.planning_request_checksum
    assert chain.planning.planning_request_source_mode == ObservationPlanningSourceMode.DECLARED
    assert chain.planning.planning_run_id == fixture.execution.planning_run_id
    assert chain.planning.observation_plan_id == fixture.execution.observation_plan_id
    assert chain.planning.link_record_id == fixture.execution.link_record_id
    assert chain.planning.link_checksum == fixture.execution.link_checksum
    assert GEOMETRY_DERIVED_LIMITATION in chain.limitations
    assert GEOMETRY_DERIVED_ACCESS_LIMITATION in chain.limitations
    assert OBSERVATION_STUDY_LIMITATION in chain.limitations
    assert {check.check_id for check in chain.checks} == {
        "geometry-provenance-checksum",
        "geometry-source-identity",
        "eligibility-window-geometry",
        "planning-link-authenticated",
    }
    assert all(check.passed for check in chain.checks)
    dumped = chain.model_dump_json()
    for forbidden in ("result_json", "request_json", "link_json", "tle_line1", "tle_line2"):
        assert forbidden not in dumped
    with pytest.raises(PydanticValidationError):
        chain.owner_id = "changed"  # type: ignore[misc]


def test_study_chain_rejects_mismatched_geometry_and_link(sqlite_db: Database) -> None:
    with sqlite_db.session() as session:
        first = _persist_study_chain(session, site_id="SITE-STUDY-A")
        second = _persist_study_chain(session, site_id="SITE-STUDY-B")

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="geometry checksum"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=first.geometry_run_id,
            provenance_link_id=second.execution.link_record_id,
        )


def test_study_chain_blocks_cross_owner_access(sqlite_db: Database) -> None:
    with sqlite_db.session() as session:
        fixture = _persist_study_chain(session, owner_id="owner-a")

    with sqlite_db.session() as session, pytest.raises(NotFoundError):
        get_geometry_planning_study_chain(
            session,
            "owner-b",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )


def test_study_chain_rejects_geometry_tamper(sqlite_db: Database) -> None:
    with sqlite_db.session() as session:
        fixture = _persist_study_chain(session)
        row = session.get(ObservationGeometryRunRow, fixture.geometry_run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("tampered-geometry-row")
        session.commit()

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="checksum"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )


def test_study_chain_rejects_provenance_eligibility_and_link_tamper(
    sqlite_db: Database,
) -> None:
    with sqlite_db.session() as session:
        provenance_fixture = _persist_study_chain(session, site_id="SITE-TAMPER-PROV")
        provenance_row = session.get(
            ObservationInputProvenanceRow,
            provenance_fixture.derived.provenance_record_id,
        )
        assert provenance_row is not None
        provenance_row.verification_status = ScientificInputVerificationStatus.UNKNOWN.value
        session.commit()

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="verification"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=provenance_fixture.geometry_run_id,
            provenance_link_id=provenance_fixture.execution.link_record_id,
        )

    with sqlite_db.session() as session:
        eligibility_fixture = _persist_study_chain(session, site_id="SITE-TAMPER-WINDOW")
        window_row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id
                == eligibility_fixture.derived.eligibility_set_record_id
            )
        )
        assert window_row is not None
        window_row.asset_id = "SAT-TAMPERED"
        session.commit()

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="asset"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=eligibility_fixture.geometry_run_id,
            provenance_link_id=eligibility_fixture.execution.link_record_id,
        )

    with sqlite_db.session() as session:
        link_fixture = _persist_study_chain(session, site_id="SITE-TAMPER-LINK")
        link_row = session.get(
            ObservationPlanningProvenanceLinkRow,
            link_fixture.execution.link_record_id,
        )
        assert link_row is not None
        link_row.selected_window_ids_json = ["missing-window"]
        session.commit()

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="selected"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=link_fixture.geometry_run_id,
            provenance_link_id=link_fixture.execution.link_record_id,
        )


def test_observation_study_query_layer_stays_read_only_and_decoupled() -> None:
    query_source = Path("src/orbitmind/observation_studies/queries.py").read_text(encoding="utf-8")
    for forbidden in (
        "compute_observation_geometry",
        "execute_and_persist_geometry",
        "derive_eligibility_from_geometry_run",
        "execute_provenance_anchored_planning",
        "plan_observation_request",
        "orbitmind.api",
        "orbitmind.quantum",
        "orbitmind.sources.celestrak",
        "orbitmind.observation_geometry.service",
        "orbitmind.observation_planning.service",
    ):
        assert forbidden not in query_source
