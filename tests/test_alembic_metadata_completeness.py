"""Regression guard for Alembic target-metadata model registration."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from orbitmind.persistence.database import Base

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PERSISTENCE_ROOT = PROJECT_ROOT / "src" / "orbitmind" / "persistence"
ALEMBIC_ENV = PROJECT_ROOT / "migrations" / "env.py"


def _declared_tables() -> dict[str, set[str]]:
    declarations: dict[str, set[str]] = {}
    for path in sorted(PERSISTENCE_ROOT.glob("*.py")):
        tables: set[str] = set()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = node.targets
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
                value = node.value
            else:
                continue
            if (
                any(
                    isinstance(target, ast.Name) and target.id == "__tablename__"
                    for target in targets
                )
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                tables.add(value.value)
        if tables:
            declarations[path.stem] = tables
    return declarations


def _alembic_model_imports() -> set[str]:
    tree = ast.parse(ALEMBIC_ENV.read_text(encoding="utf-8"), filename=str(ALEMBIC_ENV))
    return {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith("orbitmind.persistence.")
    }


def test_all_declared_persistence_tables_are_registered_with_alembic_metadata() -> None:
    declarations = _declared_tables()
    expected_modules = {f"orbitmind.persistence.{module}" for module in declarations}
    alembic_imports = _alembic_model_imports()

    assert len(declarations) == 9
    assert expected_modules <= alembic_imports
    for module in sorted(expected_modules):
        importlib.import_module(module)

    declared_tables = set().union(*declarations.values())
    assert len(declared_tables) == 79
    assert declared_tables <= set(Base.metadata.tables)
    assert "operation_admission_records" in Base.metadata.tables
    assert "tool_gateway_decision_records" in Base.metadata.tables
