"""Tests for read-only observation study chain integrity summaries."""

from __future__ import annotations

import ast
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session

import orbitmind.observation_geometry.persistence_service as geometry_persistence_service
import orbitmind.observation_planning.geometry_eligibility_adapter as geometry_adapter
import orbitmind.observation_planning.orchestration as orchestration_module
import orbitmind.observation_planning.provenance_execution as provenance_execution
import orbitmind.observation_studies.reports as reports_module
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
    GeometryDerivedEligibilityResult,
    derive_eligibility_from_geometry_run,
)
from orbitmind.observation_planning.models import ObservationPlanningRequest
from orbitmind.observation_planning.provenance_execution import (
    ProvenanceAnchoredPlanningExecution,
    execute_provenance_anchored_planning,
)
from orbitmind.observation_studies import (
    OBSERVATION_STUDY_CHAIN_INTEGRITY_DISCLAIMER,
    OBSERVATION_STUDY_CHAIN_INTEGRITY_LIMITATION,
    OBSERVATION_STUDY_CHAIN_INTEGRITY_STATUS,
    ObservationStudyCheck,
    get_geometry_planning_study_chain,
    summarize_geometry_planning_study_chain,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_geometry_models import ObservationGeometryRunRow
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
    db = Database(f"sqlite:///{(tmp_path / 'observation-study-integrity.db').as_posix()}")
    db.create_all()
    return db


def _registry_elements() -> PinnedOrbitElementSet:
    registry = SourceRegistry()
    source = registry.get_source_record("ISS")
    line1, line2 = registry.get_tle("ISS")
    return PinnedOrbitElementSet(source=source, tle_line1=line1, tle_line2=line2)


def _geometry_request(site_id: str = "SITE-INTEGRITY") -> GeometryComputationRequest:
    return GeometryComputationRequest(
        elements=_registry_elements(),
        site=GroundObservationSite(
            site_id=site_id,
            name=f"{site_id} integrity summary test site",
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
    site_id: str = "SITE-INTEGRITY",
) -> StudyFixture:
    geometry_execution = execute_and_persist_geometry(
        session=session,
        owner_id=owner_id,
        request=_geometry_request(site_id),
        idempotency_key=f"integrity-geometry:{owner_id}:{site_id}",
    )
    derived = derive_eligibility_from_geometry_run(
        session=session,
        owner_id=owner_id,
        geometry_run_id=geometry_execution.run_id,
        requested_by="integrity-analyst",
    )
    execution = execute_provenance_anchored_planning(
        session=session,
        owner_id=owner_id,
        eligibility_set_id=derived.eligibility_set_record_id,
        requested_by="integrity-planner",
    )
    return StudyFixture(
        geometry_run_id=geometry_execution.run_id,
        geometry_request_id=geometry_execution.request_id,
        derived=derived,
        execution=execution,
    )


def _summary(sqlite_db: Database, fixture: StudyFixture, owner_id: str = "owner-a"):
    with sqlite_db.session() as session:
        return summarize_geometry_planning_study_chain(
            session,
            owner_id,
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )


def test_study_chain_integrity_summary_projects_successful_chain(sqlite_db: Database) -> None:
    with sqlite_db.session() as session:
        fixture = _persist_study_chain(session)
        chain = get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=fixture.execution.link_record_id,
        )

    summary = _summary(sqlite_db, fixture)

    assert summary.owner_id == "owner-a"
    assert summary.geometry_run_id == fixture.geometry_run_id
    assert summary.geometry_run_checksum == fixture.derived.geometry_checksum
    assert summary.source_identity_checksum == fixture.derived.source_identity_checksum
    assert summary.eligibility_set_id == fixture.derived.eligibility_set_record_id
    assert summary.eligibility_set_checksum == fixture.derived.eligibility_set_checksum
    assert summary.planning_request_id == fixture.execution.planning_request_id
    assert summary.planning_run_id == fixture.execution.planning_run_id
    assert summary.observation_plan_id == fixture.execution.observation_plan_id
    assert summary.provenance_link_id == fixture.execution.link_record_id
    assert summary.provenance_link_checksum == fixture.execution.link_checksum
    assert summary.status == OBSERVATION_STUDY_CHAIN_INTEGRITY_STATUS
    assert summary.status == "chain-checks-consistent"
    assert summary.overall_passed is True
    assert summary.failed_check_count == 0
    assert summary.check_count == len(chain.checks)
    assert len(summary.checks) == len(chain.checks)
    assert all(check.passed for check in summary.checks)
    assert {check.name for check in summary.checks} == {check.check_id for check in chain.checks}
    assert summary.disclaimer == OBSERVATION_STUDY_CHAIN_INTEGRITY_DISCLAIMER
    assert summary.limitations[-1] == OBSERVATION_STUDY_CHAIN_INTEGRITY_LIMITATION
    assert "checksum and stored-record consistency" in summary.limitations[-1]
    assert "not real-world authenticity" in summary.limitations[-1]
    assert "does not prove live tracking" in summary.disclaimer
    assert "operational access" in summary.disclaimer
    assert "taskability" in summary.disclaimer
    assert "command readiness" in summary.disclaimer
    assert "approval" in summary.disclaimer
    assert "signed receipt status" in summary.disclaimer
    assert "quantum authority" in summary.disclaimer

    with pytest.raises(PydanticValidationError):
        summary.owner_id = "changed"  # type: ignore[misc]


def test_study_chain_integrity_summary_is_fail_closed(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with sqlite_db.session() as session:
        fixture = _persist_study_chain(session, site_id="SITE-INTEGRITY-FAIL")
        second = _persist_study_chain(session, site_id="SITE-INTEGRITY-MISMATCH")

    with pytest.raises(NotFoundError):
        _summary(sqlite_db, fixture, owner_id="owner-b")

    with sqlite_db.session() as session, pytest.raises(ValidationError, match="geometry checksum"):
        summarize_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=fixture.geometry_run_id,
            provenance_link_id=second.execution.link_record_id,
        )

    with sqlite_db.session() as session:
        row = session.get(ObservationGeometryRunRow, fixture.geometry_run_id)
        assert row is not None
        row.geometry_checksum = sha256_text("integrity-tampered-geometry")
        session.commit()

    with pytest.raises(ValidationError, match="checksum"):
        _summary(sqlite_db, fixture)

    with sqlite_db.session() as session:
        clean = _persist_study_chain(session, site_id="SITE-INTEGRITY-CHECK")
        chain = get_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=clean.geometry_run_id,
            provenance_link_id=clean.execution.link_record_id,
        )
        inconsistent = chain.model_copy(
            update={
                "checks": (
                    ObservationStudyCheck(
                        check_id="forced-inconsistent-check",
                        passed=False,
                        message="forced inconsistent read-time check",
                    ),
                )
            }
        )

    def fake_chain(*_args: object, **_kwargs: object):
        return inconsistent

    monkeypatch.setattr(reports_module, "get_geometry_planning_study_chain", fake_chain)
    with sqlite_db.session() as session, pytest.raises(ValidationError, match="inconsistent"):
        summarize_geometry_planning_study_chain(
            session,
            "owner-a",
            geometry_run_id=clean.geometry_run_id,
            provenance_link_id=clean.execution.link_record_id,
        )


