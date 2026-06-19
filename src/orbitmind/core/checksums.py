"""SHA-256 checksum helpers for fixtures and generated artifacts (NFR-04)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(data: bytes) -> str:
    """Hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """Hex SHA-256 of UTF-8 text."""
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file's contents, streamed in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_canonical_json(obj: Any) -> str:
    """Hex SHA-256 of a canonical (sorted-key) JSON encoding of ``obj``.

    Used to hash mission inputs for provenance (deterministic across runs).
    """
    encoded = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return sha256_text(encoded)
