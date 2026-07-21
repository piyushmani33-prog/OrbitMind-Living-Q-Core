"""Architecture-boundary tests for the Operation Admission v0 service (AST-based).

The orchestration ``admission_lifecycle`` is the sanctioned Authority bridge: it may
consume the authority contracts/evaluator and repositories, but must not import an
API/runtime/provider/agent surface, must not read an ambient clock (``evaluated_at``
is injected), and must not generate ids or execute anything.
"""

from __future__ import annotations

import ast
from pathlib import Path

import orbitmind.orchestration

_SERVICE_FILE = Path(orbitmind.orchestration.__file__).resolve().parent / "admission_lifecycle.py"

_ALLOWED_IMPORT_PREFIXES = (
    "__future__",
    "collections.abc",
    "datetime",
    "typing",
    "sqlalchemy.orm",
    "orbitmind.admission.contracts",
    "orbitmind.admission.policy",
    "orbitmind.authority.contracts",
    "orbitmind.authority.evaluation",
    "orbitmind.core.checksums",
    "orbitmind.core.errors",
    "orbitmind.core.timeutils",
    "orbitmind.persistence.admission_repository",
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
    "system",
    "popen",
}


def _imports(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_service_imports_only_authorized_application_dependencies() -> None:
    tree = ast.parse(_SERVICE_FILE.read_text(encoding="utf-8"))
    for module in sorted(_imports(tree)):
        allowed = any(
            module == prefix or module.startswith(prefix + ".")
            for prefix in _ALLOWED_IMPORT_PREFIXES
        )
        assert allowed, f"admission_lifecycle imports unexpected module {module!r}"
        forbidden = any(
            module == name or module.startswith(name + ".") for name in _FORBIDDEN_IMPORT_PREFIXES
        )
        assert not forbidden, f"admission_lifecycle imports forbidden module {module!r}"


def test_service_has_no_clock_uuid_or_execution_calls() -> None:
    tree = ast.parse(_SERVICE_FILE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = node.func
            name = (
                callee.id
                if isinstance(callee, ast.Name)
                else (callee.attr if isinstance(callee, ast.Attribute) else "")
            )
            assert name not in _FORBIDDEN_CALLS, (
                f"admission_lifecycle calls forbidden function {name!r} at line {node.lineno}"
            )
