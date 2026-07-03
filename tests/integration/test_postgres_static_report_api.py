"""Live PostgreSQL API tests for the mission static report route.

Skips unless ORBITMIND_TEST_POSTGRES_URL points at a disposable migrated database.
The test seeds through the repository on the migrated schema and never calls
create_all().
"""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from orbitmind.api.app import create_app
from orbitmind.api.container import AppContainer
from orbitmind.core.config import Settings
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.mission.models import Mission, MissionRequest, MissionStatus, OutputType
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.verification.models import FindingStatus, Severity, VerificationFinding
from orbitmind.visualization.models import ArtifactRecord

_PG_URL = os.environ.get("ORBITMIND_TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.skipif(not _PG_URL, reason="set ORBITMIND_TEST_POSTGRES_URL (disposable DB)"),
]

BASE = "/api/v1/static-reports/mission"
_TABLES = (
    "artifact_records",
    "audit_events",
    "provenance_records",
    "verification_findings",
    "orbital_samples",
    "orbital_element_records",
    "missions",
)
_VALID_CHECKSUM = "a" * 64


@pytest.fixture
def pg_container(tmp_path: Path) -> Iterator[AppContainer]:
    """A container on the migrated PostgreSQL schema; do not call create_all()."""

    settings = Settings(
        database_url=_PG_URL,
        artifacts_dir=tmp_path / "artifacts",
        cache_dir=tmp_path / "cache",
        env="test",
        evidence_signing_key="test-evidence-signing-key-0123456789abcdef",
    )
    container = AppContainer(settings=settings)
    container.init_storage = lambda: None  # type: ignore[method-assign]
    assert container.database.is_postgres
    with container.database.engine.begin() as conn:
        conn.execute(text("TRUNCATE " + ", ".join(_TABLES) + " RESTART IDENTITY CASCADE"))
    yield container
    container.database.engine.dispose()


@pytest.fixture
def pg_client(pg_container: AppContainer) -> Iterator[TestClient]:
    with TestClient(create_app(pg_container), raise_server_exceptions=False) as client:
        yield client


def _seed_mission(container: AppContainer) -> str:
    """Persist a completed mission with two artifacts and a passing finding."""

    start = dt.datetime(2020, 1, 1, tzinfo=dt.UTC)
    request = MissionRequest(
        satellite_id="ISS",
        start_time=start,
        end_time=start + dt.timedelta(minutes=25),
        step_seconds=300,
    )
    mission = Mission(
        satellite_id="ISS",
        status=MissionStatus.COMPLETED,
        raw_request={"satellite_id": "ISS"},
        normalized_request=request,
        epistemic_status=EpistemicStatus.DETERMINISTIC_CALCULATION,
    )
    artifacts = [
        ArtifactRecord(
            mission_id=mission.id,
            type=output_type,
            path=f"missions/{mission.id}/{output_type.value}.png",
            sidecar_path=f"missions/{mission.id}/{output_type.value}.json",
            checksum=_VALID_CHECKSUM,
        )
        for output_type in OutputType
    ]
    findings = [
        VerificationFinding(
            check_id="altitude-monotonic",
            severity=Severity.INFO,
            status=FindingStatus.PASSED,
            explanation="all checks passed",
        )
    ]
    with container.database.session() as session:
        repo = SqlAlchemyMissionRepository(session)
        repo.add_mission(mission)
        session.flush()  # parent row visible before child artifact/finding inserts
        repo.add_artifacts(artifacts)
        repo.add_findings(mission.id, findings)
        session.commit()
    return mission.id


def _assert_safe_text(text_value: str) -> None:
    lowered = text_value.lower()
    for forbidden in (
        '"path"',
        '"sidecar_path"',
        '"url"',
        '"artifact_type"',
        "source_references",
        "tle_line",
        "raw samples",
        "raw intervals",
        "result_json",
        "request_json",
        "link_json",
        "postgresql://",
        "select ",
        "traceback",
        ".py",
        "execution_receipt",
        '"signature"',
        "hmac",
        "quantum_evidence",
        "qubo",
        "provider state",
    ):
        assert forbidden not in lowered


def test_postgres_mission_static_report_http_boundary(
    pg_client: TestClient,
    pg_container: AppContainer,
) -> None:
    mission_id = _seed_mission(pg_container)
    success = pg_client.get(f"{BASE}/{mission_id}")
    missing = pg_client.get(f"{BASE}/11111111-2222-3333-4444-555555555555")
    invalid = pg_client.get(f"{BASE}/not-a-uuid")
    query = pg_client.get(f"{BASE}/{mission_id}", params={"owner_id": "spoof"})

    assert success.status_code == 200, success.text
    body = success.json()
    assert body["schema_version"] == "static-report-v1"
    assert body["source_domain"] == "mission"
    assert body["scope_id"] == mission_id
    assert body["report_id"] == f"static-report:mission:{mission_id}:v1"
    assert body["inputs_and_provenance"]["manifest_id"] == (
        f"visual-manifest:mission:{mission_id}:v1"
    )
    assert body["mission_summary"]["artifact_count"] == 2
    assert set(body["mission_summary"]["artifact_types"]) == {"altitude_vs_time", "ground_track"}
    assert body["evidence_and_limitations"]["withheld"] is False
    assert "not proof by itself" in body["disclaimer"]
    _assert_safe_text(success.text)

    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert query.status_code == 422
    for response in (missing, invalid, query):
        assert set(response.json()) == {"code", "message"}
        _assert_safe_text(response.text)
