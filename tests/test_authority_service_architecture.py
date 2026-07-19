"""Architecture guards for the U7.2 orchestration-only lifecycle boundary."""

from __future__ import annotations

import ast
from pathlib import Path

import orbitmind.orchestration

_SOURCE = Path(orbitmind.orchestration.__file__).resolve().parent / "authority_lifecycle.py"

_ALLOWED_IMPORT_PREFIXES = (
    "__future__",
    "collections.abc",
    "datetime",
    "typing",
    "unicodedata",
    "pydantic",
    "sqlalchemy.orm",
    "orbitmind.authority.contracts",
    "orbitmind.authority.evaluation",
    "orbitmind.core.errors",
    "orbitmind.core.timeutils",
    "orbitmind.persistence.authority_repository",
)

_FORBIDDEN_IMPORT_PREFIXES = (
    "os",
    "sys",
    "pathlib",
    "time",
    "uuid",
    "importlib",
    "subprocess",
    "socket",
    "http",
    "httpx",
    "urllib",
    "requests",
    "fastapi",
    "starlette",
    "orbitmind.api",
    "orbitmind.runtime",
    "orbitmind.camera",
    "orbitmind.quantum",
    "orbitmind.laboratory",
    "orbitmind.sources",
)

_FORBIDDEN_CALLS = {
    "now",
    "utcnow",
    "today",
    "time",
    "monotonic",
    "uuid4",
    "new_id",
    "open",
    "exec",
    "eval",
    "compile",
    "__import__",
    "import_module",
}


def _imports(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_lifecycle_service_imports_only_authorized_application_dependencies() -> None:
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    for module in _imports(tree):
        assert any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in _ALLOWED_IMPORT_PREFIXES
        ), module
        assert not any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in _FORBIDDEN_IMPORT_PREFIXES
        ), module


def test_lifecycle_service_has_no_ambient_clock_identity_or_execution_calls() -> None:
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = node.func
        name = (
            callee.id
            if isinstance(callee, ast.Name)
            else (callee.attr if isinstance(callee, ast.Attribute) else "")
        )
        assert name not in _FORBIDDEN_CALLS, f"forbidden call {name!r} at {node.lineno}"


def test_lifecycle_service_keeps_commands_closed_and_read_model_status_free() -> None:
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    source = _SOURCE.read_text(encoding="utf-8")
    assert 'ConfigDict(frozen=True, extra="forbid", strict=True)' in source
    assert "status:" not in source
    assert "lifecycle_status" not in source
    classes = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert {
        "CreateApprovalRequestCommand",
        "RecordApprovalDecisionCommand",
        "IssueCapabilityGrantCommand",
        "RevokeCapabilityGrantCommand",
        "EvaluateAuthorityCommand",
        "AuthorityChainReadModel",
    } <= classes
