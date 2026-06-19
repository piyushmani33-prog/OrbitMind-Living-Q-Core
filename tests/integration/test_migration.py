"""Integration test: Alembic migration builds the expected schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from orbitmind.persistence.database import Base

pytestmark = pytest.mark.integration

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


def test_alembic_upgrade_head_builds_schema(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'migrated.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")

    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    engine.dispose()

    assert tables >= EXPECTED_TABLES
    # Migration schema matches the ORM metadata (parity check).
    assert set(Base.metadata.tables) >= EXPECTED_TABLES
