"""Deterministic text normalization that preserves scientific meaning.

The authoritative stored text is only line-ending normalized (no lowercasing, no
punctuation stripping, Unicode/symbols/units/identifiers preserved). A separate
search-normalized representation is produced for lexical matching.
"""

from __future__ import annotations

import re

from orbitmind.core.checksums import sha256_text

_WS = re.compile(r"\s+")
# Tokens: alphanumeric cores plus common scientific identifier characters
# (so "25544", "1p/halley", "v_rel", "ts_rank" survive as single tokens).
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._/+-]*")


def normalize_line_endings(text: str) -> str:
    """Normalize CRLF/CR to LF (preserves all other content)."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def search_normalize(text: str) -> str:
    """Lowercase + collapse whitespace for lexical matching (Unicode preserved)."""
    return _WS.sub(" ", text).strip().lower()


def content_checksum(text: str) -> str:
    """SHA-256 of the (line-ending normalized) authoritative text."""
    return sha256_text(text)


def tokenize(text: str) -> list[str]:
    """Deterministic tokenization for lexical ranking."""
    return _TOKEN.findall(text.lower())
