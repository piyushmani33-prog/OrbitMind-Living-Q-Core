"""Focused tests for the bounded U5.0B1 Windows runtime source."""

from __future__ import annotations

import ctypes
import gc
import hashlib
import json
import os
import socket
import sqlite3
import sys
import threading
from collections.abc import Iterator
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.script import ScriptDirectory

from orbitmind.core.errors import StorageError
from orbitmind.runtime import database as runtime_database
from orbitmind.runtime import launcher as runtime_launcher
from orbitmind.runtime import windows as runtime_windows
from orbitmind.runtime.configuration import (
    LauncherArguments,
    PortConfigurationSource,
    RuntimeConfiguration,
    build_runtime_configuration,
    parse_launcher_arguments,
)
from orbitmind.runtime.database import (
    ALEMBIC_HEAD,
    MigrationResources,
    preflight_sqlite,
)
from orbitmind.runtime.launcher import LauncherServices, run_launcher
from orbitmind.runtime.paths import RuntimePaths
from orbitmind.runtime.server import LOOPBACK_HOST, acquire_loopback_socket
from orbitmind.runtime.status import (
    ExitCode,
    ReasonCode,
    RuntimeFailure,
    RuntimeState,
    StatusReporter,
)
from orbitmind.runtime.windows import FakeMutex, NativeWindowsRuntime
from orbitmind.sources import registry as source_registry
from orbitmind.sources.registry import SourceRegistry


@pytest.fixture(autouse=True)
def _clear_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in tuple(os.environ):
        if name.startswith("ORBITMIND_"):
            monkeypatch.delenv(name, raising=False)
    yield


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths(tmp_path / "OrbitMind")
    paths.prepare()
    return paths


def _copy_sample_files(samples_dir: Path) -> None:
    samples_dir.mkdir(parents=True)
    for name in ("catalog.json", "iss_zarya.tle"):
        source = source_registry.DEFAULT_SAMPLES_DIR / name
        (samples_dir / name).write_bytes(source.read_bytes())


def test_source_registry_source_default_and_sample_content_are_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    registry = SourceRegistry()

    assert registry._dir == source_registry.DEFAULT_SAMPLES_DIR
    assert registry.supported_satellite_ids() == {"ISS", "25544"}
    assert registry.get_tle("ISS") == (
        "1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991",
        "2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482",
    )
    fixture = source_registry.DEFAULT_SAMPLES_DIR / "iss_zarya.tle"
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "e20e7db3f19c0ebb5c2d2a10a425fa8440b61452773f35b4ba19c47184576214"
    )


def test_source_registry_explicit_directory_remains_authoritative_when_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    samples_dir = tmp_path / "explicit-samples"
    _copy_sample_files(samples_dir)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    registry = SourceRegistry(samples_dir)

    assert registry._dir == samples_dir
    assert registry.get_tle("ISS") == SourceRegistry(source_registry.DEFAULT_SAMPLES_DIR).get_tle(
        "ISS"
    )


def test_source_registry_frozen_default_uses_only_meipass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle_root = tmp_path / "bundle-root"
    samples_dir = bundle_root / "data" / "samples"
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    _copy_sample_files(samples_dir)
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle_root), raising=False)
    monkeypatch.setattr(sys, "executable", str(unrelated / "OrbitMind.exe"))
    monkeypatch.setattr(
        socket,
        "create_connection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network attempted")),
    )

    registry = SourceRegistry()

    assert registry._dir == samples_dir
    assert registry.get_tle("ISS") == SourceRegistry(source_registry.DEFAULT_SAMPLES_DIR).get_tle(
        "ISS"
    )
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*") if path.is_file()} == {
        Path("bundle-root/data/samples/catalog.json"),
        Path("bundle-root/data/samples/iss_zarya.tle"),
    }


@pytest.mark.parametrize("meipass", [None, "missing", "empty"])
def test_source_registry_frozen_default_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    meipass: str | None,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.chdir(source_registry.PROJECT_ROOT)
    monkeypatch.setattr(sys, "executable", str(source_registry.PROJECT_ROOT / "OrbitMind.exe"))
    if meipass is None:
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    elif meipass == "empty":
        empty_root = tmp_path / "empty-bundle"
        empty_root.mkdir()
        monkeypatch.setattr(sys, "_MEIPASS", str(empty_root), raising=False)
    else:
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / meipass), raising=False)

    with pytest.raises(StorageError, match=r"^sample catalog is missing$"):
        SourceRegistry()


def test_runtime_paths_create_only_injected_tree(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    expected = {
        "config",
        "data",
        "projects",
        "artifacts",
        "cache",
        "logs",
        "runtime",
        "backups",
        "temp",
    }
    assert {path.name for path in paths.root.iterdir()} == expected
    assert paths.database_file == paths.root / "data" / "orbitmind.db"
    assert paths.config_file == paths.root / "config" / "config.json"
    assert not (tmp_path / ".orbitmind-write-probe").exists()


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "[]",
        '{"config_schema_version": 2}',
        '{"config_schema_version": 1, "unknown": true}',
        '{"config_schema_version": 1, "port": "8000"}',
        '{"config_schema_version": 1, "port": true}',
        '{"config_schema_version": 1, "port": false}',
        '{"config_schema_version": 1, "port": null}',
        '{"config_schema_version": 1, "port": 8010.0}',
        '{"config_schema_version": 1, "port": 1023}',
        '{"config_schema_version": 1, "port": 65536}',
        '{"config_schema_version": 1, "open_browser": 1}',
    ],
)
def test_runtime_config_rejects_malformed_unknown_and_wrong_types(
    tmp_path: Path, payload: str
) -> None:
    paths = _paths(tmp_path)
    paths.config_file.write_text(payload, encoding="utf-8")
    with pytest.raises(RuntimeFailure) as caught:
        build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert caught.value.code is ExitCode.INVALID_CONFIGURATION