def test_study_chain_integrity_summary_does_not_recompute_or_execute(
    sqlite_db: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with sqlite_db.session() as session:
        fixture = _persist_study_chain(session, site_id="SITE-INTEGRITY-READONLY")

    def fail_geometry_compute(*_args: object, **_kwargs: object) -> GeometryComputationResult:
        raise AssertionError("integrity summary must not recompute geometry")

    def fail_eligibility_derivation(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("integrity summary must not derive eligibility")

    def fail_planning_execution(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("integrity summary must not execute anchored planning")

    def fail_planner(_: ObservationPlanningRequest) -> object:
        raise AssertionError("integrity summary must not invoke the planner")

    monkeypatch.setattr(
        geometry_persistence_service,
        "compute_observation_geometry",
        fail_geometry_compute,
    )
    monkeypatch.setattr(
        geometry_adapter,
        "derive_eligibility_from_geometry_run",
        fail_eligibility_derivation,
    )
    monkeypatch.setattr(
        provenance_execution,
        "execute_provenance_anchored_planning",
        fail_planning_execution,
    )
    monkeypatch.setattr(orchestration_module, "plan_observation_request", fail_planner)

    summary = _summary(sqlite_db, fixture)

    assert summary.status == "chain-checks-consistent"
    assert summary.overall_passed is True


def test_study_chain_integrity_summary_does_not_leak_raw_internal_fields(
    sqlite_db: Database,
) -> None:
    with sqlite_db.session() as session:
        fixture = _persist_study_chain(session, site_id="SITE-INTEGRITY-LEAKS")

    serialized = _summary(sqlite_db, fixture).model_dump_json().lower()
    for forbidden in (
        "result_json",
        "request_json",
        "link_json",
        "snapshot",
        "tle_line1",
        "tle_line2",
        '"samples"',
        '"intervals"',
        "select",
        "insert",
        "postgresql://",
        "sqlite",
        "traceback",
        ".py",
        "e:\\",
    ):
        assert forbidden not in serialized


def test_observation_studies_reports_have_no_forbidden_imports() -> None:
    report_path = Path("src/orbitmind/observation_studies/reports.py")
    report_source = report_path.read_text(encoding="utf-8")

    for forbidden in (
        "compute_observation_geometry",
        "execute_and_persist_geometry",
        "derive_eligibility_from_geometry_run",
        "execute_provenance_anchored_planning",
        "plan_observation_request",
        "orbitmind.api",
        "orbitmind.quantum",
        "orbitmind.sources",
        "orbitmind.optimization.solvers",
        "orbitmind.observation_geometry",
        "orbitmind.observation_planning.provenance_execution",
        "orbitmind.observation_planning.orchestration",
    ):
        assert forbidden not in report_source

    tree = ast.parse(report_source)
    forbidden_prefixes = (
        "orbitmind.api",
        "orbitmind.sources",
        "orbitmind.quantum",
        "orbitmind.optimization",
        "orbitmind.observation_geometry",
        "orbitmind.observation_planning.provenance_execution",
        "orbitmind.observation_planning.orchestration",
        "orbitmind.observation_planning.service",
    )
    for node in ast.walk(tree):
        module = _imported_module(node)
        if module is None:
            continue
        assert not module.startswith(forbidden_prefixes), module


def _imported_module(node: ast.AST) -> str | None:
    if isinstance(node, ast.Import):
        return node.names[0].name
    if isinstance(node, ast.ImportFrom):
        return node.module
    return None
