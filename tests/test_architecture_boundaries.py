"""Dependency-free architecture boundary tests for OrbitMind's module layering.

These AST-based tests promote documented module-boundary invariants into
CI-checked guarantees. They enforce three rules that currently hold:

- ``core`` imports nothing internal (no ``orbitmind.*`` outside ``orbitmind.core``);
- no module outside ``api/`` imports ``orbitmind.api`` (downstream must not import API);
- the orbital slice does not import ``orbitmind.quantum`` (ADR-0005 / CLAUDE.md #6),
  with the only sanctioned quantum consumers being ``optimization`` and
  ``observability`` (both use ``quantum.adapter.quantum_available`` — a capability
  check, not mission-path quantum computation).

Plain offline tests: no ``postgres``/``quantum`` marker, stdlib only. Simulator-
specific guards (no-Qiskit, mission-not-importing-simulator) live in
``tests/test_quantum_simulator_v0.py`` and are intentionally not duplicated here.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import orbitmind

_SOURCE_ROOT = Path(orbitmind.__file__).resolve().parent

# Packages allowed to import ``orbitmind.quantum`` (sanctioned by ADR-0005): the
# quantum package itself, the Phase-4 optimization work, and the observability
# capability self-report. Any future addition here is a conscious, reviewed edit.
_ALLOWED_QUANTUM_CONSUMERS = ("quantum", "optimization", "observability")

# Narrow composition-root exception: ``orbitmind.sample`` is an executable reviewer
# entrypoint (``python -m orbitmind.sample``), not domain/core/business logic. CLI
# composition roots may import the API layer to wire the existing app container and
# DTO projections for an executable local flow. This does not permit domain, core,
# orbital, or arbitrary future modules to import ``orbitmind.api``.
_API_IMPORT_ENTRYPOINT_EXCEPTIONS = {_SOURCE_ROOT / "sample.py"}


def _imported_modules(source: str) -> set[str]:
    """Return the set of absolute module names imported by a source file."""
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            # Skip relative imports (``from . import x``) where module is None.
            if node.module is not None:
                modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


def _python_files(*, exclude_packages: tuple[str, ...] = ()) -> Iterator[Path]:
    """Yield ``src/orbitmind`` Python files, excluding the given top-level packages."""
    excluded_dirs = {_SOURCE_ROOT / package for package in exclude_packages}
    for py_file in _SOURCE_ROOT.rglob("*.py"):
        if any(
            excluded == py_file.parent or excluded in py_file.parents for excluded in excluded_dirs
        ):
            continue
        yield py_file


def _offending_imports(py_file: Path, forbidden_prefix: str) -> list[str]:
    modules = _imported_modules(py_file.read_text(encoding="utf-8"))
    return sorted(module for module in modules if module.startswith(forbidden_prefix))


def test_core_has_no_internal_orbitmind_imports() -> None:
    """Boundary: ``core`` imports nothing internal except ``orbitmind.core.*``."""
    core_dir = _SOURCE_ROOT / "core"
    for py_file in core_dir.rglob("*.py"):
        modules = _imported_modules(py_file.read_text(encoding="utf-8"))
        offending = sorted(
            module
            for module in modules
            if module == "orbitmind"
            or (module.startswith("orbitmind.") and not module.startswith("orbitmind.core"))
        )
        assert not offending, (
            f"[core-purity] {py_file} imports non-core orbitmind modules {offending}; "
            "core must import nothing internal"
        )


def test_no_module_imports_api_except_api() -> None:
    """Boundary: no module outside ``api/`` imports ``orbitmind.api``."""
    for py_file in _python_files(exclude_packages=("api",)):
        if py_file in _API_IMPORT_ENTRYPOINT_EXCEPTIONS:
            continue
        offending = _offending_imports(py_file, "orbitmind.api")
        assert not offending, (
            f"[no-api-backimport] {py_file} imports the API layer {offending}; "
            "downstream layers must not import orbitmind.api"
        )


def test_orbital_slice_does_not_import_quantum() -> None:
    """Boundary: only sanctioned consumers import ``orbitmind.quantum`` (ADR-0005)."""
    for py_file in _python_files(exclude_packages=_ALLOWED_QUANTUM_CONSUMERS):
        offending = _offending_imports(py_file, "orbitmind.quantum")
        assert not offending, (
            f"[orbital-quantum-boundary] {py_file} imports {offending}; the orbital slice "
            f"must not import orbitmind.quantum (allowed consumers: {_ALLOWED_QUANTUM_CONSUMERS})"
        )
