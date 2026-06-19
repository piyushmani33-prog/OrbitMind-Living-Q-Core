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

    # --- Network safety (Phase 2). DISABLED by default (ADR-0009). ---
    # A live external request requires BOTH the global switch AND the source switch.
    network_enabled: bool = False
    celestrak_enabled: bool = False

    # CelesTrak connector configuration (endpoint is configurable, not hard-coded).
    celestrak_base_url: str = "https://celestrak.org/NORAD/elements/gp.php"
    celestrak_connect_timeout_seconds: float = 5.0
    celestrak_read_timeout_seconds: float = 10.0
    celestrak_max_retries: int = 2
    celestrak_cache_ttl_seconds: int = 7200  # 2h: do not refetch within this window
    # CelesTrak checks for new GP data only every 2 hours; do not poll more often.
    # The connector policy floors this at the official 7200s regardless of config.
    celestrak_min_refresh_seconds: int = 7200  # 2h official minimum (CelesTrak guidance)
    celestrak_max_response_bytes: int = 1_048_576  # 1 MiB response-size cap

    # Controlled cache directory for raw source payloads (metadata lives in the DB).
    cache_dir: Path = PROJECT_ROOT / "cache"

    def resolved_artifacts_dir(self) -> Path:
        """Absolute, resolved artifacts directory (used as the path-traversal root)."""
        return self._resolve(self.artifacts_dir)

    def resolved_cache_dir(self) -> Path:
        """Absolute, resolved source-cache directory (path-traversal root for cache)."""
        return self._resolve(self.cache_dir)

    @staticmethod
    def _resolve(path: Path) -> Path:
        if not path.is_absolute():
            path = (PROJECT_ROOT / path).resolve()
        return path.resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()
