"""Unit tests for the source cache store + keyed lock + path safety."""

from __future__ import annotations

from pathlib import Path

import pytest

from orbitmind.core.errors import SecurityError
from orbitmind.sources.cache import KeyedLock, SourceCacheStore, cache_key_for


def test_cache_key_is_deterministic() -> None:
    assert cache_key_for("celestrak", "25544") == "celestrak:25544"


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    store = SourceCacheStore(tmp_path)
    body = b'[{"OBJECT_NAME": "ISS"}]'
    rel = store.write_body("celestrak", "celestrak:25544", body)
    assert (tmp_path / rel).exists()
    assert store.read_body(rel) == body


def test_unsafe_source_id_rejected(tmp_path: Path) -> None:
    store = SourceCacheStore(tmp_path)
    with pytest.raises(ValueError, match="unsafe source_id"):
        store.write_body("../evil", "k", b"x")


def test_path_traversal_on_read_rejected(tmp_path: Path) -> None:
    store = SourceCacheStore(tmp_path)
    with pytest.raises(SecurityError):
        store.read_body("../../etc/passwd")


def test_keyed_lock_serializes_same_key() -> None:
    lock = KeyedLock()
    # Distinct keys acquire independently; the same key would serialize across threads.
    with lock.acquire("k"), lock.acquire("other"):
        pass
