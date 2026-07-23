"""Closed architectural boundary checks for the non-executing gateway domain."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "src" / "orbitmind" / "toolgateway"
PRODUCTION = ROOT / "src" / "orbitmind"
DOMAIN_FILES = {"__init__.py", "catalog.py", "contracts.py", "policy.py"}
ALLOWED_IMPORTS = {
    "__future__",
    "dataclasses",
    "datetime",
    "enum",
    "hashlib",
    "json",
    "types",
    "typing",
    "unicodedata",
    "pydantic",
    "orbitmind.core.errors",
    "orbitmind.core.timeutils",
}
FORBIDDEN_CALLS = {
    "__import__",
    "compile",
    "eval",
    "exec",
    "import_module",
    "open",
    "popen",
    "run",
    "system",
}


def _imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports.append(node.module or "")
        elif isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
    return tuple(imports)


def test_domain_file_set_and_closed_import_allowlist() -> None:
    assert {path.name for path in PACKAGE.glob("*.py")} == DOMAIN_FILES
    for path in PACKAGE.glob("*.py"):
        for imported in _imports(path):
            assert imported.startswith("orbitmind.toolgateway") or imported in ALLOWED_IMPORTS, (
                path,
                imported,
            )


def test_only_orchestration_and_persistence_consume_the_domain() -> None:
    consumers: set[str] = set()
    for path in PRODUCTION.rglob("*.py"):
        if PACKAGE in path.parents:
            continue
        if any(name.startswith("orbitmind.toolgateway") for name in _imports(path)):
            consumers.add(path.relative_to(PRODUCTION).parts[0])
    assert consumers == {"orchestration", "persistence"}


def test_no_adapter_dynamic_import_or_execution_calls_exist() -> None:
    assert not (PACKAGE / "adapter.py").exists()
    checked = (
        *PACKAGE.glob("*.py"),
        PRODUCTION / "orchestration" / "tool_gateway_lifecycle.py",
        PRODUCTION / "persistence" / "tool_gateway_repository.py",
    )
    for path in checked:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else ""
                )
                assert name not in FORBIDDEN_CALLS, (path, node.lineno, name)
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                assert all(
                    not name.startswith(
                        ("importlib", "subprocess", "socket", "http", "requests", "pathlib", "os")
                    )
                    for name in _imports_from_node(node)
                ), (path, node.lineno)


def _imports_from_node(node: ast.Import | ast.ImportFrom) -> tuple[str, ...]:
    if isinstance(node, ast.ImportFrom):
        return (node.module or "",)
    return tuple(alias.name for alias in node.names)


def test_module_constants_have_no_runtime_mutation_sites() -> None:
    """Private construction maps are static; no module mutates them after declaration."""
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.AugAssign, ast.AnnAssign)) and isinstance(
                node.target, ast.Subscript
            ):
                raise AssertionError((path, node.lineno, "subscript mutation"))
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Subscript) for target in node.targets
            ):
                raise AssertionError((path, node.lineno, "subscript mutation"))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {
                    "add",
                    "append",
                    "clear",
                    "extend",
                    "insert",
                    "pop",
                    "remove",
                    "setdefault",
                    "update",
                }, (path, node.lineno, node.func.attr)


def test_public_domain_surface_has_no_execution_receipt_or_result() -> None:
    init_tree = ast.parse((PACKAGE / "__init__.py").read_text(encoding="utf-8"))
    exported_literals = {
        value.value
        for node in ast.walk(init_tree)
        if isinstance(node, (ast.Tuple, ast.List))
        for value in node.elts
        if isinstance(value, ast.Constant) and isinstance(value.value, str)
    }
    assert exported_literals == {"GatewayDecision", "ToolDescriptor", "ToolInvocationProposal"}
    assert not any(
        token in name.lower()
        for name in exported_literals
        for token in ("adapter", "execute", "receipt", "result")
    )
