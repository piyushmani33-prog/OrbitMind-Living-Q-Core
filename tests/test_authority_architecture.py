"""Architecture-boundary tests for the U7.0 authority domain (AST-based).

The global layering suites already forbid api back-imports for every package
under ``src/orbitmind``. These tests add authority-specific guarantees: a
closed import allowlist, no I/O or execution surface, no ambient clock inside
the pure decision layer, and no module-level mutable state.
"""

from __future__ import annotations

import ast
from pathlib import Path

import orbitmind.authority

_AUTHORITY_ROOT = Path(orbitmind.authority.__file__).resolve().parent

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
    # orbitmind.core.ids (uuid-backed) — this layer never generates ids.
    "orbitmind.core.errors",
    "orbitmind.core.timeutils",
    "orbitmind.authority",
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
    "shelve",
    "sqlite3",
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "orbitmind.api",
    "orbitmind.persistence",
    "orbitmind.laboratory",
    "orbitmind.sources",
    "orbitmind.orchestration",
    "orbitmind.quantum",
    "orbitmind.camera",
    "orbitmind.runtime",
)

# The pure decision layer must never read a clock, generate randomness,
# touch the filesystem, or execute anything.
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
}


def _authority_files() -> list[Path]:
    files = sorted(_AUTHORITY_ROOT.glob("*.py"))
    assert [path.name for path in files] == [
        "__init__.py",
        "contracts.py",
        "evaluation.py",
    ], "authority package must contain exactly the reviewed U7.0 modules"
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


def test_authority_imports_are_a_closed_allowlist() -> None:
    for py_file in _authority_files():
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


def test_authority_has_no_clock_io_or_execution_calls() -> None:
    for py_file in _authority_files():
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


def test_authority_has_no_module_level_mutable_state() -> None:
    for py_file in _authority_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(node, ast.Assign):
                targets, value = node.targets, node.value
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                targets, value = [node.target], node.value
            if value is None:
                continue
            # Module-level dict/list/set literals are mutable shared state
            # unless they are typing/Final-annotated frozen conventions; the
            # authority package allows only Final-annotated constants.
            if isinstance(value, ast.List | ast.Set):
                raise AssertionError(
                    f"{py_file.name} defines module-level mutable literal at line {node.lineno}"
                )
            if isinstance(value, ast.Dict):
                annotated_final = isinstance(node, ast.AnnAssign) and "Final" in ast.dump(
                    node.annotation
                )
                assert annotated_final, (
                    f"{py_file.name} defines a non-Final module-level dict at line {node.lineno}"
                )
            del targets


# Sanctioned consumers of orbitmind.authority. U7.1 adds the persistence
# adapter; API/runtime/agent/tool consumers remain forbidden until their own
# reviewed slices. Any new top-level package added here must be a conscious edit.
_SANCTIONED_AUTHORITY_CONSUMER_PACKAGES = ("persistence",)
_FORBIDDEN_AUTHORITY_CONSUMER_PACKAGES = (
    "api",
    "runtime",
    "camera",
    "quantum",
    "laboratory",
    "sources",
    "orchestration",
)


def test_authority_is_only_consumed_by_sanctioned_layers() -> None:
    """Only sanctioned layers import ``orbitmind.authority``.

    U7.0 introduced the pure contracts with no consumers; U7.1 adds exactly one
    sanctioned consumer — the persistence adapter. API/UI/runtime/agent layers
    must not import authority until their own reviewed slices.
    """
    source_root = _AUTHORITY_ROOT.parent
    consumers: set[str] = set()
    for py_file in source_root.rglob("*.py"):
        if _AUTHORITY_ROOT in py_file.parents:
            continue
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for module in _imports(tree):
            if module == "orbitmind.authority" or module.startswith("orbitmind.authority."):
                consumers.add(py_file.relative_to(source_root).parts[0])
    assert not (consumers - set(_SANCTIONED_AUTHORITY_CONSUMER_PACKAGES)), (
        f"unexpected authority consumers: {sorted(consumers)}"
    )
    for forbidden in _FORBIDDEN_AUTHORITY_CONSUMER_PACKAGES:
        assert forbidden not in consumers, f"{forbidden} must not import orbitmind.authority yet"


def test_evaluation_module_is_pure_of_pydantic_construction_side_effects() -> None:
    """evaluation.py builds decisions only from its input request: no ids,
    no clocks, no randomness — verified by the absence of any call to id/time
    generators (covered above) and by importing nothing beyond contracts."""
    tree = ast.parse((_AUTHORITY_ROOT / "evaluation.py").read_text(encoding="utf-8"))
    modules = _imports(tree)
    assert modules <= {"__future__", "types", "typing", "orbitmind.authority.contracts"}, modules
