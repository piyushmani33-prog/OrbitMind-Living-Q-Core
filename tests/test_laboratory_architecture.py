"""Architecture-boundary tests for the Laboratory Framework (AST-based, offline).

The global layering rules (core purity, no api back-imports, quantum isolation)
in ``tests/test_architecture_boundaries.py`` already cover ``orbitmind.laboratory``
automatically. These tests add the laboratory-specific guarantees:

- pure contracts stay framework-independent (no FastAPI/Starlette/persistence);
- no dynamic loading, subprocess, network or filesystem execution surface;
- no agent/provider/quantum/camera/hardware dependency enters the core contracts.
"""

from __future__ import annotations

import ast
from pathlib import Path

import orbitmind.laboratory

_LABORATORY_ROOT = Path(orbitmind.laboratory.__file__).resolve().parent

# The laboratory domain may import only these modules (prefix match), plus the
# bare ``orbitmind`` package (exact match only, solely for ``__version__``).
_ALLOWED_IMPORT_PREFIXES = (
    "__future__",
    "enum",
    "math",
    "re",
    "typing",
    "pydantic",
    "orbitmind.core",
    "orbitmind.laboratory",
)
_ALLOWED_EXACT_IMPORTS = frozenset({"orbitmind"})

_FORBIDDEN_IMPORTS = (
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
    "fastapi",
    "starlette",
    "sqlalchemy",
    "alembic",
    "orbitmind.api",
    "orbitmind.persistence",
    "orbitmind.quantum",
    "orbitmind.camera",
    "orbitmind.sources",
    "orbitmind.orchestration",
)

_FORBIDDEN_CALL_NAMES = {"__import__", "eval", "exec", "compile", "open"}


def _laboratory_files() -> list[Path]:
    files = sorted(_LABORATORY_ROOT.rglob("*.py"))
    assert files, "laboratory package must contain source files"
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


def test_laboratory_imports_are_a_closed_allowlist() -> None:
    for py_file in _laboratory_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for module in sorted(_imports(tree)):
            allowed = module in _ALLOWED_EXACT_IMPORTS or any(
                module == prefix or module.startswith(prefix + ".")
                for prefix in _ALLOWED_IMPORT_PREFIXES
            )
            assert allowed, f"{py_file.name} imports unexpected module {module!r}"
            assert not any(
                module == forbidden or module.startswith(forbidden + ".")
                for forbidden in _FORBIDDEN_IMPORTS
            ), f"{py_file.name} imports forbidden module {module!r}"


def test_laboratory_has_no_dynamic_loading_or_execution_calls() -> None:
    for py_file in _laboratory_files():
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
                assert name not in {"import_module", "entry_points", "load_entry_point"}, (
                    f"{py_file.name} performs dynamic plugin loading via {name!r}"
                )


def test_laboratory_has_no_module_level_mutable_registry_singleton() -> None:
    """No module-level registry instance may leak state between tests/imports."""
    for py_file in _laboratory_files():
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign | ast.AnnAssign):
                value = node.value
                if isinstance(value, ast.Call):
                    callee = value.func
                    name = (
                        callee.id
                        if isinstance(callee, ast.Name)
                        else (callee.attr if isinstance(callee, ast.Attribute) else "")
                    )
                    assert name != "LaboratoryRegistry", (
                        f"{py_file.name} creates a module-level registry singleton"
                    )


def test_pure_contracts_do_not_import_presentation_or_web_frameworks() -> None:
    """Behavioral check on actual imports (not fragile source-text matching)."""
    for module_name in ("contracts", "capabilities", "registry"):
        tree = ast.parse((_LABORATORY_ROOT / f"{module_name}.py").read_text(encoding="utf-8"))
        for module in sorted(_imports(tree)):
            top_level = module.split(".", maxsplit=1)[0]
            assert top_level not in {"fastapi", "starlette", "jinja2", "html", "uvicorn"}, (
                f"{module_name}.py imports web/presentation module {module!r}"
            )


def test_existing_global_boundaries_still_cover_laboratory() -> None:
    """The laboratory package sits under src/orbitmind where the global
    boundary tests (no api back-import, quantum isolation) scan it."""
    source_root = Path(orbitmind.laboratory.__file__).resolve().parents[1]
    assert (source_root / "laboratory").is_dir()
    assert source_root.name == "orbitmind"
