"""Integration test: Alembic migration builds the expected schema."""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

import orbitmind.persistence.observation_geometry_models as _observation_geometry_models
import orbitmind.persistence.observation_planning_models as _observation_planning_models
from orbitmind.persistence.database import Base

pytestmark = pytest.mark.integration
REGISTERED_MODEL_MODULES = (_observation_geometry_models, _observation_planning_models)

PHASE1_REVISION = "b38aa92661c2"
PHASE2_REVISION = "080f934b44d1"
PHASE4A_HEAD = "h4c5d6e7f8a9"

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

PHASE3A_TABLES = {
    "space_objects",
    "space_object_identifiers",
    "space_object_aliases",
    "small_body_orbits",
    "small_body_physical_properties",
    "small_body_classifications",
    "close_approaches",
    "small_body_query_runs",
}

PHASE4B_PLANNING_HEAD = "i5d6e7f8a9b0"

PHASE4B_OBSERVATION_PLANNING_TABLES = {
    "observation_planning_requests",
    "observation_planning_runs",
    "observation_plans",
}

PHASE4B_PROVENANCE_ELIGIBILITY_TABLES = {
    "observation_input_provenance",
    "observation_input_provenance_parents",
    "observation_eligibility_window_sets",
    "observation_eligibility_windows",
}

PHASE4B_PROVENANCE_ANCHORED_HEAD = "j6e7f8a9b0c1"

PHASE4B_PROVENANCE_LINK_TABLES = {
    "observation_planning_provenance_links",
}

PHASE4B_PROVENANCE_LINK_HEAD = "k6e7f8a9b0c2"

PHASE4C_OBSERVATION_GEOMETRY_HEAD = "l7a8b9c0d1e2"

PHASE4C_OBSERVATION_GEOMETRY_TABLES = {
    "observation_geometry_requests",
    "observation_geometry_runs",
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
    assert tables >= PHASE3A_TABLES
    assert tables >= PHASE4B_OBSERVATION_PLANNING_TABLES
    assert tables >= PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
    assert tables >= PHASE4B_PROVENANCE_LINK_TABLES
    assert tables >= PHASE4C_OBSERVATION_GEOMETRY_TABLES
    # Migration schema matches the ORM metadata (parity check).
    assert set(Base.metadata.tables) >= (
        EXPECTED_TABLES
        | PHASE2_TABLES
        | PHASE3A_TABLES
        | PHASE4B_OBSERVATION_PLANNING_TABLES
        | PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
        | PHASE4B_PROVENANCE_LINK_TABLES
        | PHASE4C_OBSERVATION_GEOMETRY_TABLES
    )


def test_upgrade_from_phase2_schema_is_non_destructive(tmp_path: Path) -> None:
    """Upgrading a Phase 2 database to Phase 3A adds tables and keeps mission/source data."""
    db_url = f"sqlite:///{(tmp_path / 'p2.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, PHASE2_REVISION)
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
        conn.execute(
            text(
                "INSERT INTO source_definitions (source_id, name, kind, description, enabled, "
                "updated_at) VALUES ('celestrak', 'CelesTrak', 'celestrak', 'x', 1, "
                "'2026-06-19 00:00:00')"
            )
        )

    command.upgrade(cfg, "head")
    tables = set(inspect(engine).get_table_names())
    assert tables >= PHASE3A_TABLES
    with engine.connect() as conn:
        missions = conn.execute(text("SELECT COUNT(*) FROM missions")).scalar_one()
        sources = conn.execute(text("SELECT COUNT(*) FROM source_definitions")).scalar_one()
    engine.dispose()
    assert missions == 1  # existing satellite mission data preserved
    assert sources == 1  # existing source data preserved


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


def test_observation_planning_migration_downgrade_and_reupgrade(tmp_path: Path) -> None:
    db_url = f"sqlite:///{(tmp_path / 'p4b.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) >= (
        PHASE4B_OBSERVATION_PLANNING_TABLES | PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
    )
    engine.dispose()

    command.downgrade(cfg, PHASE4A_HEAD)
    engine = create_engine(db_url)
    downgraded_tables = set(inspect(engine).get_table_names())
    assert downgraded_tables.isdisjoint(PHASE4B_OBSERVATION_PLANNING_TABLES)
    assert downgraded_tables >= EXPECTED_TABLES
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) >= (
        PHASE4B_OBSERVATION_PLANNING_TABLES | PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
    )
    engine.dispose()