def test_runtime_config_precedence_and_settings_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.config_file.write_text(
        json.dumps(
            {
                "config_schema_version": 1,
                "port": 8100,
                "open_browser": True,
                "custom_tle_handoff_enabled": True,
                "log_level": "WARNING",
                "log_json": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", "8200")
    configuration = build_runtime_configuration(
        paths, parse_launcher_arguments(["--port", "8300", "--no-browser"])
    )
    assert configuration.port == 8300
    assert configuration.port_source is PortConfigurationSource.COMMAND_LINE
    assert configuration.settings.custom_tle_handoff_port == 8300
    assert configuration.settings.custom_tle_handoff_enabled is True
    assert configuration.settings.api_bind_host == "127.0.0.1"
    assert configuration.settings.api_workers == 1
    assert configuration.settings.api_reload_enabled is False
    assert configuration.settings.forwarded_header_trust_enabled is False
    assert configuration.settings.database_url.startswith("sqlite:///")
    assert configuration.open_browser is False
    assert configuration.workbench_url == "http://127.0.0.1:8300/workbench"


def test_runtime_port_configuration_sources_are_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)

    default = build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert default.port == 8000
    assert default.port_source is PortConfigurationSource.DEFAULT

    paths.config_file.write_text('{"config_schema_version": 1, "port": 8100}', encoding="utf-8")
    json_selected = build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert json_selected.port == 8100
    assert json_selected.port_source is PortConfigurationSource.JSON

    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", "8200")
    environment_selected = build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert environment_selected.port == 8200
    assert environment_selected.port_source is PortConfigurationSource.ENVIRONMENT

    command_line_selected = build_runtime_configuration(
        paths, parse_launcher_arguments(["--port", "8300"])
    )
    assert command_line_selected.port == 8300
    assert command_line_selected.port_source is PortConfigurationSource.COMMAND_LINE


@pytest.mark.parametrize("port", [1024, 8000, 8010, 8999, 65535])
def test_command_line_port_bounds_are_accepted(tmp_path: Path, port: int) -> None:
    configuration = build_runtime_configuration(
        _paths(tmp_path), parse_launcher_arguments(["--port", str(port)])
    )
    assert configuration.port == port
    assert configuration.port_source is PortConfigurationSource.COMMAND_LINE


@pytest.mark.parametrize("port", [1024, 65535])
def test_json_and_environment_port_bounds_are_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, port: int
) -> None:
    paths = _paths(tmp_path)
    paths.config_file.write_text(
        json.dumps({"config_schema_version": 1, "port": port}), encoding="utf-8"
    )
    json_selected = build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert json_selected.port == port
    assert json_selected.port_source is PortConfigurationSource.JSON

    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", str(port))
    environment_selected = build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert environment_selected.port == port
    assert environment_selected.port_source is PortConfigurationSource.ENVIRONMENT


@pytest.mark.parametrize(
    "arguments",
    [
        ["--port"],
        ["--port", ""],
        ["--port", " "],
        ["--port", "abc"],
        ["--port", "0"],
        ["--port", "-1"],
        ["--port", "1"],
        ["--port", "1023"],
        ["--port", "65536"],
        ["--port", "8010.0"],
        ["--port", "http://127.0.0.1:8010"],
        ["--port", "127.0.0.1:8010"],
        ["--port", "8010,8011"],
        ["--port", "+8010"],
        ["--port", "\u0668\u0660\u0661\u0660"],
        ["--port", "8010", "--port", "8011"],
    ],
)
def test_launcher_arguments_reject_invalid_and_duplicate_ports(arguments: list[str]) -> None:
    with pytest.raises(RuntimeFailure) as caught:
        parse_launcher_arguments(arguments)
    assert caught.value.code is ExitCode.INVALID_CONFIGURATION


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "abc",
        "true",
        "false",
        "8010.0",
        "0",
        "1023",
        "65536",
        "http://127.0.0.1:8010",
        "127.0.0.1:8010",
        "8010,8011",
        "+8010",
        "\u0668\u0660\u0661\u0660",
    ],
)
def test_environment_port_rejects_invalid_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", value)
    with pytest.raises(RuntimeFailure) as caught:
        build_runtime_configuration(_paths(tmp_path), parse_launcher_arguments([]))
    assert caught.value.code is ExitCode.INVALID_CONFIGURATION


def test_invalid_higher_precedence_port_does_not_fall_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    paths.config_file.write_text('{"config_schema_version": 1, "port": 8100}', encoding="utf-8")
    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", "8200")
    with pytest.raises(RuntimeFailure) as command_line_error:
        parse_launcher_arguments(["--port", "65536"])
    assert command_line_error.value.code is ExitCode.INVALID_CONFIGURATION

    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", "65536")
    with pytest.raises(RuntimeFailure) as environment_error:
        build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert environment_error.value.code is ExitCode.INVALID_CONFIGURATION


