"""Bounded launcher states, reason codes, and console reporting."""

from __future__ import annotations

from collections.abc import Callable
from enum import IntEnum, StrEnum

from orbitmind import __version__


class ExitCode(IntEnum):
    """Stable local-runtime process exit codes."""

    SUCCESS = 0
    INVALID_CONFIGURATION = 10
    SINGLE_INSTANCE_CONFLICT = 20
    PORT_COLLISION = 21
    DATABASE_CORRUPTION = 30
    MIGRATION_FAILURE = 31
    MIGRATION_GRAPH_INVALID = 32
    SCHEMA_UNRECOGNISED = 33
    READINESS_TIMEOUT = 40
    BACKEND_FAILURE = 50
    UNSUPPORTED_ENVIRONMENT = 60


class RuntimeState(StrEnum):
    """Operator-visible launcher states."""

    STARTING = "starting"
    VALIDATING_CONFIGURATION = "validating configuration"
    CHECKING_DATABASE = "checking database"
    STARTING_BACKEND = "starting backend"
    READY = "ready"
    FAILED = "failed"
    STOPPING = "stopping"
    STOPPED = "stopped"


class ReasonCode(StrEnum):
    """Sanitized launcher failure reasons."""

    INVALID_CONFIGURATION = "invalid_configuration"
    UNSUPPORTED_ENVIRONMENT = "unsupported_environment"
    SINGLE_INSTANCE_CONFLICT = "single_instance_conflict"
    PORT_COLLISION = "port_collision"
    DATABASE_CORRUPTION = "database_corruption"
    MIGRATION_FAILURE = "migration_failure"
    MIGRATION_GRAPH_INVALID = "migration_graph_invalid"
    SCHEMA_UNRECOGNISED = "schema_unrecognised"
    READINESS_TIMEOUT = "readiness_timeout"
    BACKEND_FAILURE = "backend_failure"
    SHUTDOWN_TIMEOUT = "shutdown_timeout"


class RuntimeFailure(Exception):
    """A launcher failure safe to map to a fixed reason and exit code."""

    def __init__(self, code: ExitCode, reason: ReasonCode) -> None:
        self.code = code
        self.reason = reason
        super().__init__(reason.value)


class StatusReporter:
    """Print only bounded lifecycle facts; never arbitrary exception text."""

    def __init__(self, *, write: Callable[[str], None] = print) -> None:
        self._write = write

    def emit(
        self,
        state: RuntimeState,
        *,
        port: int | None = None,
        url: str | None = None,
        reason: ReasonCode | None = None,
    ) -> None:
        fields = [f"OrbitMind {__version__}", state.value]
        if port is not None:
            fields.append(f"port={port}")
        if url is not None:
            fields.append(f"workbench={url}")
        if reason is not None:
            fields.append(f"reason={reason.value}")
        self._write(" | ".join(fields))

    def emit_port_collision_guidance(self, selected_port: int) -> None:
        """Render bounded local guidance without inspecting the port owner."""

        example_port = 8011 if selected_port == 8010 else 8010
        prefix = f"OrbitMind {__version__}"
        for message in (
            f"could not start because local port {selected_port} is already in use.",
            "OrbitMind did not stop or take over the other local application.",
            "Choose another unused local port and start OrbitMind explicitly.",
            "Example only; availability is not checked.",
            f"OrbitMind.exe --port {example_port}",
        ):
            self._write(f"{prefix} | {message}")