def test_provenance_eligibility_migration_downgrades_to_previous_head(
    tmp_path: Path,
) -> None:
    db_url = f"sqlite:///{(tmp_path / 'p4b-provenance.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    tables = set(inspect(engine).get_table_names())
    assert tables >= PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
    assert tables >= PHASE4B_OBSERVATION_PLANNING_TABLES
    engine.dispose()

    command.downgrade(cfg, PHASE4B_PLANNING_HEAD)
    engine = create_engine(db_url)
    downgraded = set(inspect(engine).get_table_names())
    assert downgraded.isdisjoint(PHASE4B_PROVENANCE_ELIGIBILITY_TABLES)
    assert downgraded >= PHASE4B_OBSERVATION_PLANNING_TABLES
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) >= PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
    engine.dispose()


def test_provenance_anchored_link_migration_downgrades_to_previous_head(
    tmp_path: Path,
) -> None:
    db_url = f"sqlite:///{(tmp_path / 'p4b-anchored-link.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert tables >= PHASE4B_PROVENANCE_LINK_TABLES
    constraints = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("observation_planning_provenance_links")
    }
    indexes = {
        index["name"] for index in inspector.get_indexes("observation_planning_provenance_links")
    }
    engine.dispose()
    assert "fk_oppl_provenance_owner" in constraints
    assert "fk_oppl_eligibility_set_owner" in constraints
    assert "fk_oppl_request_owner" in constraints
    assert "fk_oppl_run_owner" in constraints
    assert "ix_oppl_checksum" in indexes

    command.downgrade(cfg, PHASE4B_PROVENANCE_ANCHORED_HEAD)
    engine = create_engine(db_url)
    downgraded = set(inspect(engine).get_table_names())
    assert downgraded.isdisjoint(PHASE4B_PROVENANCE_LINK_TABLES)
    assert downgraded >= PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
    assert downgraded >= PHASE4B_OBSERVATION_PLANNING_TABLES
    engine.dispose()

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) >= PHASE4B_PROVENANCE_LINK_TABLES
    engine.dispose()


def test_observation_geometry_migration_downgrade_reupgrade_and_parity(
    tmp_path: Path,
) -> None:
    db_url = f"sqlite:///{(tmp_path / 'p4c-geometry.db').as_posix()}"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)

    command.upgrade(cfg, "head")
    engine = create_engine(db_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert tables >= PHASE4C_OBSERVATION_GEOMETRY_TABLES
    assert tables >= PHASE4B_PROVENANCE_LINK_TABLES
    request_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("observation_geometry_requests")
    }
    run_constraints = {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("observation_geometry_runs")
    }
    run_fks = {
        constraint["name"] for constraint in inspector.get_foreign_keys("observation_geometry_runs")
    }
    request_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("observation_geometry_requests")
    }
    run_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("observation_geometry_runs")
    }
    run_indexes = {index["name"] for index in inspector.get_indexes("observation_geometry_runs")}
    engine.dispose()
    assert "uq_og_requests_owner_checksum" in request_constraints
    assert "uq_og_requests_idempotency" in request_constraints
    assert "uq_og_runs_owner_request" in run_constraints
    assert "fk_og_runs_request_owner" in run_fks
    assert "ck_og_requests_schema" in request_checks
    assert "ck_og_runs_schema" in run_checks
    assert "ck_og_runs_computation_version" in run_checks
    assert "ix_og_runs_geometry" in run_indexes
    assert set(Base.metadata.tables) >= PHASE4C_OBSERVATION_GEOMETRY_TABLES

    command.downgrade(cfg, PHASE4B_PROVENANCE_LINK_HEAD)
    engine = create_engine(db_url)
    downgraded = set(inspect(engine).get_table_names())
    assert downgraded.isdisjoint(PHASE4C_OBSERVATION_GEOMETRY_TABLES)
    assert downgraded >= PHASE4B_PROVENANCE_LINK_TABLES
    assert downgraded >= PHASE4B_PROVENANCE_ELIGIBILITY_TABLES
    assert downgraded >= PHASE4B_OBSERVATION_PLANNING_TABLES
    engine.dispose()

    command.upgrade(cfg, PHASE4C_OBSERVATION_GEOMETRY_HEAD)
    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) >= PHASE4C_OBSERVATION_GEOMETRY_TABLES
    engine.dispose()
