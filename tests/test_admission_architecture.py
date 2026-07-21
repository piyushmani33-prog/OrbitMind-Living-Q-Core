"""Architecture-boundary tests for the Operation Admission v0 domain (AST-based).

These pin admission-specific guarantees: a closed file + import allowlist, no I/O
or execution surface, no ambient clock inside the pure policy, no module-level
mutable state, and — critically — the admission **domain** never imports
``orbitmind.authority`` (the authority bridge lives only in orchestration).
"""

from __future__ import annotations

import ast
from pathlib import Path

import orbitmind.admission

_ADMISSION_ROOT = Path(orbitmind.admission.__file__).resolve().parent

_ALLOWED_IMPORT_PREFIXES = (
    "__future__",
    "datetime",
    "enum",
    "json",
    "re",
    "types",
    "typing",
    "unicodedata",
    "pydantic",
    # Narrow core surface: errors + time normalization only. Notably NOT
    # orbitmind.core.ids (uuid-backed) — this layer never generates ids — and NOT
    # orbitmind.authority (the domain must not depend on Authority).
    "orbitmind.core.errors",
    "orbitmind.core.timeutils",
    "orbitmind.admission",
)

_FORBIDDEN_IMPORTS = (
    "os",
    "sys",
    "io",
    "pathlib",
    "time",
    "importlib",
    "subprocess",
    "socket",
    "http",
    "httpx",
    "urllib",
    "requests",
    "threading",
    "multiprocessing",
    "asyncio",
    "ctypes",
    "pickle",
    "sqlite3",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "orbitmind.api",
    "orbitmind.authority",
    "orbitmind.persistence",
    "orbitmind.orchestration",
    "orbitmind.laboratory",
    "orbitmind.sources",
    "orbitmind.quantum",
    "orbitmind.camera",
    "orbitmind.runtime",
    "orbitmind.core.ids",
    "orbitmind.core.checksums",
)

_FORBIDDEN_CALL_NAMES = {
    "now",
    "utcnow",
    "today",
    "time",
    "monotonic",
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "import_module",
    "uuid4",
    "new_id",
    "urandom",
    "token_bytes",
    "token_hex",
    "system",
    "popen",
    "run",
}


def _admission_files() -> list[Path]:
    files = sorted(_ADMISSION_ROOT.glob("*.py"))
    assert [path.name for path in files] == [
        "__init__.py",
        "contracts.py",
        "policy.py",
    ], "admission package must contain exactly the reviewed U7.4 modules"
    return files


def _imports(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def test_admission_imports_are_a_closed_allowlist() -> None:
    for py_file in _admission_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for module in sorted(_imports(tree)):
            allowed = any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in _ALLOWED_IMPORT_PREFIXES
            )
            assert allowed, f"{py_file.name} imports unexpected module {module!r}"
            forbidden = any(
                module == name or module.startswith(name + ".") for name in _FORBIDDEN_IMPORTS
            )
            assert not forbidden, f"{py_file.name} imports forbidden module {module!r}"


def test_admission_domain_never_imports_authority() -> None:
    for py_file in _admission_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for module in _imports(tree):
            assert not module.startswith("orbitmind.authority"), (
                f"{py_file.name} must not import Authority (bridge lives in orchestration)"
            )


def test_admission_has_no_clock_io_or_execution_calls() -> None:
    for py_file in _admission_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                callee = node.func
                name = (
                    callee.id
                    if isinstance(callee, ast.Name)
                    else (callee.attr if isinstance(callee, ast.Attribute) else "")
                )
                assert name not in _FORBIDDEN_CALL_NAMES, (
                    f"{py_file.name} calls forbidden function {name!r}"
                )


def test_admission_has_no_module_level_mutable_state() -> None:
    for py_file in _admission_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            value: ast.expr | None = None
            annotated_final = False
            if isinstance(node, ast.Assign):
                value = node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                value = node.value
                annotated_final = "Final" in ast.dump(node.annotation)
            if value is None:
                continue
            if isinstance(value, ast.List | ast.Set):
                raise AssertionError(
                    f"{py_file.name} defines module-level mutable literal at line {node.lineno}"
                )
            if isinstance(value, ast.Dict):
                assert annotated_final, (
                    f"{py_file.name} defines a non-Final module-level dict at line {node.lineno}"
                )


_SANCTIONED_ADMISSION_CONSUMER_PACKAGES = ("orchestration", "persistence")
_FORBIDDEN_ADMISSION_CONSUMER_PACKAGES = (
    "authority",
    "runtime",
    "camera",
    "quantum",
    "laboratory",
    "sources",
)


def test_admission_is_only_consumed_by_sanctioned_layers() -> None:
    source_root = _ADMISSION_ROOT.parent
    consumers: set[str] = set()
    for py_file in source_root.rglob("*.py"):
        if _ADMISSION_ROOT in py_file.parents:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for module in _imports(tree):
            if module == "orbitmind.admission" or module.startswith("orbitmind.admission."):
                consumers.add(py_file.relative_to(source_root).parts[0])
    assert not (consumers - set(_SANCTIONED_ADMISSION_CONSUMER_PACKAGES)), (
        f"unexpected admission consumers: {sorted(consumers)}"
    )
    for forbidden in _FORBIDDEN_ADMISSION_CONSUMER_PACKAGES:
        assert forbidden not in consumers, f"{forbidden} must not import orbitmind.admission"
