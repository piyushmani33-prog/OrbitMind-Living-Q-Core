"""Unit tests for checksum helpers."""

from __future__ import annotations

from pathlib import Path

from orbitmind.core.checksums import (
    sha256_bytes,
    sha256_canonical_json,
    sha256_file,
    sha256_text,
)


def test_sha256_text_matches_known_value() -> None:
    # Well-known SHA-256 of the empty string.
    expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256_text("") == expected
    assert sha256_bytes(b"") == expected


def test_canonical_json_is_key_order_independent() -> None:
    a = sha256_canonical_json({"x": 1, "y": 2})
    b = sha256_canonical_json({"y": 2, "x": 1})
    assert a == b


def test_canonical_json_distinguishes_values() -> None:
    assert sha256_canonical_json({"x": 1}) != sha256_canonical_json({"x": 2})


def test_sha256_file(tmp_path: Path) -> None:
    p = tmp_path / "f.bin"
    p.write_bytes(b"hello")
    assert sha256_file(p) == sha256_bytes(b"hello")
