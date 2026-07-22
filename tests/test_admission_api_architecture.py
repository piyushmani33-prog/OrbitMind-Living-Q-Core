"""AST-pinned dependency and no-execution boundaries for the Admission API."""

from __future__ import annotations

import ast
from pathlib import Path

import orbitmind.api
import orbitmind.orchestration

_API_ROOT = Path(orbitmind.api.__file__).resolve().parent
_ORCHESTRATION_ROOT = Path(orbitmind.orchestration.__file__).resolve().parent
_SURFACE = (
    _API_ROOT / "admission_schemas.py",
    _API_ROOT / "routers" / "admission.py",
)
_NO_EXECUTION_SURFACE = (*_SURFACE, _ORCHESTRATION_ROOT / "admission_evidence.py")


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_api_imports_only_the_approved_admission_contract_surface() -> None:
    admission_imports = {
        module
        for path in _SURFACE
        for module in _imports(path)
        if module == "orbitmind.admission" or module.startswith("orbitmind.admission.")
    }
    assert admission_imports == {"orbitmind.admission.contracts"}


def test_api_never_constructs_sqlalchemy_repositories() -> None:
    for path in _SURFACE:
        tree = _tree(path)
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "SqlAlchemyAdmissionRepository" not in imported_names
        assert "SqlAlchemyAuthorityRepository" not in imported_names
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert not node.func.id.startswith("SqlAlchemy"), (
                    f"{path.name} directly constructs {node.func.id}"
                )


def test_admission_api_and_projection_have_no_execution_surface() -> None:
    forbidden_modules = (
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "orbitmind.runtime",
        "orbitmind.execution",
        "orbitmind.tools",
        "orbitmind.providers",
        "orbitmind.agents",
        "orbitmind.worktree",
        "orbitmind.deployment",
        "orbitmind.quantum",
    )
    forbidden_calls = {"exec", "eval", "system", "popen", "Popen", "run"}
    for path in _NO_EXECUTION_SURFACE:
        for module in _imports(path):
            assert not any(
                module == forbidden or module.startswith(forbidden + ".")
                for forbidden in forbidden_modules
            ), f"{path.name} imports forbidden execution surface {module}"
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                assert name not in forbidden_calls, f"{path.name} calls forbidden {name}"


def test_application_has_no_permissive_cors_middleware() -> None:
    for path in _API_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "CORSMiddleware" not in source
        assert "allow_origins" not in source
