"""Windows-only bounded source integration for the local runtime launcher."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import urllib.request
from collections.abc import Iterator
from pathlib import Path

import pytest

from orbitmind.runtime.launcher import LauncherServices, run_launcher
from orbitmind.runtime.paths import RuntimePaths
from orbitmind.runtime.status import ExitCode, RuntimeState, StatusReporter
from orbitmind.runtime.windows import FakeMutex


class _ConsoleHandler:
    def unregister(self) -> None:
        return None


class _WindowsBoundary:
    def __init__(self) -> None:
        self.mutexes: list[FakeMutex] = []

    def validate_environment(self) -> None:
        return None

    def acquire_mutex(self) -> FakeMutex:
        mutex = FakeMutex()
        self.mutexes.append(mutex)
        return mutex

    def register_console_handler(self, stop_event: threading.Event) -> _ConsoleHandler:
        del stop_event
        return _ConsoleHandler()


@pytest.fixture(autouse=True)
def _clear_runtime_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in tuple(os.environ):
        if name.startswith("ORBITMIND_"):
            monkeypatch.delenv(name, raising=False)
    yield


@pytest.mark.integration
@pytest.mark.skipif(sys.platform != "win32", reason="Windows local-runtime spike")
def test_windows_launcher_reaches_ready_and_stops_without_real_profile(tmp_path: Path) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])

    stop_event = threading.Event()
    ready_event = threading.Event()
    lines: list[str] = []

    def record(line: str) -> None:
        lines.append(line)
        if RuntimeState.READY.value in line:
            ready_event.set()

    paths = RuntimePaths(tmp_path / "OrbitMind")
    windows = _WindowsBoundary()
    services = LauncherServices(
        windows=windows,
        paths_factory=lambda: paths,
        browser_open=lambda url: (_ for _ in ()).throw(AssertionError(url)),
        stop_event=stop_event,
        reporter=StatusReporter(write=record),
        confirm_migration=lambda revision: False,
        readiness_timeout_seconds=30.0,
    )
    result: list[ExitCode] = []
    launcher = threading.Thread(
        target=lambda: result.append(
            run_launcher(["--port", str(port), "--no-browser"], services=services)
        ),
        daemon=False,
    )
    launcher.start()
    assert ready_event.wait(45.0), "launcher did not reach ready"

    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2.0) as response:
        health = json.loads(response.read())
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/workbench", timeout=2.0) as response:
        workbench = response.read()
    assert health["status"] == "ok"
    assert health["database"] == "connected"
    assert b"Mission Workbench" in workbench

    stop_event.set()
    launcher.join(30.0)
    assert not launcher.is_alive()
    assert result == [ExitCode.SUCCESS]
    assert paths.database_file.is_file()
    assert paths.config_dir.is_dir()
    assert paths.artifacts_dir.is_dir()
    assert any("http://127.0.0.1:" in line for line in lines)
    assert not any("localhost" in line for line in lines)
    assert windows.mutexes and windows.mutexes[0].released
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as rebound_socket:
        rebound_socket.bind(("127.0.0.1", port))
