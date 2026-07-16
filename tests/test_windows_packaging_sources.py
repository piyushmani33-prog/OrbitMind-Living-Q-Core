"""Static review tests for unexecuted U5.0B1 packaging sources."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = PROJECT_ROOT / "packaging" / "orbitmind.spec"
LOCK = PROJECT_ROOT / "requirements" / "u5.0b0-windows-py312.lock.txt"
EXPECTED_LOCK_HASH = "785d303155e2ee03915b17d5d5f9a24f009d087465af2b1d9355de2ac0c4102c"
SPEC_PATH_NAMES = {"SPEC_DIR", "ROOT", "SOURCE", "MIGRATIONS", "SAMPLES", "LAUNCHER"}
MIGRATION_HIDDEN_IMPORTS = {"orbitmind.persistence.research_models"}
MIGRATION_NORMAL_ANALYSIS_IMPORTS = {
    "orbitmind.core.config",
    "orbitmind.persistence.database",
    "orbitmind.persistence.memory_models",
    "orbitmind.persistence.models",
    "orbitmind.persistence.observation_geometry_models",
    "orbitmind.persistence.observation_planning_models",
    "orbitmind.persistence.optimization_models",
}
VERIFIER = PROJECT_ROOT / "scripts" / "verify_windows_poc.ps1"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_windows_poc.ps1"
EXPECTED_SPEC_HASH = "463c3623086ee887016852fc9ddee1ce51c5db7f2e55bba2e7e2a423456e4612"
POWERSHELL_PARSER_SKIP_REASON = (
    "PowerShell parser validation requires powershell.exe or pwsh on the test host."
)
PHYSICAL_WINDOWS_PATH_SKIP_REASON = "Physical Windows path semantics require a Windows host."


def _powershell_executable() -> str:
    for command in ("powershell.exe", "pwsh"):
        executable = shutil.which(command)
        if executable is not None:
            return executable
    pytest.skip(POWERSHELL_PARSER_SKIP_REASON)


def _evaluate_spec_paths(spec_dir: Path) -> dict[str, Path]:
    """Evaluate only the spec's path preparation, never its PyInstaller DSL."""
    tree = ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))
    selected: list[ast.stmt] = []
    for node in tree.body:
        is_path_preparation = (
            (isinstance(node, ast.ImportFrom) and node.module == "pathlib")
            or (
                isinstance(node, ast.Assign)
                and any(
                    isinstance(target, ast.Name) and target.id in SPEC_PATH_NAMES
                    for target in node.targets
                )
            )
            or (
                isinstance(node, ast.If)
                and any(
                    isinstance(child, ast.Name) and child.id == "LAUNCHER"
                    for child in ast.walk(node)
                )
            )
        )
        if is_path_preparation:
            selected.append(node)

    namespace: dict[str, object] = {"SPECPATH": str(spec_dir)}
    path_module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(path_module, str(SPEC), "exec"), namespace)

    paths: dict[str, Path] = {}
    for name in SPEC_PATH_NAMES:
        value = namespace.get(name)
        assert isinstance(value, Path)
        paths[name] = value
    return paths


def _spec_tree() -> ast.Module:
    return ast.parse(SPEC.read_text(encoding="utf-8"), filename=str(SPEC))


def _assigned_string_list(name: str) -> list[str]:
    for node in _spec_tree().body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        assert isinstance(value, list)
        assert all(isinstance(item, str) for item in value)
        return value
    raise AssertionError(f"Missing string-list assignment: {name}")


def _analysis_string_list(keyword_name: str) -> list[str]:
    for node in ast.walk(_spec_tree()):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "Analysis":
            continue
        for keyword in node.keywords:
            if keyword.arg == keyword_name:
                value = ast.literal_eval(keyword.value)
                assert isinstance(value, list)
                assert all(isinstance(item, str) for item in value)
                return value
    raise AssertionError(f"Missing Analysis keyword: {keyword_name}")


def _explicit_data_mappings() -> list[tuple[Path, str]]:
    paths = _evaluate_spec_paths(SPEC.parent.resolve())
    namespace: dict[str, object] = {**paths, "str": str}
    for node in _spec_tree().body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(target, ast.Name) and target.id == "datas" for target in node.targets
        ):
            continue
        assert isinstance(node.value, ast.List)
        mappings: list[tuple[Path, str]] = []
        for item in node.value.elts:
            if not isinstance(item, ast.Tuple) or len(item.elts) != 2:
                continue
            expression = ast.fix_missing_locations(ast.Expression(body=item.elts[0]))
            source = eval(
                compile(expression, str(SPEC), "eval"),
                {"__builtins__": {}},
                namespace,
            )
            destination = ast.literal_eval(item.elts[1])
            assert isinstance(source, str)
            assert isinstance(destination, str)
            mappings.append((Path(source), destination))
        return mappings
    raise AssertionError("Missing datas assignment")


