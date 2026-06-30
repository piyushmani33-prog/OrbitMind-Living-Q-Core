"""Live PostgreSQL tests for read-only observation study chain queries."""

from __future__ import annotations

import datetime as dt
import os

import pytest
from sqlalchemy import select, text

from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.persistence_service import execute_and_persist_geometry
from orbitmind.observation_planning.geometry_eligibility_adapter import (
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
from orbitmind.observation_studies import get_geometry_planning_study_chain
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_geometry_models import ObservationGeometryRunRow
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationInputProvenanceRow,
)
from orbitmind.sources.registry import SourceRegistry

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

UTC = dt.UTC
START = dt.datetime(2019, 12, 9, 19, 50, tzinfo=UTC)
_TABLES = (
    "observation_geometry_runs",
    "observation_geometry_requests",
    "observation_planning_provenance_links",
    "observation_eligibility_windows",
    "observation_eligibility_window_sets",
    "observation_input_provenance_parents",
    "observation_input_provenance",
    "observation_plans",
    "observation_planning_runs",
    "observation_planning_requests",
)


@pytest.fixture()
def pg_db() -> Database:
    assert _PG_URL is not None
    db = Database(_PG_URL)
    assert db.is_postgres
    with db.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield db
    db.engine.dispose()


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _geometry_request(site_id: str) -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} postgres observation study site",
            position=GeodeticPosition(latitude_deg=0.0, longitude_deg=0.0, altitude_km=0.0),
        ),
        start=START,
        end=START + dt.timedelta(minutes=25),
        step_seconds=300,
        minimum_elevation_deg=0.0,
    )


def _persist_chain(
    db: Database,
    *,
    owner_id: str = "owner-a",
    site_id: str = "SITE-PG-STUDY",
) -> tuple[str, ProvenanceAnchoredPlanningExecution]:
    with db.session() as session:
        geometry_execution = execute_and_persist_geometry(
            session=session,
            owner_id=owner_id,
            request=_geometry_request(site_id),
            idempotency_key=f"pg-study-geometry:{owner_id}:{site_id}",
        )
    with db.session() as session:
        derived = derive_eligibility_from_geometry_run(
            session=session,
            owner_id=owner_id,
            geometry_run_id=geometry_execution.run_id,
            requested_by="pg-study-analyst",
        )
    with db.session() as session:
        execution = execute_provenance_anchored_planning(
            session=session,
            owner_id=owner_id,
            eligibility_set_id=derived.eligibility_set_record_id,
            requested_by="pg-study-planner",
        )
    return geometry_execution.run_id, execution


def test_postgres_observation_study_chain_success_owner_and_mismatch(
    pg_db: Database,
) -> None:
    run_id, execution = _persist_chain(pg_db, site_id="SITE-PG-STUDY-A")
    other_run_id, _ = _persist_chain(pg_db, site_id="SITE-PG-STUDY-B")

    with pg_db.session() as session:
        chain = get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=run_id,
            provenance_link_id=execution.link_record_id,
        )
    assert chain.geometry.run_id == run_id
    assert chain.eligibility.source_type == PinnedInputSourceType.DERIVED
    assert chain.eligibility.source_mode == PinnedInputSourceMode.DERIVED_FROM_GEOMETRY
    assert (
        chain.eligibility.verification_status == ScientificInputVerificationStatus.GEOMETRY_DERIVED
    )
    assert chain.planning.planning_request_source_mode == ObservationPlanningSourceMode.DECLARED
    assert chain.planning.link_record_id == execution.link_record_id

    with pg_db.session() as session, pytest.raises(NotFoundError):
        get_geometry_planning_study_chain(
            session,
            "owner-b",
            geometry_run_id=run_id,
            provenance_link_id=execution.link_record_id,
        )
    with pg_db.session() as session, pytest.raises(ValidationError, match="geometry checksum"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=other_run_id,
            provenance_link_id=execution.link_record_id,
        )


def test_postgres_observation_study_chain_tamper_detection(pg_db: Database) -> None:
    geometry_run_id, execution = _persist_chain(pg_db, site_id="SITE-PG-TAMPER-GEOM")
    with pg_db.session() as session:
        row = session.get(ObservationGeometryRunRow, geometry_run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("pg-study-tampered-geometry")
        session.commit()
    with pg_db.session() as session, pytest.raises(ValidationError, match="checksum"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=geometry_run_id,
            provenance_link_id=execution.link_record_id,
        )

    geometry_run_id, execution = _persist_chain(pg_db, site_id="SITE-PG-TAMPER-PROV")
    with pg_db.session() as session:
        provenance_row = session.get(ObservationInputProvenanceRow, execution.provenance_record_id)
        assert provenance_row is not None
        provenance_row.verification_status = ScientificInputVerificationStatus.UNKNOWN.value
        session.commit()
    with pg_db.session() as session, pytest.raises(ValidationError, match="verification"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=geometry_run_id,
            provenance_link_id=execution.link_record_id,
        )

    geometry_run_id, execution = _persist_chain(pg_db, site_id="SITE-PG-TAMPER-WINDOW")
    with pg_db.session() as session:
        window_row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id == execution.eligibility_set_record_id
            )
        )
        assert window_row is not None
        window_row.target_id = "TARGET-TAMPERED"
        session.commit()
    with pg_db.session() as session, pytest.raises(ValidationError, match="target"):
        get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=geometry_run_id,
            provenance_link_id=execution.link_record_id,
        )
