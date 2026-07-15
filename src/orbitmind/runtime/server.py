"""Owned loopback socket, managed Uvicorn thread, and readiness probes."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

import uvicorn
from fastapi import FastAPI

from orbitmind.runtime.status import ExitCode, ReasonCode, RuntimeFailure

LOOPBACK_HOST = "127.0.0.1"


def acquire_loopback_socket(port: int) -> socket.socket:
    owned = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            owned.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        owned.bind((LOOPBACK_HOST, port))
        owned.listen(socket.SOMAXCONN)
    except OSError as exc:
        owned.close()
        raise RuntimeFailure(ExitCode.PORT_COLLISION, ReasonCode.PORT_COLLISION) from exc
    return owned


@dataclass
class ManagedUvicornServer:
    app: FastAPI
    owned_socket: socket.socket
    server: uvicorn.Server = field(init=False)
    thread: threading.Thread = field(init=False)
    failure: BaseException | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        config = uvicorn.Config(
            self.app,
            host=LOOPBACK_HOST,
            workers=1,
            reload=False,
            proxy_headers=False,
            log_config=None,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self._run, name="orbitmind-backend", daemon=False)

    def _run(self) -> None:
        try:
            self.server.run(sockets=[self.owned_socket])
        except BaseException as exc:  # retained for the launcher; never rendered directly
            self.failure = exc

    def start(self) -> None:
        self.thread.start()

    def request_stop(self) -> None:
        self.server.should_exit = True

    def join(self, timeout: float) -> bool:
        self.thread.join(timeout)
        return not self.thread.is_alive()


def _read_local(url: str) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=1.0) as response:
        return response.status, response.headers.get_content_type(), response.read(1_048_577)


def wait_until_ready(
    base_url: str,
    backend: ManagedUvicornServer,
    *,
    timeout_seconds: float = 30.0,
    stop_event: threading.Event | None = None,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if backend.failure is not None or not backend.thread.is_alive():
            return False
        if stop_event is not None and stop_event.is_set():
            return False
        try:
            health_status, health_type, health_body = _read_local(f"{base_url}/health")
            health = json.loads(health_body)
            workbench_status, workbench_type, workbench_body = _read_local(f"{base_url}/workbench")
            if (
                health_status == 200
                and health_type == "application/json"
                and isinstance(health, dict)
                and health.get("status") == "ok"
                and health.get("database") == "connected"
                and workbench_status == 200
                and workbench_type == "text/html"
                and workbench_body
            ):
                return True
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            pass
        time.sleep(0.05)
    return False
