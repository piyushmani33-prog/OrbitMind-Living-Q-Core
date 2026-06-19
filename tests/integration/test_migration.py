"""Integration test: Alembic migration builds the expected schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from orbitmind.persistence.database import Base

pytestmark = pytest.mark.integration

PHASE1_REVISION = "b38aa92661c2"

EXPECTED_TABLES = {
    "missions",
    "mission_inputs",
    "workflow_runs",
    "orbital_samples",
    "verification_findings",
    "provenance_records",
    "artifact_records",
    "audit_events",
}

PHASE2_TABLES = {
    "source_definitions",
    "source_policies",
    "source_fetches",
    "source_cache_entries",
    "source_health_events",
    "orbital_element_records",
}


def test_alembic_upgrade_head_builds_schema(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    assert tables >= EXPECTED_TABLES
    assert tables >= PHASE2_TABLES
    # Migration schema matches the ORM metadata (parity check).
    assert set(Base.metadata.tables) >= (EXPECTED_TABLES | PHASE2_TABLES)


def test_upgrade_from_phase1_schema_is_non_destructive(tmp_path: Path) -> None:
    """Upgrading an existing Phase 1 database adds Phase 2 tables and keeps data."""
    db_url = f"sqlite:///{(tmp_path / 'p1.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    # Build the Phase 1 schema and insert a mission row.
    command.upgrade(cfg, PHASE1_REVISION)
    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO missions (id, satellite_id, status, raw_request, "
                "normalized_request, epistemic_status, created_at) VALUES "
                "('m1', 'ISS', 'completed', '{}', '{}', 'deterministic-calculation', "
                "'2026-06-19 00:00:00')"
            )
        )

    # Upgrade to head (Phase 2): new tables appear, existing data survives.
    command.upgrade(cfg, "head")
    tables = set(inspect(engine).get_table_names())
    assert tables >= PHASE2_TABLES
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM missions")).scalar_one()
    engine.dispose()
    assert count == 1  # existing mission data preserved (non-destructive)