def test_runtime_port_configuration_is_immutable_after_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", "8010")
    configuration = build_runtime_configuration(_paths(tmp_path), parse_launcher_arguments([]))
    with pytest.raises(FrozenInstanceError):
        configuration.port = 8020
    with pytest.raises(FrozenInstanceError):
        configuration.port_source = PortConfigurationSource.JSON

    monkeypatch.setenv("ORBITMIND_CUSTOM_TLE_HANDOFF_PORT", "8020")
    assert configuration.port == 8010
    assert configuration.port_source is PortConfigurationSource.ENVIRONMENT


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("ORBITMIND_API_BIND_HOST", "localhost"),
        ("ORBITMIND_API_WORKERS", "2"),
        ("ORBITMIND_API_RELOAD_ENABLED", "true"),
        ("ORBITMIND_FORWARDED_HEADER_TRUST_ENABLED", "true"),
        ("ORBITMIND_DATABASE_URL", "postgresql://example.invalid/orbitmind"),
        ("ORBITMIND_NETWORK_ENABLED", "true"),
    ],
)
def test_runtime_config_rejects_packaged_boundary_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, value: str
) -> None:
    paths = _paths(tmp_path)
    monkeypatch.setenv(name, value)
    with pytest.raises(RuntimeFailure) as caught:
        build_runtime_configuration(paths, parse_launcher_arguments([]))
    assert caught.value.code is ExitCode.INVALID_CONFIGURATION


@pytest.mark.parametrize("arguments", [["--port", "1023"], ["--host", "127.0.0.1"], ["x"]])
def test_launcher_arguments_are_bounded(arguments: list[str]) -> None:
    with pytest.raises(RuntimeFailure) as caught:
        parse_launcher_arguments(arguments)
    assert caught.value.code is ExitCode.INVALID_CONFIGURATION


def test_platform_gate_rejects_os_architecture_and_elevation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    native = object.__new__(NativeWindowsRuntime)
    monkeypatch.setattr(runtime_windows, "_is_windows_runtime", lambda: True)
    monkeypatch.delattr(sys, "getwindowsversion", raising=False)
    monkeypatch.setattr(
        sys,
        "getwindowsversion",
        lambda: SimpleNamespace(major=9),
        raising=False,
    )
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    monkeypatch.setattr(native, "_is_elevated", lambda: False)
    with pytest.raises(RuntimeFailure) as old_os:
        native.validate_environment()
    assert old_os.value.code is ExitCode.UNSUPPORTED_ENVIRONMENT

    monkeypatch.setattr(
        sys,
        "getwindowsversion",
        lambda: SimpleNamespace(major=10),
        raising=False,
    )
    monkeypatch.setattr("platform.machine", lambda: "ARM64")
    with pytest.raises(RuntimeFailure):
        native.validate_environment()
    monkeypatch.setattr("platform.machine", lambda: "AMD64")
    monkeypatch.setattr(native, "_is_elevated", lambda: True)
    with pytest.raises(RuntimeFailure):
        native.validate_environment()


class _FakeKernel32:
    def __init__(self, *, already_exists: bool = False) -> None:
        self.already_exists = already_exists
        self.created_name: str | None = None
        self.closed: list[int] = []
        self.released: list[int] = []
        self.local_freed = 0

    def CreateMutexW(self, attributes: object, initial_owner: bool, name: str) -> int:
        del attributes
        assert initial_owner is True
        self.created_name = name
        ctypes.set_last_error(183 if self.already_exists else 0)
        return 456

    def CloseHandle(self, handle: int) -> None:
        self.closed.append(handle)

    def ReleaseMutex(self, handle: int) -> None:
        self.released.append(handle)

    def LocalFree(self, descriptor: object) -> None:
        del descriptor
        self.local_freed += 1


class _FakeAdvapi32:
    def ConvertStringSecurityDescriptorToSecurityDescriptorW(
        self, sddl: str, revision: int, descriptor: object, size: object
    ) -> int:
        del size
        assert revision == 1
        assert "S-1-5-21-test" in sddl
        ctypes.cast(descriptor, ctypes.POINTER(ctypes.c_void_p)).contents.value = 123
        return 1


def _native_with_fake_apis(kernel: _FakeKernel32) -> NativeWindowsRuntime:
    native = object.__new__(NativeWindowsRuntime)
    native._kernel32 = kernel  # type: ignore[attr-defined]
    native._advapi32 = _FakeAdvapi32()  # type: ignore[attr-defined]
    native._current_user_sid = lambda: "S-1-5-21-test"  # type: ignore[method-assign]
    return native


def _enable_complete_fake_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    last_error = 0

    def set_last_error(value: int) -> None:
        nonlocal last_error
        last_error = value

    def get_last_error() -> int:
        return last_error

    monkeypatch.setattr(runtime_windows, "_is_windows_runtime", lambda: True)
    monkeypatch.setattr(ctypes, "set_last_error", set_last_error, raising=False)
    monkeypatch.setattr(ctypes, "get_last_error", get_last_error, raising=False)


def test_incomplete_fake_windows_environment_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _FakeKernel32()
    monkeypatch.setattr(runtime_windows, "_is_windows_runtime", lambda: False)
    with pytest.raises(RuntimeFailure) as caught:
        _native_with_fake_apis(kernel).acquire_mutex()
    assert caught.value.code is ExitCode.UNSUPPORTED_ENVIRONMENT
    assert kernel.created_name is None


