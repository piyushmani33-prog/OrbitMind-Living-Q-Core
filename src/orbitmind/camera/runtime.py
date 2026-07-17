"""Immutable runtime dependencies for future ephemeral camera media work."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from orbitmind.camera.csrf import CAMERA_OPAQUE_SECRET_BYTES, SecretGenerator, UtcClock

CAMERA_MEDIA_ROOT_NAME = "camera-sessions"


@dataclass(frozen=True, slots=True)
class CameraMediaRuntimeContext:
    """Application-scoped camera paths, clocks, randomness, and binding authority."""

    runtime_temp_dir: Path
    media_root: Path
    utcnow: UtcClock
    page_session_id_generator: SecretGenerator
    csrf_token_generator: SecretGenerator
    media_session_id_generator: SecretGenerator
    media_capability_generator: SecretGenerator
    process_binding_key: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not self.runtime_temp_dir.is_absolute() or not self.media_root.is_absolute():
            raise ValueError("camera runtime paths must be absolute")
        runtime_temp_dir = self.runtime_temp_dir.resolve(strict=False)
        media_root = self.media_root.resolve(strict=False)
        expected_media_root = (runtime_temp_dir / CAMERA_MEDIA_ROOT_NAME).resolve(strict=False)
        if media_root != expected_media_root or media_root.parent != runtime_temp_dir:
            raise ValueError("camera media root must be the exact runtime temp child")
        if runtime_temp_dir.exists() and not runtime_temp_dir.is_dir():
            raise ValueError("camera runtime temp path must be a directory")
        if media_root.exists() and not media_root.is_dir():
            raise ValueError("camera media root must be a directory when present")
        if type(self.process_binding_key) is not bytes or (
            len(self.process_binding_key) != CAMERA_OPAQUE_SECRET_BYTES
        ):
            raise ValueError("camera process binding key must contain exactly 32 bytes")
        generators = (
            self.page_session_id_generator,
            self.csrf_token_generator,
            self.media_session_id_generator,
            self.media_capability_generator,
        )
        if not callable(self.utcnow) or not all(callable(generator) for generator in generators):
            raise ValueError("camera runtime dependencies must be callable")
        now = self.utcnow()
        if now.tzinfo is None or now.utcoffset() != timedelta(0):
            raise ValueError("camera runtime clock must return timezone-aware UTC")
        object.__setattr__(self, "runtime_temp_dir", runtime_temp_dir)
        object.__setattr__(self, "media_root", media_root)
        object.__setattr__(self, "process_binding_key", bytes(self.process_binding_key))

    @classmethod
    def production(cls, runtime_temp_dir: Path) -> CameraMediaRuntimeContext:
        """Build one process-local context without creating a directory or media file."""

        return cls(
            runtime_temp_dir=runtime_temp_dir,
            media_root=runtime_temp_dir / CAMERA_MEDIA_ROOT_NAME,
            utcnow=lambda: datetime.now(UTC),
            page_session_id_generator=lambda: secrets.token_bytes(CAMERA_OPAQUE_SECRET_BYTES),
            csrf_token_generator=lambda: secrets.token_bytes(CAMERA_OPAQUE_SECRET_BYTES),
            media_session_id_generator=lambda: secrets.token_bytes(CAMERA_OPAQUE_SECRET_BYTES),
            media_capability_generator=lambda: secrets.token_bytes(CAMERA_OPAQUE_SECRET_BYTES),
            process_binding_key=secrets.token_bytes(CAMERA_OPAQUE_SECRET_BYTES),
        )
