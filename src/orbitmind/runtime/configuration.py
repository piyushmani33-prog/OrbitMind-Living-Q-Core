"""Strict packaged-runtime JSON and Settings adapter."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Never

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from orbitmind.core.config import Settings
from orbitmind.runtime.paths import RuntimePaths
from orbitmind.runtime.status import ExitCode, ReasonCode, RuntimeFailure

_DEFAULT_PORT = 8000
_MIN_PORT = 1024
_MAX_PORT = 65535
_PORT_ENVIRONMENT_VARIABLE = "ORBITMIND_CUSTOM_TLE_HANDOFF_PORT"


class PortConfigurationSource(StrEnum):
    """Sanitized authority that selected the packaged runtime port."""

    DEFAULT = "default"
    COMMAND_LINE = "command_line"
    ENVIRONMENT = "environment"
    JSON = "json"


def _validate_port(value: object) -> int:
    """Parse one strict decimal or integer port without coercion."""

    if type(value) is int:
        port = value
    elif isinstance(value, str) and value.isascii() and value.isdecimal():
        port = int(value, 10)
    else:
        raise ValueError("invalid port")
    if not _MIN_PORT <= port <= _MAX_PORT:
        raise ValueError("port is outside the approved range")
    return port


class _EnvironmentWithoutRuntimePort(PydanticBaseSettingsSource):
    """Leave port precedence to the explicit runtime contract below."""

    def __init__(self, source: PydanticBaseSettingsSource) -> None:
        super().__init__(source.settings_cls)
        self._source = source

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return self._source.get_field_value(field, field_name)

    def __call__(self) -> dict[str, Any]:
        values = self._source()
        values.pop("custom_tle_handoff_port", None)
        return values


class _PackagedSettings(Settings):
    """Settings with environment values above launcher-provided JSON defaults."""

    model_config = SettingsConfigDict(env_prefix="ORBITMIND_", extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        del settings_cls, dotenv_settings
        return _EnvironmentWithoutRuntimePort(env_settings), init_settings, file_secret_settings


class UserRuntimeConfig(BaseModel):
    """Strict user-facing allowlist, separate from the full Settings surface."""

    model_config = ConfigDict(extra="forbid", validate_default=True)

    config_schema_version: StrictInt = 1
    port: StrictInt = _DEFAULT_PORT
    open_browser: StrictBool = True
    custom_tle_handoff_enabled: StrictBool = False
    log_level: StrictStr = "INFO"
    log_json: StrictBool = False

    _ALLOWED_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "config_schema_version",
            "port",
            "open_browser",
            "custom_tle_handoff_enabled",
            "log_level",
            "log_json",
        }
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, value: int) -> int:
        return _validate_port(value)


@dataclass(frozen=True)
class LauncherArguments:
    port: int | None
    no_browser: bool


@dataclass(frozen=True)
class RuntimeConfiguration:
    settings: Settings
    port: int
    port_source: PortConfigurationSource
    open_browser: bool

    @property
    def workbench_url(self) -> str:
        return f"http://127.0.0.1:{self.port}/workbench"


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        del message
        raise RuntimeFailure(ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION)


def parse_launcher_arguments(arguments: list[str]) -> LauncherArguments:
    parser = _ArgumentParser(add_help=True, allow_abbrev=False)
    parser.add_argument("--port", action="append")
    parser.add_argument("--no-browser", action="store_true")
    namespace = parser.parse_args(arguments)
    raw_ports = namespace.port
    try:
        if raw_ports is None:
            port = None
        elif not isinstance(raw_ports, list) or len(raw_ports) != 1:
            raise ValueError("multiple port arguments")
        else:
            port = _validate_port(raw_ports[0])
    except ValueError as exc:
        raise RuntimeFailure(
            ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION
        ) from exc
    return LauncherArguments(port=port, no_browser=bool(namespace.no_browser))


def _read_user_config(path: Path) -> tuple[UserRuntimeConfig, bool]:
    if not path.exists():
        return UserRuntimeConfig(), False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError
        if set(raw) - UserRuntimeConfig._ALLOWED_KEYS:
            raise ValueError
        config = UserRuntimeConfig.model_validate(raw)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeFailure(
            ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION
        ) from exc
    if config.config_schema_version != 1:
        raise RuntimeFailure(ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION)
    return config, "port" in raw


def _read_environment_port() -> int | None:
    raw = os.environ.get(_PORT_ENVIRONMENT_VARIABLE)
    if raw is None:
        return None
    return _validate_port(raw)


def build_runtime_configuration(
    paths: RuntimePaths,
    arguments: LauncherArguments,
) -> RuntimeConfiguration:
    """Apply defaults -> JSON -> environment -> launcher args through Settings."""

    user, json_port_configured = _read_user_config(paths.config_file)
    try:
        environment_port = _read_environment_port()
        if arguments.port is not None:
            selected_port = _validate_port(arguments.port)
            port_source = PortConfigurationSource.COMMAND_LINE
        elif environment_port is not None:
            selected_port = environment_port
            port_source = PortConfigurationSource.ENVIRONMENT
        elif json_port_configured:
            selected_port = _validate_port(user.port)
            port_source = PortConfigurationSource.JSON
        else:
            selected_port = _validate_port(_DEFAULT_PORT)
            port_source = PortConfigurationSource.DEFAULT
    except ValueError as exc:
        raise RuntimeFailure(
            ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION
        ) from exc
    initial: dict[str, Any] = {
        "log_level": user.log_level,
        "log_json": user.log_json,
        "custom_tle_handoff_enabled": user.custom_tle_handoff_enabled,
        "custom_tle_handoff_port": selected_port,
        "api_bind_host": "127.0.0.1",
        "api_workers": 1,
        "api_reload_enabled": False,
        "forwarded_header_trust_enabled": False,
        "database_url": f"sqlite:///{paths.database_file.as_posix()}",
        "artifacts_dir": paths.artifacts_dir,
        "cache_dir": paths.cache_dir,
        "network_enabled": False,
        "celestrak_enabled": False,
        "jpl_sbdb_enabled": False,
        "jpl_cad_enabled": False,
        "open_research_enabled": False,
    }
    try:
        environment_resolved = _PackagedSettings(**initial)
        resolved_values = environment_resolved.model_dump()
        settings = Settings.model_validate(resolved_values)
    except ValueError as exc:
        raise RuntimeFailure(
            ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION
        ) from exc

    port = _validate_port(settings.custom_tle_handoff_port)
    expected_database = f"sqlite:///{paths.database_file.as_posix()}"
    if (
        settings.api_bind_host != "127.0.0.1"
        or settings.api_workers != 1
        or settings.api_reload_enabled
        or settings.forwarded_header_trust_enabled
        or port != selected_port
        or settings.database_url != expected_database
        or settings.resolved_artifacts_dir() != paths.artifacts_dir.resolve()
        or settings.resolved_cache_dir() != paths.cache_dir.resolve()
        or settings.network_enabled
        or settings.celestrak_enabled
        or settings.jpl_sbdb_enabled
        or settings.jpl_cad_enabled
        or settings.open_research_enabled
    ):
        raise RuntimeFailure(ExitCode.INVALID_CONFIGURATION, ReasonCode.INVALID_CONFIGURATION)

    open_browser = user.open_browser and not arguments.no_browser
    return RuntimeConfiguration(
        settings=settings,
        port=port,
        port_source=port_source,
        open_browser=open_browser,
    )