def test_sid_mutex_name_release_and_native_resource_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _FakeKernel32()
    _enable_complete_fake_windows(monkeypatch)
    mutex = _native_with_fake_apis(kernel).acquire_mutex()
    assert kernel.created_name == "Global\\OrbitMind.U5.0B0.Runtime.v1.S-1-5-21-test"
    assert kernel.local_freed == 1
    mutex.release()
    mutex.release()
    assert kernel.released == [456]
    assert kernel.closed == [456]


def test_sid_mutex_duplicate_closes_handle_and_exits_20(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kernel = _FakeKernel32(already_exists=True)
    _enable_complete_fake_windows(monkeypatch)
    with pytest.raises(RuntimeFailure) as caught:
        _native_with_fake_apis(kernel).acquire_mutex()
    assert caught.value.code is ExitCode.SINGLE_INSTANCE_CONFLICT
    assert kernel.closed == [456]
    assert kernel.local_freed == 1


def test_loopback_socket_owns_exact_endpoint_and_collision_has_no_fallback() -> None:
    owned = acquire_loopback_socket(0)
    try:
        host, port = owned.getsockname()
        assert host == LOOPBACK_HOST
        with pytest.raises(RuntimeFailure) as caught:
            acquire_loopback_socket(port)
        assert caught.value.code is ExitCode.PORT_COLLISION
    finally:
        owned.close()


def _create_database_at_parent_revision(paths: RuntimePaths) -> str:
    resources = MigrationResources.discover()
    database_url = f"sqlite:///{paths.database_file.as_posix()}"
    config = runtime_database._alembic_config(database_url, resources)
    script = ScriptDirectory.from_config(config)
    head = script.get_revision(ALEMBIC_HEAD)
    assert head is not None and isinstance(head.down_revision, str)
    parent = head.down_revision
    command.upgrade(config, parent)
    del config
    gc.collect()
    return parent


def test_sqlite_first_run_uses_migrations_and_releases_file(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    url = f"sqlite:///{paths.database_file.as_posix()}"
    assert preflight_sqlite(paths, url) is None
    with closing(sqlite3.connect(paths.database_file)) as connection:
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        journal = connection.execute("PRAGMA journal_mode").fetchone()
    assert revision == (ALEMBIC_HEAD,)
    assert journal is not None and str(journal[0]).lower() != "wal"
    paths.database_file.unlink()
    assert not paths.database_file.exists()


def test_sqlite_integrity_and_newer_revision_fail_closed(tmp_path: Path) -> None:
    corrupt_paths = _paths(tmp_path / "corrupt")
    corrupt_paths.database_file.write_bytes(b"not sqlite")
    with pytest.raises(RuntimeFailure) as corrupt:
        preflight_sqlite(corrupt_paths, f"sqlite:///{corrupt_paths.database_file.as_posix()}")
    assert corrupt.value.code is ExitCode.DATABASE_CORRUPTION

    newer_paths = _paths(tmp_path / "newer")
    url = f"sqlite:///{newer_paths.database_file.as_posix()}"
    preflight_sqlite(newer_paths, url)
    with closing(sqlite3.connect(newer_paths.database_file)) as connection:
        connection.execute("UPDATE alembic_version SET version_num = 'future_revision'")
        connection.commit()
    with pytest.raises(RuntimeFailure) as newer:
        preflight_sqlite(newer_paths, url)
    assert newer.value.code is ExitCode.DATABASE_CORRUPTION


def test_sqlite_known_revision_creates_verified_backup_before_migration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    parent = _create_database_at_parent_revision(paths)
    url = f"sqlite:///{paths.database_file.as_posix()}"
    backup = preflight_sqlite(
        paths,
        url,
        confirm_migration=lambda revision: revision == parent,
        now=lambda: datetime(2026, 7, 13, 12, 0, tzinfo=UTC),
    )
    assert backup == paths.backups_dir / "orbitmind-20260713T120000Z-pre-migration.sqlite3"
    assert backup.is_file()
    with closing(sqlite3.connect(paths.database_file)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
            ALEMBIC_HEAD,
        )
    with closing(sqlite3.connect(backup)) as connection:
        assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (parent,)


def test_sqlite_migration_failure_preserves_original_and_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _paths(tmp_path)
    parent = _create_database_at_parent_revision(paths)
    url = f"sqlite:///{paths.database_file.as_posix()}"
    monkeypatch.setattr(
        runtime_database,
        "_upgrade",
        lambda config: (_ for _ in ()).throw(RuntimeError()),
    )
    with pytest.raises(RuntimeFailure) as caught:
        preflight_sqlite(paths, url, confirm_migration=lambda revision: revision == parent)
    assert caught.value.code is ExitCode.MIGRATION_FAILURE
    assert paths.database_file.is_file()
    assert len(tuple(paths.backups_dir.glob("*.sqlite3"))) == 1


class _FakeConsoleHandler:
    def __init__(self) -> None:
        self.unregistered = False

    def unregister(self) -> None:
        self.unregistered = True


class _FakeWindows:
    def __init__(self, order: list[str] | None = None) -> None:
        self.validated = False
        self.acquire_calls = 0
        self.mutex = FakeMutex()
        self.handler = _FakeConsoleHandler()
        self.order = order

    def validate_environment(self) -> None:
        self.validated = True
        if self.order is not None:
            self.order.append("validate_environment")

    def acquire_mutex(self) -> FakeMutex:
        self.acquire_calls += 1
        if self.order is not None:
            self.order.append("mutex")
        return self.mutex

    def register_console_handler(self, stop_event: threading.Event) -> _FakeConsoleHandler:
        del stop_event
        return self.handler


class _FakeSocket:
    def __init__(self) -> None:
        self.closed = False
        self.close_calls = 0

    def close(self) -> None:
        self.closed = True
        self.close_calls += 1


class _FakeThread:
    def __init__(self) -> None:
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive


class _FakeBackend:
    def __init__(
        self,
        app: object,
        owned_socket: object,
        *,
        join_result: bool = True,
        order: list[str] | None = None,
    ) -> None:
        del app, owned_socket
        self.failure: BaseException | None = None
        self.thread = _FakeThread()
        self.started = False
        self.stopped = False
        self.join_result = join_result
        self.order = order

    def start(self) -> None:
        self.started = True
        if self.order is not None:
            self.order.append("backend_start")

    def request_stop(self) -> None:
        self.stopped = True
        self.thread.alive = False
        if self.order is not None:
            self.order.append("backend_stop")

    def join(self, timeout: float) -> bool:
        del timeout
        if self.order is not None:
            self.order.append("backend_join")
        return self.join_result


def _launcher_services(tmp_path: Path, events: list[str], *, stop: bool = True) -> LauncherServices:
    stop_event = threading.Event()
    if stop:
        stop_event.set()
    return LauncherServices(
        windows=_FakeWindows(),
        paths_factory=lambda: RuntimePaths(tmp_path / "OrbitMind"),
        browser_open=lambda url: events.append(f"browser:{url}") is None,
        stop_event=stop_event,
        reporter=StatusReporter(write=events.append),
        confirm_migration=lambda revision: False,
        readiness_timeout_seconds=0.1,
    )


def test_duplicate_port_rejection_prevents_runtime_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    path_factory_calls: list[str] = []

    def paths_factory() -> RuntimePaths:
        path_factory_calls.append("called")
        return RuntimePaths(tmp_path / "unexpected")

    def unexpected_runtime_work(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("invalid port input reached runtime initialization")

    services.paths_factory = paths_factory
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", unexpected_runtime_work)
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", unexpected_runtime_work)
    monkeypatch.setattr(runtime_launcher, "_build_application", unexpected_runtime_work)

    result = run_launcher(["--port", "8010", "--port", "8011"], services=services)

    assert result is ExitCode.INVALID_CONFIGURATION
    assert path_factory_calls == []
    assert not any(event.startswith("browser:") for event in events)
    assert services.windows.acquire_calls == 0  # type: ignore[union-attr]
    assert not services.windows.mutex.released  # type: ignore[union-attr]
    assert any(ReasonCode.INVALID_CONFIGURATION.value in event for event in events)
    assert not any("availability is not checked" in event for event in events)


@pytest.mark.parametrize(
    ("arguments", "selected_port"),
    [([], 8000), (["--port", "8010"], 8010)],
)
def test_launcher_orders_selected_port_before_persistent_runtime_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    selected_port: int,
) -> None:
    events: list[str] = []
    order: list[str] = []
    services = _launcher_services(tmp_path, events)
    services.windows = _FakeWindows(order)
    paths = RuntimePaths(tmp_path / "OrbitMind")
    fake_socket = _FakeSocket()
    backend = _FakeBackend(object(), fake_socket, order=order)
    original_parse = runtime_launcher.parse_launcher_arguments
    original_configuration = runtime_launcher.build_runtime_configuration
    original_prepare = RuntimePaths.prepare

    def traced_parse(raw_arguments: list[str]) -> LauncherArguments:
        order.append("parse_arguments")
        return original_parse(raw_arguments)

    def paths_factory() -> RuntimePaths:
        order.append("paths_factory")
        return paths

    def traced_configuration(
        runtime_paths: RuntimePaths, launcher_arguments: LauncherArguments
    ) -> RuntimeConfiguration:
        order.append("configuration")
        return original_configuration(runtime_paths, launcher_arguments)

    def traced_prepare(runtime_paths: RuntimePaths) -> None:
        if runtime_paths == paths:
            order.append("paths_prepare")
        original_prepare(runtime_paths)

    def reserve_socket(port: int) -> _FakeSocket:
        assert port == selected_port
        order.append(f"socket:{port}")
        return fake_socket

    def database_preflight(
        runtime_paths: RuntimePaths,
        database_url: str,
        **kwargs: object,
    ) -> None:
        del kwargs
        assert runtime_paths == paths
        assert database_url == f"sqlite:///{paths.database_file.as_posix()}"
        order.append("database_preflight")

    def build_application(configuration: RuntimeConfiguration) -> object:
        assert configuration.port == selected_port
        order.append("application")
        return object()

    def build_backend(application: object, owned_socket: object) -> _FakeBackend:
        del application
        assert owned_socket is fake_socket
        order.append("backend")
        return backend

    def wait_for_readiness(base_url: str, active_backend: _FakeBackend, **kwargs: object) -> bool:
        del kwargs
        assert active_backend is backend
        order.append(f"readiness:{base_url}")
        return True

    services.paths_factory = paths_factory
    services.browser_open = lambda url: order.append(f"browser:{url}") is None
    monkeypatch.setattr(runtime_launcher, "parse_launcher_arguments", traced_parse)
    monkeypatch.setattr(runtime_launcher, "build_runtime_configuration", traced_configuration)
    monkeypatch.setattr(RuntimePaths, "prepare", traced_prepare)
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", reserve_socket)
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", database_preflight)
    monkeypatch.setattr(runtime_launcher, "_build_application", build_application)
    monkeypatch.setattr(runtime_launcher, "ManagedUvicornServer", build_backend)
    monkeypatch.setattr(runtime_launcher, "wait_until_ready", wait_for_readiness)

    result = run_launcher(arguments, services=services)

    expected_url = f"http://127.0.0.1:{selected_port}"
    assert result is ExitCode.SUCCESS
    assert order == [
        "validate_environment",
        "parse_arguments",
        "paths_factory",
        "configuration",
        "mutex",
        f"socket:{selected_port}",
        "paths_prepare",
        "database_preflight",
        "application",
        "backend",
        "backend_start",
        f"readiness:{expected_url}",
        f"browser:{expected_url}/workbench",
        "backend_stop",
        "backend_join",
    ]
    assert fake_socket.close_calls == 1
    assert services.windows.mutex.released  # type: ignore[union-attr]


def test_launcher_collision_precedes_database_and_persistent_path_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    mutex_released = False

    class _ReacquirableWindows(_FakeWindows):
        def __init__(self) -> None:
            super().__init__()
            self.held = False

        def acquire_mutex(self) -> FakeMutex:
            nonlocal mutex_released
            self.acquire_calls += 1
            if self.held:
                raise RuntimeFailure(
                    ExitCode.SINGLE_INSTANCE_CONFLICT,
                    ReasonCode.SINGLE_INSTANCE_CONFLICT,
                )
            self.held = True

            def release() -> None:
                nonlocal mutex_released
                mutex_released = True
                self.held = False

            return FakeMutex(on_release=release)

    windows = _ReacquirableWindows()
    services.windows = windows
    paths = RuntimePaths(tmp_path / "fresh" / "OrbitMind")
    services.paths_factory = lambda: paths
    database_calls: list[str] = []
    application_calls: list[str] = []

    def unexpected_database(*args: object, **kwargs: object) -> None:
        del args, kwargs
        database_calls.append("database")
        pytest.fail("port collision reached database preflight")

    def unexpected_application(*args: object, **kwargs: object) -> object:
        del args, kwargs
        application_calls.append("application")
        pytest.fail("port collision constructed an application")

    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", unexpected_database)
    monkeypatch.setattr(runtime_launcher, "_build_application", unexpected_application)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupying_socket:
        occupying_socket.bind((LOOPBACK_HOST, 0))
        occupying_socket.listen(socket.SOMAXCONN)
        port = int(occupying_socket.getsockname()[1])

        result = run_launcher(["--port", str(port), "--no-browser"], services=services)

        assert result is ExitCode.PORT_COLLISION
        assert occupying_socket.fileno() != -1
        assert occupying_socket.getsockname() == (LOOPBACK_HOST, port)

    assert database_calls == []
    assert application_calls == []
    assert not paths.root.exists()
    assert not any(paths.root.rglob("orbitmind.db*"))
    assert not any(event.startswith("browser:") for event in events)
    rendered = "\n".join(events)
    example_port = 8011 if port == 8010 else 8010
    assert f"failed | port={port} | reason=port_collision" in rendered
    assert f"local port {port} is already in use" in rendered
    assert "did not stop or take over the other local application" in rendered
    assert "Choose another unused local port and start OrbitMind explicitly" in rendered
    assert "Example only; availability is not checked" in rendered
    assert f"OrbitMind.exe --port {example_port}" in rendered
    assert "Traceback" not in rendered
    assert "LocalAppData" not in rendered
    assert "PID" not in rendered
    assert mutex_released
    assert not windows.held
    reacquired = windows.acquire_mutex()
    reacquired.release()
    assert mutex_released


@pytest.mark.parametrize(
    ("arguments", "selected_port", "example_port"),
    [([], 8000, 8010), (["--port", "8010"], 8010, 8011), (["--port", "8500"], 8500, 8010)],
)
def test_launcher_collision_guidance_uses_only_the_resolved_port(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    selected_port: int,
    example_port: int,
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    paths = RuntimePaths(tmp_path / "fresh" / "OrbitMind")
    services.paths_factory = lambda: paths

    def collision(port: int) -> _FakeSocket:
        assert port == selected_port
        raise RuntimeFailure(ExitCode.PORT_COLLISION, ReasonCode.PORT_COLLISION)

    def unexpected_runtime_work(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("collision guidance reached persistent runtime work")

    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", collision)
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", unexpected_runtime_work)
    monkeypatch.setattr(runtime_launcher, "_build_application", unexpected_runtime_work)

    result = run_launcher([*arguments, "--no-browser"], services=services)

    rendered = "\n".join(events)
    assert result is ExitCode.PORT_COLLISION
    assert f"failed | port={selected_port} | reason=port_collision" in rendered
    assert f"local port {selected_port} is already in use" in rendered
    assert "did not stop or take over the other local application" in rendered
    assert "Choose another unused local port and start OrbitMind explicitly" in rendered
    assert "Example only; availability is not checked" in rendered
    assert f"OrbitMind.exe --port {example_port}" in rendered
    assert f"OrbitMind.exe --port {selected_port}" not in rendered
    assert not paths.root.exists()
    assert not any(event.startswith("browser:") for event in events)
    assert services.windows.mutex.released  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("selected_port", "example_port"),
    [(8000, 8010), (8010, 8011), (8500, 8010)],
)
def test_port_collision_guidance_is_bounded_and_frozen_safe(
    selected_port: int, example_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines: list[str] = []
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    StatusReporter(write=lines.append).emit_port_collision_guidance(selected_port)

    rendered = "\n".join(lines)
    assert f"local port {selected_port} is already in use" in rendered
    assert "did not stop or take over the other local application" in rendered
    assert "Choose another unused local port and start OrbitMind explicitly" in rendered
    assert "Example only; availability is not checked" in rendered
    assert f"OrbitMind.exe --port {example_port}" in rendered
    assert "Traceback" not in rendered
    assert "LocalAppData" not in rendered
    assert "C:\\" not in rendered
    assert "PID" not in rendered
    assert all(len(line) < 100 for line in lines)


def test_port_collision_guidance_does_not_add_port_owner_inspection() -> None:
    source = "\n".join(
        (
            Path(runtime_launcher.__file__).read_text(encoding="utf-8"),
            Path(runtime_launcher.__file__).with_name("status.py").read_text(encoding="utf-8"),
        )
    )

    forbidden = (
        "psutil",
        "Get-NetTCPConnection",
        "netstat",
        "tasklist",
        "Win32_Process",
        "GetExtendedTcpTable",
    )
    assert not any(marker in source for marker in forbidden)


def test_launcher_database_failure_releases_reserved_port_and_mutex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((LOOPBACK_HOST, 0))
        port = int(probe.getsockname()[1])

    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    paths = RuntimePaths(tmp_path / "OrbitMind")
    services.paths_factory = lambda: paths
    reserved_ports: list[int] = []
    application_calls: list[str] = []
    original_reservation = runtime_launcher.acquire_loopback_socket

    def reserve_socket(selected_port: int) -> socket.socket:
        reserved_ports.append(selected_port)
        return original_reservation(selected_port)

    def fail_database(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeFailure(ExitCode.MIGRATION_FAILURE, ReasonCode.MIGRATION_FAILURE)

    def unexpected_application(*args: object, **kwargs: object) -> object:
        del args, kwargs
        application_calls.append("application")
        pytest.fail("database failure constructed an application")

    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", reserve_socket)
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", fail_database)
    monkeypatch.setattr(runtime_launcher, "_build_application", unexpected_application)

    result = run_launcher(["--port", str(port), "--no-browser"], services=services)

    assert result is ExitCode.MIGRATION_FAILURE
    assert reserved_ports == [port]
    assert paths.root.is_dir()
    assert not paths.database_file.exists()
    assert application_calls == []
    assert not any(event.startswith("browser:") for event in events)
    assert services.windows.mutex.released  # type: ignore[union-attr]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as rebound_socket:
        rebound_socket.bind((LOOPBACK_HOST, port))


def test_launcher_backend_start_failure_releases_socket_and_mutex(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    fake_socket = _FakeSocket()
    backend = _FakeBackend(object(), fake_socket)
    preflight_calls: list[str] = []

    def fail_start() -> None:
        backend.started = True
        raise RuntimeError("backend start failure")

    monkeypatch.setattr(
        runtime_launcher,
        "preflight_sqlite",
        lambda *args, **kwargs: preflight_calls.append("database"),
    )
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", lambda port: fake_socket)
    monkeypatch.setattr(runtime_launcher, "_build_application", lambda configuration: object())
    monkeypatch.setattr(runtime_launcher, "ManagedUvicornServer", lambda app, sock: backend)
    monkeypatch.setattr(backend, "start", fail_start)

    result = run_launcher(["--no-browser"], services=services)

    assert result is ExitCode.BACKEND_FAILURE
    assert preflight_calls == ["database"]
    assert backend.started and backend.stopped
    assert fake_socket.close_calls == 1
    assert services.windows.mutex.released  # type: ignore[union-attr]
    assert not any(event.startswith("browser:") for event in events)


def test_duplicate_instance_prevents_socket_and_database_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    paths_factory_calls: list[str] = []

    class _DuplicateWindows(_FakeWindows):
        def acquire_mutex(self) -> FakeMutex:
            self.acquire_calls += 1
            raise RuntimeFailure(
                ExitCode.SINGLE_INSTANCE_CONFLICT, ReasonCode.SINGLE_INSTANCE_CONFLICT
            )

    def unexpected_runtime_work(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail("duplicate instance reached runtime ownership work")

    def paths_factory() -> RuntimePaths:
        paths_factory_calls.append("paths")
        return RuntimePaths(tmp_path / "OrbitMind")

    services.windows = _DuplicateWindows()
    services.paths_factory = paths_factory
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", unexpected_runtime_work)
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", unexpected_runtime_work)
    monkeypatch.setattr(runtime_launcher, "_build_application", unexpected_runtime_work)

    result = run_launcher(["--no-browser"], services=services)

    assert result is ExitCode.SINGLE_INSTANCE_CONFLICT
    assert paths_factory_calls == ["paths"]
    assert services.windows.acquire_calls == 1  # type: ignore[union-attr]
    assert not services.windows.mutex.released  # type: ignore[union-attr]
    assert not any(event.startswith("browser:") for event in events)
    assert not any("availability is not checked" in event for event in events)


def test_launcher_status_readiness_browser_and_clean_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    fake_socket = _FakeSocket()
    backend = _FakeBackend(object(), fake_socket)
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", lambda port: fake_socket)
    monkeypatch.setattr(runtime_launcher, "_build_application", lambda configuration: object())
    monkeypatch.setattr(runtime_launcher, "ManagedUvicornServer", lambda app, sock: backend)
    monkeypatch.setattr(runtime_launcher, "wait_until_ready", lambda *args, **kwargs: True)
    result = run_launcher(["--port", "8123"], services=services)
    assert result is ExitCode.SUCCESS
    joined = "\n".join(events)
    assert joined.index(RuntimeState.STARTING.value) < joined.index(RuntimeState.READY.value)
    assert "browser:http://127.0.0.1:8123/workbench" in events
    assert backend.started and backend.stopped
    assert fake_socket.closed
    assert services.windows.mutex.released  # type: ignore[union-attr]
    assert services.windows.handler.unregistered  # type: ignore[union-attr]


def test_launcher_no_browser_readiness_timeout_and_shutdown_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path, events)
    fake_socket = _FakeSocket()
    backend = _FakeBackend(object(), fake_socket)
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", lambda port: fake_socket)
    monkeypatch.setattr(runtime_launcher, "_build_application", lambda configuration: object())
    monkeypatch.setattr(runtime_launcher, "ManagedUvicornServer", lambda app, sock: backend)
    monkeypatch.setattr(runtime_launcher, "wait_until_ready", lambda *args, **kwargs: False)
    result = run_launcher(["--no-browser"], services=services)
    assert result is ExitCode.READINESS_TIMEOUT
    assert not any(event.startswith("browser:") for event in events)
    assert backend.started and backend.stopped
    assert fake_socket.close_calls == 1
    assert services.windows.mutex.released  # type: ignore[union-attr]
    assert services.windows.handler.unregistered  # type: ignore[union-attr]

    backend.join_result = False
    result = run_launcher(["--no-browser"], services=services)
    assert result is ExitCode.BACKEND_FAILURE
    assert any(ReasonCode.SHUTDOWN_TIMEOUT.value in event for event in events)


def test_status_reporter_never_renders_arbitrary_exception_text() -> None:
    lines: list[str] = []
    StatusReporter(write=lines.append).emit(
        RuntimeState.FAILED, reason=ReasonCode.INVALID_CONFIGURATION
    )
    assert lines == ["OrbitMind 0.1.0 | failed | reason=invalid_configuration"]
    assert "Traceback" not in lines[0]


def _run_launcher_with_application_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> tuple[ExitCode, list[str], LauncherServices, _FakeSocket]:
    events: list[str] = []
    services = _launcher_services(tmp_path / "runtime", events)
    fake_socket = _FakeSocket()

    def raise_application_failure(configuration: object) -> object:
        hidden_frame_local = "frame-local-must-not-be-recorded"
        del configuration, hidden_frame_local
        raise failure

    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", lambda port: fake_socket)
    monkeypatch.setattr(runtime_launcher, "_build_application", raise_application_failure)
    result = run_launcher(["--no-browser"], services=services)
    return result, events, services, fake_socket


@pytest.mark.parametrize("frozen", [False, True])
def test_application_failure_stays_sanitized_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    frozen: bool,
) -> None:
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setenv("OM_U5B1_FROZEN_DIAGNOSTIC", "1")
    result, events, services, fake_socket = _run_launcher_with_application_failure(
        tmp_path, monkeypatch, RuntimeError("private backend failure")
    )
    rendered = "\n".join(events)

    assert result is ExitCode.BACKEND_FAILURE
    assert int(result) == 50
    assert "reason=backend_failure" in rendered
    assert "private backend failure" not in rendered
    assert "RuntimeError" not in rendered
    assert "Traceback" not in rendered
    assert "availability is not checked" not in rendered
    assert capsys.readouterr() == ("", "")
    assert {path.name for path in tmp_path.iterdir()} == {"runtime"}
    assert fake_socket.closed
    assert services.windows.mutex.released  # type: ignore[union-attr]


def test_successful_launch_ignores_former_diagnostic_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    services = _launcher_services(tmp_path / "runtime", events)
    fake_socket = _FakeSocket()
    backend = _FakeBackend(object(), fake_socket)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("OM_U5B1_FROZEN_DIAGNOSTIC", "1")
    monkeypatch.setattr(runtime_launcher, "preflight_sqlite", lambda *args, **kwargs: None)
    monkeypatch.setattr(runtime_launcher, "acquire_loopback_socket", lambda port: fake_socket)
    monkeypatch.setattr(runtime_launcher, "_build_application", lambda configuration: object())
    monkeypatch.setattr(runtime_launcher, "ManagedUvicornServer", lambda app, sock: backend)
    monkeypatch.setattr(runtime_launcher, "wait_until_ready", lambda *args, **kwargs: True)
    assert run_launcher(["--no-browser"], services=services) is ExitCode.SUCCESS
    assert {path.name for path in tmp_path.iterdir()} == {"runtime"}
    assert fake_socket.closed
    assert services.windows.mutex.released  # type: ignore[union-attr]


def test_launcher_source_contains_no_temporary_diagnostic_sink() -> None:
    launcher_source = Path(runtime_launcher.__file__).read_text(encoding="utf-8")
    forbidden = (
        "OM_U5B1_FROZEN_DIAGNOSTIC",
        "orbitmind-frozen-backend-diagnostic.json",
        "u5.0b1-frozen-backend",
        "diagnostic_schema_version",
        "diagnostic_scope",
        "TracebackException",
        "capture_locals",
        "originating_traceback_frames",
    )
    assert not any(marker in launcher_source for marker in forbidden)
