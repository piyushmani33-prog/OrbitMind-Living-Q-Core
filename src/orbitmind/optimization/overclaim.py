"""Bounded overclaim validator for artifact sidecars + summaries (third review, High #4).

Rejects affirmative, scientifically misleading quantum claims while permitting explicit
disclaimers. Normalized, case-insensitive substring checks: the affirmative phrases are
specific enough that a legitimate disclaimer ("not evidence of quantum advantage", "no quantum
advantage is claimed") never contains them.
"""

from __future__ import annotations

# Affirmative claims that must never appear in artifact text.
_FORBIDDEN_PHRASES = (
    "quantum advantage verified",
    "quantum advantage demonstrated",
    "proven quantum advantage",
    "achieves quantum advantage",
    "quantum superiority",
    "quantum wins",
    "better than classical",
    "faster than classical",
    "outperforms classical",
    "production-ready quantum",
    "production quantum control",
)

# Disclaimers that are explicitly permitted (documented here for clarity + tests).
PERMITTED_DISCLAIMERS = (
    "not evidence of quantum advantage",
    "no quantum advantage is claimed",
)


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def contains_overclaim(text: str) -> bool:
    """True iff ``text`` contains an affirmative, misleading quantum-advantage claim."""
    norm = _normalize(text)
    return any(phrase in norm for phrase in _FORBIDDEN_PHRASES)
