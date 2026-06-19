"""Unit tests for artifact path safety (SR-13/14)."""

from __future__ import annotations

from pathlib import Path

import pytest

from orbitmind.core.errors import SecurityError
from orbitmind.core.paths import ensure_within, mission_artifact_dir

VALID_UUID = "11111111-2222-3333-4444-555555555555"


def test_mission_artifact_dir_creates_within_root(tmp_path: Path) -> None:
    out = mission_artifact_dir(tmp_path, VALID_UUID)
    assert out.is_dir()
    assert out.parent == tmp_path.resolve()


def test_invalid_uuid_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="valid UUID"):
        mission_artifact_dir(tmp_path, "../escape")


def test_path_traversal_rejected(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    with pytest.raises(SecurityError):
        ensure_within(root, root / ".." / "outside.png")


def test_ensure_within_allows_nested(tmp_path: Path) -> None:
    root = tmp_path / "artifacts"
    root.mkdir()
    target = root / "abc" / "file.png"
    assert ensure_within(root, target) == target.resolve()
