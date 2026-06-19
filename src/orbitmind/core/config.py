"""Typed application configuration (pydantic-settings).

Only this module reads environment variables. Everything else receives a typed
``Settings`` instance via dependency injection.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = three levels up from this file: src/orbitmind/core/config.py
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings loaded from environment / .env (prefix ``ORBITMIND_``)."""

    model_config = SettingsConfigDict(
        env_prefix="ORBITMIND_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "OrbitMind Living Q-Core"
    env: str = "local"
    log_level: str = "INFO"
    log_json: bool = False
    execution_mode: str = "local"

    # Storage
    database_url: str = "sqlite:///./data/orbitmind.db"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"

    # Mission demonstration limits (safety bounds)
    max_propagation_hours: float = 48.0
    min_step_seconds: int = 10
    max_step_seconds: int = 3600
    max_samples: int = 20_000

    # Quantum adapter
    quantum_enabled: bool = False

    def resolved_artifacts_dir(self) -> Path:
        """Absolute, resolved artifacts directory (used as the path-traversal root)."""
        path = self.artifacts_dir
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return path.resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
