"""Composition root for the bounded Windows local runtime."""

from __future__ import annotations

import sys
import threading
import webbrowser
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from fastapi import FastAPI

from orbitmind.runtime.configuration import (
    RuntimeConfiguration,
    build_runtime_configuration,
    parse_launcher_arguments,
)
from orbitmind.runtime.database import preflight_sqlite
from orbitmind.runtime.paths import RuntimePaths
from orbitmind.runtime.server import (
    ManagedUvicornServer,
    acquire_loopback_socket,
    wait_until_ready,
)
from orbitmind.runtime.status import (
    ExitCode,
    ReasonCode,
    RuntimeFailure,
    RuntimeState,
    StatusReporter,
)
from orbitmind.runtime.windows import NativeWindowsRuntime, WindowsRuntime

_SHUTDOWN_TIMEOUT_SECONDS = 15.0


@dataclass
class LauncherServices:
    """Injectable effects; production defaults remain narrow and local."""

    windows: WindowsRuntime
    paths_factory: Callable[[], RuntimePaths]
    browser_open: Callable[[str], bool]
    stop_event: threading.Event
    reporter: StatusReporter
    confirm_migration: Callable[[str], bool]
    readiness_timeout_seconds: float = 30.0

    @classmethod
    def production(cls) -> LauncherServices:
        return cls(
            windows=NativeWindowsRuntime(),
            paths_factory=RuntimePaths.from_local_app_data,
            browser_open=lambda url: bool(webbrowser.open(url, new=2)),
            stop_event=threading.Event(),
            reporter=StatusReporter(),
            confirm_migration=_confirm_migration,
        )


def _confirm_migration(revision: str) -> bool:
    del revision
    try:
        answer = input("A verified database backup is required before migration. Continue? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() == "y"


def _build_application(configuration: RuntimeConfiguration) -> FastAPI:
    # This is the sole runtime-to-API composition boundary. Importing here avoids
    # constructing the source-mode module-level app before packaged settings exist.
    from orbitmind.api.app import create_app
    from orbitmind.api.container import AppContainer
    from orbitmind.camera.runtime import CameraMediaRuntimeContext

    camera_runtime_context = (
        CameraMediaRuntimeContext.production(configuration.runtime_paths.temp_dir)
        if configuration.runtime_paths is not None
        else None
    )
    return create_app(
        AppContainer(
            settings=configuration.settings,
            camera_runtime_context=camera_runtime_context,
        )
    )


def run_launcher(
    arguments: Sequence[str],
    *,
    services: LauncherServices | None = None,
) -> ExitCode:
    active = services
    if active is None:
        try:
            active = LauncherServices.production()
        except RuntimeFailure as failure:
            StatusReporter().emit(RuntimeState.FAILED, reason=failure.reason)
            return failure.code

    reporter = active.reporter
    reporter.emit(RuntimeState.STARTING)
    mutex = None
    console_handler = None
    owned_socket = None
    backend: ManagedUvicornServer | None = None
    configuration: RuntimeConfiguration | None = None
    final_code = ExitCode.SUCCESS
    try:
        active.windows.validate_environment()
        reporter.emit(RuntimeState.VALIDATING_CONFIGURATION)
        parsed = parse_launcher_arguments(list(arguments))
        paths = active.paths_factory()
        configuration = build_runtime_configuration(paths, parsed)
        mutex = active.windows.acquire_mutex()
        owned_socket = acquire_loopback_socket(configuration.port)
        paths.prepare()
        reporter.emit(RuntimeState.CHECKING_DATABASE, port=configuration.port)
        preflight_sqlite(
            paths,
            configuration.settings.database_url,
            confirm_migration=active.confirm_migration,
        )
        application = _build_application(configuration)
        reporter.emit(RuntimeState.STARTING_BACKEND, port=configuration.port)
        backend = ManagedUvicornServer(application, owned_socket)
        console_handler = active.windows.register_console_handler(active.stop_event)
        backend.start()
        base_url = f"http://127.0.0.1:{configuration.port}"
        if not wait_until_ready(
            base_url,
            backend,
            timeout_seconds=active.readiness_timeout_seconds,
            stop_event=active.stop_event,
        ):
            if backend.failure is not None:
                raise RuntimeFailure(ExitCode.BACKEND_FAILURE, ReasonCode.BACKEND_FAILURE)
            raise RuntimeFailure(ExitCode.READINESS_TIMEOUT, ReasonCode.READINESS_TIMEOUT)
        reporter.emit(
            RuntimeState.READY,
            port=configuration.port,
            url=configuration.workbench_url,
        )
        if configuration.open_browser:
            active.browser_open(configuration.workbench_url)
        while not active.stop_event.wait(0.1):
            if backend.failure is not None or not backend.thread.is_alive():
                raise RuntimeFailure(ExitCode.BACKEND_FAILURE, ReasonCode.BACKEND_FAILURE)
    except RuntimeFailure as failure:
        final_code = failure.code
        if failure.reason is ReasonCode.PORT_COLLISION and configuration is not None:
            reporter.emit(
                RuntimeState.FAILED,
                port=configuration.port,
                reason=failure.reason,
            )
            reporter.emit_port_collision_guidance(configuration.port)
        else:
            reporter.emit(RuntimeState.FAILED, reason=failure.reason)
    except Exception:
        final_code = ExitCode.BACKEND_FAILURE
        reporter.emit(RuntimeState.FAILED, reason=ReasonCode.BACKEND_FAILURE)
    finally:
        if backend is not None:
            reporter.emit(RuntimeState.STOPPING)
            backend.request_stop()
            if not backend.join(_SHUTDOWN_TIMEOUT_SECONDS):
                final_code = ExitCode.BACKEND_FAILURE
                reporter.emit(RuntimeState.FAILED, reason=ReasonCode.SHUTDOWN_TIMEOUT)
        if console_handler is not None:
            console_handler.unregister()
        if owned_socket is not None:
            owned_socket.close()
        if mutex is not None:
            mutex.release()
        reporter.emit(RuntimeState.STOPPED)
    return final_code


def main(arguments: Sequence[str] | None = None) -> int:
    return int(run_launcher(sys.argv[1:] if arguments is None else arguments))


if __name__ == "__main__":
    raise SystemExit(main())