def _absolute_orbitmind_imports(path: Path) -> set[str]:
    imports: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(
                alias.name
                for alias in node.names
                if alias.name == "orbitmind" or alias.name.startswith("orbitmind.")
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and (node.module == "orbitmind" or node.module.startswith("orbitmind."))
        ):
            imports.add(node.module)
    return imports


def _orbitmind_collection_calls() -> list[tuple[str, str | None]]:
    calls: list[tuple[str, str | None]] = []
    for node in ast.walk(_spec_tree()):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            function_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            function_name = node.func.attr
        else:
            continue
        if function_name not in {"collect_all", "collect_submodules"}:
            continue
        package = None
        if (
            node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            package = node.args[0].value
        calls.append((function_name, package))
    return calls


def _spec_has_path_join(base_name: str, child_name: str) -> bool:
    return any(
        isinstance(node, ast.BinOp)
        and isinstance(node.op, ast.Div)
        and isinstance(node.left, ast.Name)
        and node.left.id == base_name
        and isinstance(node.right, ast.Constant)
        and node.right.value == child_name
        for node in ast.walk(_spec_tree())
    )


def _powershell_ast_summary(path: Path) -> dict[str, object]:
    command = r"""
$tokens = $null
$errors = $null
$path = [Environment]::GetEnvironmentVariable("ORBITMIND_TEST_VERIFIER_PATH", "Process")
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $path, [ref]$tokens, [ref]$errors
)
[ordered]@{
    errors = @($errors | ForEach-Object { $_.Message })
    commands = @(
        $ast.FindAll(
            { param($node) $node -is [System.Management.Automation.Language.CommandAst] },
            $true
        ) | ForEach-Object { $_.GetCommandName() } | Where-Object { $null -ne $_ }
    )
    functions = @(
        $ast.FindAll(
            {
                param($node)
                $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
            },
            $true
        ) | ForEach-Object { $_.Name }
    )
    members = @(
        $ast.FindAll(
            { param($node) $node -is [System.Management.Automation.Language.MemberExpressionAst] },
            $true
        ) | ForEach-Object { $_.Member.Value }
    )
} | ConvertTo-Json -Depth 5 -Compress
"""
    environment = os.environ.copy()
    environment["ORBITMIND_TEST_VERIFIER_PATH"] = str(path)
    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    summary = json.loads(completed.stdout)
    assert isinstance(summary, dict)
    return summary


def _powershell_parse_errors(path: Path) -> list[str]:
    command = r"""
$tokens = $null
$errors = $null
$path = [Environment]::GetEnvironmentVariable("ORBITMIND_TEST_SCRIPT_PATH", "Process")
[System.Management.Automation.Language.Parser]::ParseFile(
    $path, [ref]$tokens, [ref]$errors
) | Out-Null
ConvertTo-Json -InputObject @($errors | ForEach-Object { $_.Message }) -Compress
"""
    environment = os.environ.copy()
    environment["ORBITMIND_TEST_SCRIPT_PATH"] = str(path)
    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    errors = json.loads(completed.stdout)
    assert isinstance(errors, list)
    assert all(isinstance(error, str) for error in errors)
    return errors


def _evaluate_build_path_contract(external_root: str, wheelhouse: str) -> dict[str, object]:
    command = r"""
$tokens = $null
$errors = $null
$scriptPath = [Environment]::GetEnvironmentVariable("ORBITMIND_TEST_SCRIPT_PATH", "Process")
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) { throw "Build script has parser errors." }
$functionNames = @(
    "Get-CanonicalPath",
    "Test-PathEqual",
    "Test-StrictDescendant",
    "Assert-NoReparsePoint",
    "Assert-ExternalBuildRoot",
    "Assert-SafeExternalChildPath"
)
foreach ($name in $functionNames) {
    $definition = $ast.FindAll(
        {
            param($node)
            $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
                $node.Name -eq $name
        },
        $true
    ) | Select-Object -First 1
    if ($null -eq $definition) { throw "Missing path-contract function: $name" }
    Invoke-Expression $definition.Extent.Text
}
try {
    $repository = Get-CanonicalPath `
        -Path ([Environment]::GetEnvironmentVariable("ORBITMIND_TEST_REPOSITORY", "Process")) `
        -Label "Repository"
    $wheelhouseRoot = Get-CanonicalPath -Path $env:ORBITMIND_TEST_WHEELHOUSE -Label "Wheelhouse"
    $historicalBuild = Get-CanonicalPath `
        -Path (Join-Path $repository "build\u5.0b1") `
        -Label "Historical build"
    $historicalDist = Get-CanonicalPath `
        -Path (Join-Path $repository "dist\u5.0b1") `
        -Label "Historical dist"
    $historicalCandidate = Get-CanonicalPath `
        -Path (Join-Path $historicalDist "OrbitMind") `
        -Label "Historical candidate"
    $localAppData = Get-CanonicalPath -Path $env:LOCALAPPDATA -Label "LocalAppData"
    $historicalInstaller = Get-CanonicalPath `
        -Path (Join-Path $localAppData "OrbitMindBuild\U5.0I0") `
        -Label "Historical installer"
    $protected = @(
        $repository,
        $historicalBuild,
        $historicalDist,
        $historicalCandidate,
        $historicalInstaller
    )
    $external = Assert-ExternalBuildRoot `
        -Path $env:ORBITMIND_TEST_EXTERNAL_ROOT `
        -Repository $repository `
        -Wheelhouse $wheelhouseRoot `
        -ProtectedPaths $protected
    $venv = Assert-SafeExternalChildPath `
        -ExternalRoot $external `
        -Path (Join-Path $external ".venv-build-offline") `
        -ExpectedLeaf ".venv-build-offline" `
        -ProtectedPaths $protected
    $work = Assert-SafeExternalChildPath `
        -ExternalRoot $external `
        -Path (Join-Path $external "build") `
        -ExpectedLeaf "build" `
        -ProtectedPaths $protected
    $dist = Assert-SafeExternalChildPath `
        -ExternalRoot $external `
        -Path (Join-Path $external "candidate") `
        -ExpectedLeaf "candidate" `
        -ProtectedPaths $protected
    [ordered]@{
        success = $true
        external_root = $external
        build_venv = $venv
        work_path = $work
        dist_path = $dist
        candidate_path = Join-Path $dist "OrbitMind"
    } | ConvertTo-Json -Compress
}
catch {
    [ordered]@{
        success = $false
        error = $_.Exception.Message
    } | ConvertTo-Json -Compress
}
"""
    environment = os.environ.copy()
    environment.update(
        {
            "ORBITMIND_TEST_SCRIPT_PATH": str(BUILD_SCRIPT),
            "ORBITMIND_TEST_REPOSITORY": str(PROJECT_ROOT),
            "ORBITMIND_TEST_EXTERNAL_ROOT": external_root,
            "ORBITMIND_TEST_WHEELHOUSE": wheelhouse,
        }
    )
    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    return result


def _evaluate_canonical_path_rejection(path: str, label: str) -> dict[str, object]:
    command = r"""
$tokens = $null
$errors = $null
$scriptPath = [Environment]::GetEnvironmentVariable("ORBITMIND_TEST_SCRIPT_PATH", "Process")
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
    $scriptPath, [ref]$tokens, [ref]$errors
)
if (@($errors).Count -ne 0) { throw "Build script has parser errors." }
$definition = $ast.FindAll(
    {
        param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
            $node.Name -eq "Get-CanonicalPath"
    },
    $true
) | Select-Object -First 1
if ($null -eq $definition) { throw "Missing path-contract function: Get-CanonicalPath" }
Invoke-Expression $definition.Extent.Text
try {
    $canonical = Get-CanonicalPath `
        -Path $env:ORBITMIND_TEST_PATH_INPUT `
        -Label $env:ORBITMIND_TEST_PATH_LABEL
    [ordered]@{
        success = $true
        canonical = $canonical
    } | ConvertTo-Json -Compress
}
catch {
    [ordered]@{
        success = $false
        error = $_.Exception.Message
    } | ConvertTo-Json -Compress
}
"""
    environment = os.environ.copy()
    environment.update(
        {
            "ORBITMIND_TEST_SCRIPT_PATH": str(BUILD_SCRIPT),
            "ORBITMIND_TEST_PATH_INPUT": path,
            "ORBITMIND_TEST_PATH_LABEL": label,
        }
    )
    completed = subprocess.run(
        [
            _powershell_executable(),
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert isinstance(result, dict)
    return result


def test_lock_identity_and_shape() -> None:
    content = LOCK.read_bytes()
    text = content.decode("utf-8")
    assert hashlib.sha256(content).hexdigest() == EXPECTED_LOCK_HASH
    entries = re.findall(r"^([a-z0-9][a-z0-9._-]*)==([^ ]+) \\$", text, re.MULTILINE)
    hashes = re.findall(r"^    --hash=sha256:[0-9a-f]{64}$", text, re.MULTILINE)
    assert len(entries) == len(hashes) == 48
    assert [name for name, _ in entries] == sorted(name for name, _ in entries)
    assert not {"psycopg", "psycopg-binary", "qiskit", "qiskit-aer"} & {name for name, _ in entries}


def test_spec_is_one_folder_and_has_bounded_package_data() -> None:
    text = SPEC.read_text(encoding="utf-8")
    for required in (
        "alembic.ini",
        "migrations",
        "script.py.mako",
        "trajectory_replay.js",
        'collect_data_files("matplotlib")',
        "copy_metadata(distribution)",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "COLLECT(",
        "uac_admin=False",
        "upx=False",
    ):
        assert required in text
    for excluded in ("psycopg", "qiskit", "qiskit_aer", "pytest"):
        assert excluded in text
    assert "--onefile" not in text
    assert "C:\\Users\\" not in text
    assert str(PROJECT_ROOT) not in text


def test_spec_has_exact_bounded_migration_hidden_import() -> None:
    hidden_imports = _assigned_string_list("hiddenimports")
    migration_env_imports = _absolute_orbitmind_imports(PROJECT_ROOT / "migrations" / "env.py")
    exclusions = set(_analysis_string_list("excludes"))

    assert hidden_imports.count("orbitmind.persistence.research_models") == 1
    assert "orbitmind.persistence.research_models" in migration_env_imports
    assert not [item for item in hidden_imports if item.startswith("orbitmind.") and "*" in item]
    assert not [
        call
        for call in _orbitmind_collection_calls()
        if call[1] == "orbitmind" or (call[1] or "").startswith("orbitmind.")
    ]
    assert {"psycopg", "psycopg_binary", "qiskit", "qiskit_aer"} <= exclusions


def test_migration_environment_imports_match_reviewed_frozen_graph_boundary() -> None:
    migration_env = PROJECT_ROOT / "migrations" / "env.py"
    migration_env_imports = _absolute_orbitmind_imports(migration_env)
    hidden_imports = set(_assigned_string_list("hiddenimports"))

    assert migration_env_imports == (MIGRATION_NORMAL_ANALYSIS_IMPORTS | MIGRATION_HIDDEN_IMPORTS)
    assert hidden_imports & migration_env_imports == MIGRATION_HIDDEN_IMPORTS
    assert _spec_has_path_join("MIGRATIONS", "env.py")
    for module in migration_env_imports:
        source = PROJECT_ROOT / "src" / Path(*module.split(".")).with_suffix(".py")
        assert source.is_file()


def test_spec_paths_resolve_from_the_spec_directory() -> None:
    spec_dir = SPEC.parent.resolve()
    project_root = PROJECT_ROOT.resolve()
    paths = _evaluate_spec_paths(spec_dir)

    assert paths["SPEC_DIR"] == spec_dir
    assert paths["ROOT"] == project_root
    assert paths["SOURCE"] == project_root / "src"
    assert paths["MIGRATIONS"] == project_root / "migrations"
    assert paths["SAMPLES"] == project_root / "data" / "samples"
    assert paths["LAUNCHER"] == project_root / "src" / "orbitmind" / "runtime" / "launcher.py"
    assert paths["LAUNCHER"].is_file()
    assert paths["ROOT"] != spec_dir.parent.parent

    required_resources = (
        project_root / "alembic.ini",
        paths["MIGRATIONS"] / "env.py",
        paths["MIGRATIONS"] / "script.py.mako",
        project_root / "src" / "orbitmind" / "api" / "assets" / "trajectory_replay.js",
    )
    assert list((paths["MIGRATIONS"] / "versions").glob("*.py"))
    for resource in (*paths.values(), *required_resources):
        assert resource.resolve().is_relative_to(project_root)
        assert resource.exists()


def test_spec_includes_only_the_canonical_sample_catalog_and_fixture() -> None:
    samples_dir = (PROJECT_ROOT / "data" / "samples").resolve()
    catalog_path = samples_dir / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    fixtures = catalog["fixtures"]
    assert len(fixtures) == 1
    fixture_path = (samples_dir / fixtures[0]["file"]).resolve()
    assert fixture_path.is_relative_to(samples_dir)
    assert fixture_path.is_file()

    mappings = _explicit_data_mappings()
    sample_mappings = [
        (source.resolve(), destination)
        for source, destination in mappings
        if source.resolve().is_relative_to(samples_dir)
    ]
    assert sample_mappings == [
        (catalog_path, "data/samples"),
        (fixture_path, "data/samples"),
    ]
    assert sum(source.resolve() == catalog_path for source, _ in mappings) == 1
    assert sum(source.resolve() == fixture_path for source, _ in mappings) == 1

    tree = _spec_tree()
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Tree"
    ]
    assert not [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"glob", "rglob"}
        and any(isinstance(child, ast.Name) and child.id == "SAMPLES" for child in ast.walk(node))
    ]


def test_spec_path_preparation_fails_before_analysis_when_launcher_is_missing(
    tmp_path: Path,
) -> None:
    missing_spec_dir = tmp_path / "packaging"
    missing_spec_dir.mkdir()

    with pytest.raises(FileNotFoundError) as exc_info:
        _evaluate_spec_paths(missing_spec_dir)

    message = str(exc_info.value)
    assert message == "Required packaging source is missing: src/orbitmind/runtime/launcher.py"
    assert str(tmp_path) not in message


def test_build_script_is_offline_bounded_and_not_machine_specific() -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")
    for required in (
        "--no-index",
        "--find-links",
        "--require-hashes",
        "--no-deps",
        "PIP_NO_INDEX",
        EXPECTED_LOCK_HASH,
        "git_sha",
        "git_dirty",
        "frozen-output-sha256.txt",
        "orbitmind.spec",
    ):
        assert required in text
    assert "C:\\Users\\dell" not in text
    assert "%LOCALAPPDATA%\\OrbitMind" not in text


def test_build_script_parses_without_execution() -> None:
    assert _powershell_parse_errors(BUILD_SCRIPT) == []


def test_powershell_parser_capability_skip_is_narrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(shutil, "which", lambda _command: None)
    with pytest.raises(pytest.skip.Exception, match="PowerShell parser validation requires"):
        _powershell_executable()


def test_build_path_contract_rejects_posix_repository_path() -> None:
    result = _evaluate_canonical_path_rejection(
        str(PurePosixPath("/home/runner/work/orbitmind")),
        "Repository",
    )

    assert result["success"] is False
    assert "fully qualified Windows path" in str(result["error"])


@pytest.mark.parametrize(
    ("invalid_root", "error_fragment"),
    (
        (str(PurePosixPath("/tmp/orbitmind-build")), "fully qualified Windows path"),
        (r"relative\output", "fully qualified Windows path"),
        (r"C:\safe\..\escaped", "relative path segments"),
        ("", "nonempty absolute Windows path"),
    ),
)
def test_build_path_contract_rejects_portable_unsafe_roots_before_mutation(
    invalid_root: str,
    error_fragment: str,
    tmp_path: Path,
) -> None:
    before = tuple(tmp_path.rglob("*"))

    result = _evaluate_canonical_path_rejection(invalid_root, "ExternalBuildRoot")

    assert result["success"] is False
    assert error_fragment in str(result["error"])
    assert tuple(tmp_path.rglob("*")) == before
    for forbidden_leaf in (".venv-build-offline", "build", "candidate"):
        assert not (tmp_path / forbidden_leaf).exists()


@pytest.mark.skipif(os.name != "nt", reason=PHYSICAL_WINDOWS_PATH_SKIP_REASON)
def test_build_script_derives_all_packaging_paths_from_external_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    external_root = tmp_path / "U5.0I2D"
    external_root.mkdir()
    local_app_data = tmp_path / "LocalAppData"
    local_app_data.mkdir()
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    result = _evaluate_build_path_contract(
        str(external_root),
        str(tmp_path / "approved-wheelhouse"),
    )

    assert result["success"] is True
    assert external_root.is_absolute()
    assert external_root.drive
    assert not external_root.is_relative_to(PROJECT_ROOT)
    assert not external_root.is_symlink()
    expected_root = PureWindowsPath(external_root.resolve())
    assert PureWindowsPath(str(result["external_root"])) == expected_root
    assert PureWindowsPath(str(result["build_venv"])) == expected_root / ".venv-build-offline"
    assert PureWindowsPath(str(result["work_path"])) == expected_root / "build"
    assert PureWindowsPath(str(result["dist_path"])) == expected_root / "candidate"
    assert PureWindowsPath(str(result["candidate_path"])) == (
        expected_root / "candidate" / "OrbitMind"
    )
    assert (
        len(
            {
                str(result["build_venv"]).casefold(),
                str(result["work_path"]).casefold(),
                str(result["dist_path"]).casefold(),
            }
        )
        == 3
    )


@pytest.mark.skipif(os.name != "nt", reason=PHYSICAL_WINDOWS_PATH_SKIP_REASON)
def test_build_script_rejects_protected_windows_external_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    local_app_data = tmp_path / "LocalAppData"
    local_app_data.mkdir()
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    wheelhouse = str(tmp_path / "approved-wheelhouse")
    invalid_roots = (
        str(PROJECT_ROOT) + ".",
        rf"\\?\{PROJECT_ROOT}",
        PROJECT_ROOT.anchor,
        str(Path.home()),
        str(local_app_data),
        str(PROJECT_ROOT),
        str(PROJECT_ROOT / "src"),
        str(PROJECT_ROOT / "build"),
        str(PROJECT_ROOT / "dist"),
        str(PROJECT_ROOT / "dist" / "u5.0b1"),
        str(PROJECT_ROOT / "dist" / "u5.0b1" / "OrbitMind"),
        str(local_app_data / "OrbitMindBuild"),
        str(local_app_data / "OrbitMindBuild" / "U5.0I0"),
        wheelhouse,
        str(Path(wheelhouse) / "nested"),
    )

    for invalid_root in invalid_roots:
        result = _evaluate_build_path_contract(invalid_root, wheelhouse)
        assert result["success"] is False, invalid_root
        assert "ExternalBuildRoot" in str(result["error"]), invalid_root

    assert not (tmp_path / ".venv-build-offline").exists()
    assert not (tmp_path / "build").exists()
    assert not (tmp_path / "candidate").exists()


def test_build_script_revalidates_only_bounded_cleanup_targets() -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "$BuildVenv = Assert-SafeExternalChildPath `" in text
    assert "$BuildPath = Assert-SafeExternalChildPath `" in text
    assert "$DistPath = Assert-SafeExternalChildPath `" in text
    assert '$Path = Join-Path $ExternalRoot "build"' not in text
    assert '$Path = Join-Path $ExternalRoot "candidate"' not in text
    assert "[System.IO.FileAttributes]::ReparsePoint" in text
    assert 'throw "$Label must not be a reparse point or symbolic link."' in text
    assert text.count("Remove-Item -LiteralPath") == 1
    assert "Remove-Item -LiteralPath $safePath -Recurse -Force" in text
    cleanup = text[text.index("foreach ($generated in @(") : text.index("New-Item -ItemType")]
    for leaf in (".venv-build-offline", "build", "candidate"):
        assert f'Leaf = "{leaf}"' in cleanup
    assert "Assert-SafeExternalChildPath" in cleanup
    assert "$ExternalRoot" not in re.findall(r"Remove-Item[^\n]+", text)[0]
    assert "$HistoricalBuildPath" in text
    assert "$HistoricalDistPath" in text
    assert "$HistoricalCandidatePath" in text
    assert "$HistoricalInstallerRoot" in text


def test_build_script_propagates_external_paths_and_preserves_packaging_contract() -> None:
    text = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert re.search(
        r"\[Parameter\(Mandatory\s*=\s*\$true\)\]\s*\[string\]\$ExternalBuildRoot",
        text,
    )
    assert re.search(r"\$BuildVenv\s*=\s*Assert-SafeExternalChildPath", text)
    assert re.search(r"\$BuildPath\s*=\s*Assert-SafeExternalChildPath", text)
    assert re.search(r"\$DistPath\s*=\s*Assert-SafeExternalChildPath", text)
    assert "--workpath $BuildPath --distpath $DistPath $SpecPath" in text
    assert text.count("--workpath $BuildPath --distpath $DistPath $SpecPath") == 2
    assert 'Join-Path $RepositoryRoot "build\\u5.0b1"' in text
    assert 'Join-Path $RepositoryRoot "dist\\u5.0b1"' in text
    assert not re.search(r"\$BuildPath\s*=.*\$RepositoryRoot", text)
    assert not re.search(r"\$DistPath\s*=.*\$RepositoryRoot", text)
    path_validation = text.index("$ExternalRoot = Assert-ExternalBuildRoot")
    bounded_cleanup = text.index("foreach ($generated in @(")
    package_install = text.index("& $venvPython @installArgs")
    pyinstaller = text.index("& $venvPython -m PyInstaller")
    assert path_validation < bounded_cleanup < package_install < pyinstaller
    for required in (
        '$ExpectedPython = "3.12.10"',
        "--no-index",
        "--find-links",
        "--require-hashes",
        "--no-deps",
        "--no-cache-dir",
        '$env:PIP_NO_INDEX = "1"',
        EXPECTED_LOCK_HASH,
    ):
        assert required in text
    for forbidden in (
        "Invoke-WebRequest",
        "Start-BitsTransfer",
        "--index-url",
        "--extra-index-url",
        "pip install --upgrade",
        "Start-Process -Verb RunAs",
    ):
        assert forbidden not in text
    assert hashlib.sha256(SPEC.read_bytes()).hexdigest() == EXPECTED_SPEC_HASH


def test_verification_script_uses_injected_data_and_loopback_only() -> None:
    text = VERIFIER.read_text(encoding="utf-8")
    for required in (
        "$env:LOCALAPPDATA = $TempRoot",
        "http://127.0.0.1:$ReadyPort/health",
        "http://127.0.0.1:$ReadyPort/workbench",
        "http://127.0.0.1:$Port/assets/trajectory-replay.js",
        "Duplicate-launch guard",
        "Port-collision guard",
        "GenerateConsoleCtrlEvent",
        "external_network_observed",
    ):
        assert required in text
    assert "localhost" not in text.lower()
    assert "ORBITMIND_CUSTOM_TLE_HANDOFF_ENABLED" not in text
    assert "C:\\Users\\dell" not in text


def test_verifier_retains_the_create_process_native_handle() -> None:
    text = VERIFIER.read_text(encoding="utf-8")
    summary = _powershell_ast_summary(VERIFIER)
    csharp_match = re.search(
        r"Add-Type -TypeDefinition @'\n(?P<csharp>.*?)\n'@",
        text,
        re.DOTALL,
    )
    assert csharp_match is not None
    csharp = csharp_match.group("csharp")

    assert summary["errors"] == []
    assert {
        "Wait-OrbitMindNativeExit",
        "Assert-OrbitMindNativeExit",
        "Close-OrbitMindNativeHandle",
        "New-OrbitMindProcessEvidence",
    } <= set(summary["functions"])
    assert "public sealed class OrbitMindProcessHandle" in csharp
    assert "public IntPtr NativeProcessHandle" in csharp
    assert "public bool NativeHandleClosed" in csharp
    assert "public DateTime ProcessCreationTimeUtc" in csharp
    assert "public string Role" in csharp
    assert "CloseHandle(process.hThread)" in csharp
    assert "return new OrbitMindProcessHandle(" in csharp
    assert re.search(
        r"return new OrbitMindProcessHandle\(\s*"
        r"process\.dwProcessId,\s*managedProcess,\s*process\.hProcess,",
        csharp,
    )
    assert "return Process.GetProcessById(process.dwProcessId)" not in csharp


def test_verifier_uses_native_wait_and_exit_codes_for_every_process_role() -> None:
    text = VERIFIER.read_text(encoding="utf-8")
    summary = _powershell_ast_summary(VERIFIER)
    commands = summary["commands"]
    csharp_match = re.search(
        r"Add-Type -TypeDefinition @'\n(?P<csharp>.*?)\n'@",
        text,
        re.DOTALL,
    )
    assert csharp_match is not None
    csharp = csharp_match.group("csharp")

    for required in (
        "WaitForSingleObject",
        "GetExitCodeProcess",
        "WAIT_OBJECT_0 = 0x00000000",
        "WAIT_TIMEOUT = 0x00000102",
        "WAIT_FAILED = 0xFFFFFFFF",
        "STILL_ACTIVE = 259",
        "NativeExitCodeUInt32",
        "NativeExitCodeInt32",
        "unchecked((int)exitCode)",
    ):
        assert required in csharp
    assert commands.count("Wait-OrbitMindNativeExit") == 4
    assert commands.count("Assert-OrbitMindNativeExit") == 4
    assert commands.count("Close-OrbitMindNativeHandle") == 4
    for variable, code in (
        ("collisionWait", 21),
        ("duplicateWait", 20),
        ("firstShutdownWait", 0),
        ("secondShutdownWait", 0),
    ):
        assert re.search(
            rf"Assert-OrbitMindNativeExit\s+-Result\s+\${variable}\s+"
            rf"-ExpectedExitCode\s+{code}\b",
            text,
        )
    assert "Start-Process" not in text
    assert "$LASTEXITCODE" not in text
    assert not re.search(r"\$[A-Za-z_][A-Za-z0-9_]*\.ExitCode\b", text)
    assert "-not $runtime.WaitForExit(30000) -or $runtime.ExitCode -ne 0" not in text


def test_verifier_closes_native_handles_once_and_cleans_up_in_finally() -> None:
    text = VERIFIER.read_text(encoding="utf-8")
    csharp_match = re.search(
        r"Add-Type -TypeDefinition @'\n(?P<csharp>.*?)\n'@",
        text,
        re.DOTALL,
    )
    assert csharp_match is not None
    csharp = csharp_match.group("csharp")

    already_closed = csharp.index("if (process.NativeHandleClosed)")
    close_call = csharp.index("CloseHandle(process.NativeProcessHandle)")
    mark_closed = csharp.index("process.NativeHandleClosed = true")
    assert already_closed < close_call < mark_closed
    assert "AlreadyClosed = true" in csharp
    assert "process.NativeProcessHandle = IntPtr.Zero" in csharp
    assert "if (process.NativeProcessHandle == IntPtr.Zero)" in csharp
    assert "foreach ($processHandle in $processHandles)" in text
    assert "if ($null -eq $processHandle -or $processHandle.NativeHandleClosed)" in text
    assert "$cleanupClose = [OrbitMindProcessGroup]::CloseNativeHandle($processHandle)" in text
    assert "handle_close_success" in text
    assert "handle_already_closed" in text
    assert "handle_close_last_error" in text
    assert "build_windows_poc.ps1" not in text
    assert "PyInstaller" not in text


def test_verifier_hashes_persistence_only_while_the_runtime_is_stopped() -> None:
    text = VERIFIER.read_text(encoding="utf-8")
    persistence = text[text.index("$firstShutdownClose = Close-OrbitMindNativeHandle") :]

    first_close = persistence.index("$firstShutdownClose = Close-OrbitMindNativeHandle")
    baseline_release = persistence.index("$baselineDatabaseRelease = Test-OrbitMindDatabaseRelease")
    baseline_hash = persistence.index("$baselineDatabaseHash = (Get-FileHash")
    restart_start = persistence.index("$restart = [OrbitMindProcessGroup]::Start(")
    restart_ready = persistence.index("Wait-Workbench -ReadyPort $Port", restart_start)
    second_signal = persistence.index("[OrbitMindProcessGroup]::RequestStop($restart.ProcessId)")
    second_wait = persistence.index("$secondShutdownWait = Wait-OrbitMindNativeExit")
    second_assert = persistence.index(
        "Assert-OrbitMindNativeExit -Result $secondShutdownWait -ExpectedExitCode 0"
    )
    second_close = persistence.index("$secondShutdownClose = Close-OrbitMindNativeHandle")
    final_release = persistence.index("$finalDatabaseRelease = Test-OrbitMindDatabaseRelease")
    final_hash = persistence.index("$finalDatabaseHash = (Get-FileHash")
    hash_comparison = persistence.index("$finalDatabaseHash -ne $baselineDatabaseHash")

    assert (
        first_close
        < baseline_release
        < baseline_hash
        < restart_start
        < restart_ready
        < second_signal
        < second_wait
        < second_assert
        < second_close
        < final_release
        < final_hash
        < hash_comparison
    )
    assert "Get-FileHash" not in persistence[restart_start:second_close]
    assert persistence.count("Get-FileHash -LiteralPath $database") == 2
    assert "Move-Item -LiteralPath $DatabasePath -Destination $renameProbe" in text
    assert "Move-Item -LiteralPath $renameProbe -Destination $DatabasePath" in text
    assert 'throw "User data changed unexpectedly across restart."' in text
    assert "Copy-Item" not in persistence
    assert "Start-Sleep" not in persistence[restart_start:final_hash]


def test_verifier_serializes_the_complete_native_result_matrix() -> None:
    text = VERIFIER.read_text(encoding="utf-8")
    summary = _powershell_ast_summary(VERIFIER)

    assert summary["errors"] == []
    assert "Write-OrbitMindProcessResult" in summary["functions"]
    for role, expected in (
        ("collision", 21),
        ("duplicate", 20),
        ("primary_shutdown", 0),
        ("restart_shutdown", 0),
    ):
        assert re.search(
            rf"New-OrbitMindProcessEvidence\s+`.*?"
            rf'-Role\s+"{role}"\s+`.*?'
            rf"-ExpectedExitCode\s+{expected}\b",
            text,
            re.DOTALL,
        )
    assert text.count("Write-OrbitMindProcessResult -Evidence") == 4
    for field in (
        "native_exit_code_uint32",
        "native_exit_code_int32",
        "handle_closed",
        "expected_exit_code",
        "assertion_passed",
    ):
        assert field in text
    assert (
        "orbitmind_process_result role={0} pid={1} wait={2} exit_uint32={3} "
        "exit_int32={4} handle_closed={5} expected={6} passed={7}"
    ) in text
    output_function = text[
        text.index("function Write-OrbitMindProcessResult") : text.index(
            "function Test-OrbitMindDatabaseRelease"
        )
    ]
    assert "NativeProcessHandle" not in output_function
    assert not re.search(r"\$[A-Za-z_][A-Za-z0-9_]*\.ExitCode\b", text)
    assert "$LASTEXITCODE" not in text


def test_verification_script_uses_the_application_replay_asset_route() -> None:
    verifier = VERIFIER.read_text(encoding="utf-8")
    workbench_path = PROJECT_ROOT / "src" / "orbitmind" / "api" / "routers" / "workbench.py"
    workbench = workbench_path.read_text(encoding="utf-8")
    workbench_tree = ast.parse(workbench, filename=str(workbench_path))

    route_constants = [
        ast.literal_eval(node.value)
        for node in workbench_tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "REPLAY_CONTROLLER_ASSET_PATH"
            for target in node.targets
        )
    ]
    assert route_constants == ["/assets/trajectory-replay.js"]
    canonical_route = route_constants[0]

    decorated_routes: list[str] = []
    for node in workbench_tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "get"
                and decorator.args
            ):
                route = ast.literal_eval(decorator.args[0])
                if isinstance(route, str):
                    decorated_routes.append(route)
    assert canonical_route in decorated_routes

    request = re.search(
        r"\$asset\s*=\s*Invoke-WebRequest\s+-Uri\s+"
        r'"http://127\.0\.0\.1:\$Port(?P<route>/[^"]+)"',
        verifier,
    )
    assert request is not None
    assert request.group("route") == canonical_route
    assert verifier.count(canonical_route) == 1
    assert "/workbench/assets/trajectory_replay.js" not in verifier
    assert "/workbench/assets/" not in request.group("route")
    assert "trajectory_replay.js" not in request.group("route")

    replay_check = verifier[request.end() : request.end() + 160]
    assert re.search(r"if \(\$asset\.StatusCode -ne 200\)", replay_check)


def test_application_replay_asset_contract_remains_non_empty_javascript() -> None:
    workbench_path = PROJECT_ROOT / "src" / "orbitmind" / "api" / "routers" / "workbench.py"
    workbench_tree = ast.parse(
        workbench_path.read_text(encoding="utf-8"), filename=str(workbench_path)
    )
    handler = next(
        node
        for node in workbench_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "trajectory_replay_controller_asset"
    )
    media_types = {
        ast.literal_eval(keyword.value)
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "media_type" and isinstance(keyword.value, ast.Constant)
    }
    assert "application/javascript; charset=utf-8" in media_types
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "read_text"
        for node in ast.walk(handler)
    )

    asset = PROJECT_ROOT / "src" / "orbitmind" / "api" / "assets" / "trajectory_replay.js"
    body = asset.read_text(encoding="utf-8")
    assert body.strip()
    assert "trajectory-replay-display-v1" in body


def test_no_generated_packaging_output_is_tracked() -> None:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    forbidden_suffixes = (".exe", ".dll", ".pyd", ".whl", ".sqlite", ".sqlite3", ".log")
    assert not [
        line for line in completed.stdout.splitlines() if line.lower().endswith(forbidden_suffixes)
    ]
