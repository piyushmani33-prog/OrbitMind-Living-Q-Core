"""Filesystem cache store for raw source payloads + an in-process keyed lock.

Raw bodies are written under the controlled cache root (path-traversal rejected,
SR-13). Only metadata + checksum + the relative path are stored in the database.
A keyed lock prevents concurrent refresh storms for the same cache key (no
distributed locking — Phase 2 is single-process).
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from orbitmind.core.checksums import sha256_bytes
from orbitmind.core.paths import ensure_within

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def cache_key_for(source_id: str, selector: str) -> str:
    """Deterministic cache key for a source + selector (e.g. satellite id)."""
    return f"{source_id}:{selector}"


class SourceCacheStore:
    """Reads/writes raw payloads under a controlled cache directory."""

    def __init__(self, cache_root: Path) -> None:
        self._root = cache_root

    def write_body(self, source_id: str, cache_key: str, body: bytes) -> str:
        """Persist a raw body; return its path relative to the cache root."""
        if not _SAFE_ID.match(source_id):
            raise ValueError("unsafe source_id for cache path")
        source_dir = ensure_within(self._root, self._root / source_id)
        source_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{sha256_bytes(cache_key.encode('utf-8'))}.json"
        target = ensure_within(self._root, source_dir / filename)
        target.write_bytes(body)
        return target.relative_to(self._root.resolve()).as_posix()

    def read_body(self, body_path: str) -> bytes:
        """Read a previously cached body by its relative path."""
        target = ensure_within(self._root, self._root / body_path)
        return target.read_bytes()


class KeyedLock:
    """Provides a per-key re-entrant-free lock to serialize refreshes."""

    def __init__(self) -> None:
        self._master = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @contextmanager
    def acquire(self, key: str) -> Iterator[None]:
        with self._master:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            yield
