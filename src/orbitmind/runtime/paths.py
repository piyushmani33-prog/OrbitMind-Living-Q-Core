"""User-scoped writable paths for the packaged local runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from orbitmind.runtime.status import ExitCode, ReasonCode, RuntimeFailure

_SUBDIRECTORIES = (
    "config",
    "data",
    "projects",
    "artifacts",
    "cache",
    "logs",
    "runtime",
    "backups",
    "temp",
)


@dataclass(frozen=True)
class RuntimePaths:
    """Deterministic paths rooted outside the read-only application bundle."""

    root: Path

    @classmethod
    def from_local_app_data(cls, *, injected_root: Path | None = None) -> RuntimePaths:
        if injected_root is not None:
            return cls(injected_root.resolve())
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            raise RuntimeFailure(ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION)
        return cls((Path(local_app_data) / "OrbitMind").resolve())

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def projects_dir(self) -> Path:
        return self.root / "projects"

    @property
    def artifacts_dir(self) -> Path:
        return self.root / "artifacts"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def backups_dir(self) -> Path:
        return self.root / "backups"

    @property
    def temp_dir(self) -> Path:
        return self.root / "temp"

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def database_file(self) -> Path:
        return self.data_dir / "orbitmind.db"

    @property
    def runtime_marker(self) -> Path:
        return self.runtime_dir / "runtime.json"

    def prepare(self) -> None:
        """Create the approved tree and fail closed if it is not writable."""

        try:
            self.root.mkdir(parents=True, exist_ok=True)
            for name in _SUBDIRECTORIES:
                path = self.root / name
                path.mkdir(exist_ok=True)
                if not path.is_dir():
                    raise OSError
            probe = self.temp_dir / ".orbitmind-write-probe"
            probe.write_bytes(b"ok")
            probe.unlink()
        except OSError as exc:
            raise RuntimeFailure(
                ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION
            ) from exc
