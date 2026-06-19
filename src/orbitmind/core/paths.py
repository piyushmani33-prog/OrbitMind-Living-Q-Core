"""Filesystem path safety: contain all artifact writes (SR-13/14)."""

from __future__ import annotations

from pathlib import Path

from orbitmind.core.errors import SecurityError
from orbitmind.core.ids import validate_uuid


def ensure_within(root: Path, target: Path) -> Path:
    """Return the resolved ``target`` if it lies within ``root``, else raise.

    Prevents path traversal: a resolved target escaping the artifacts root is a
    :class:`SecurityError`.
    """
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved != root_resolved and root_resolved not in target_resolved.parents:
        raise SecurityError("refusing to write outside the artifacts directory")
    return target_resolved


def mission_artifact_dir(artifacts_root: Path, mission_id: str) -> Path:
    """Resolve and create the per-mission artifact directory under the root.

    ``mission_id`` MUST be a valid UUID (SR-14); the resolved directory MUST be
    contained by ``artifacts_root`` (SR-13).
    """
    validate_uuid(mission_id)
    target = artifacts_root / mission_id
    safe = ensure_within(artifacts_root, target)
    safe.mkdir(parents=True, exist_ok=True)
    return safe
