"""Builds health, version, and capability reports."""

from __future__ import annotations

import platform
from importlib.metadata import PackageNotFoundError, version

from orbitmind import __version__
from orbitmind.core.config import Settings
from orbitmind.observability.models import CapabilityRecord, HealthReport, VersionReport
from orbitmind.persistence.database import Database
from orbitmind.quantum.adapter import quantum_available


def _ver(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - defensive
        return "unknown"


class ObservabilityService:
    """Reports operational status without leaking sensitive details."""

    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._db = database

    def health(self) -> HealthReport:
        db_ok = self._db.check_connection()
        return HealthReport(
            status="ok" if db_ok else "degraded",
            version=__version__,
            python_version=platform.python_version(),
            database="connected" if db_ok else "unavailable",
            execution_mode=self._settings.execution_mode,
            quantum="available" if quantum_available() else "unavailable",
        )

    def version(self) -> VersionReport:
        return VersionReport(
            app=self._settings.app_name,
            version=__version__,
            components={
                "python": platform.python_version(),
                "fastapi": _ver("fastapi"),
                "sqlalchemy": _ver("SQLAlchemy"),
                "sgp4": _ver("sgp4"),
                "numpy": _ver("numpy"),
                "matplotlib": _ver("matplotlib"),
            },
        )

    def capabilities(self) -> list[CapabilityRecord]:
        return [
            CapabilityRecord(
                name="orbital-propagation",
                available=True,
                detail="Deterministic SGP4 propagation from bundled sample TLEs.",
            ),
            CapabilityRecord(
                name="verification",
                available=True,
                detail="Deterministic verification checks over scientific results.",
            ),
            CapabilityRecord(
                name="visualization",
                available=True,
                detail="Altitude-vs-time and ground-track artifacts with sidecars.",
            ),
            CapabilityRecord(
                name="persistence",
                available=self._db.check_connection(),
                detail="SQLite system of record via SQLAlchemy (PostgreSQL is the prod target).",
            ),
            CapabilityRecord(
                name="quantum-adapter",
                available=quantum_available(),
                detail="Bounded Qiskit/Aer adapter; simulator-only; not on the mission path.",
            ),
        ]
