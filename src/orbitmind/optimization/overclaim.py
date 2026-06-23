"""Bounded overclaim validator for artifact sidecars + summaries (third review, High #4;
fourth review, Medium #2).

Rejects affirmative, scientifically misleading quantum claims while permitting explicit
disclaimers. Matching is NFKC-normalized and punctuation/case/whitespace insensitive (so
``Quantum-Advantage``, ``quantum_advantage``, and ``quantum   advantage`` all match), and a
forbidden phrase preceded by a negation within a short window is treated as a permitted
disclaimer (so "no quantum advantage is claimed" / "not better than classical" are allowed).
"""

from __future__ import annotations

import re
import unicodedata

# Affirmative claims that must never appear UN-negated in artifact text.
_FORBIDDEN_PHRASES = (
    "quantum advantage verified",
    "quantum advantage demonstrated",
    "quantum advantage proven",
    "proven quantum advantage",
    "achieves quantum advantage",
    "quantum advantage",
    "quantum supremacy",
    "quantum superiority",
    "quantum wins",
    "better than classical",
    "faster than classical",
    "outperforms classical",
    "beats classical",
    "production ready quantum",
    "production quantum control",
)

# Negation/disclaimer cues; when one appears just before a forbidden phrase the claim is
# negated and therefore permitted.
_NEGATORS = frozenset(
    {
        "no",
        "not",
        "never",
        "without",
        "isnt",
        "arent",
        "dont",
        "doesnt",
        "cannot",
        "cant",
        "false",
        "refute",
        "refutes",
        "refuted",
        "disclaim",
        "disclaims",
        "disclaimed",
        "neither",
        "nor",
    }
)
_NEGATION_WINDOW = 4

# Disclaimers that are explicitly permitted (documented here for clarity + tests).
PERMITTED_DISCLAIMERS = (
    "not evidence of quantum advantage",
    "no quantum advantage is claimed",
    "this is not better than classical",
)

# hyphen, underscore, Unicode hyphens/dashes (U+2010-U+2015), and minus sign (U+2212) -> space.
# Built from codepoints so the source stays ASCII-only.
_DASH_CHARS = "-_" + "".join(chr(c) for c in range(0x2010, 0x2016)) + chr(0x2212)
_DASH_TABLE = {ord(c): " " for c in _DASH_CHARS}
_NON_WORD = re.compile(r"[^\w\s]")


def _normalize(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).lower().translate(_DASH_TABLE)
    t = _NON_WORD.sub(" ", t)
    return " ".join(t.split())


def contains_overclaim(text: str) -> bool:
    """True iff ``text`` contains an affirmative, misleading quantum-advantage claim that is not
    negated by a nearby disclaimer."""
    norm = _normalize(text)
    for phrase in _FORBIDDEN_PHRASES:
        # Evaluate EVERY occurrence (fifth review, Low #1): a negated first occurrence must not
        # mask a later affirmative one ("no quantum advantage is claimed, but quantum advantage
        # exists" must fail).
        start = norm.find(phrase)
        while start != -1:
            preceding = norm[:start].split()
            if not any(neg in preceding[-_NEGATION_WINDOW:] for neg in _NEGATORS):
                return True  # an affirmative, non-negated occurrence remains
            start = norm.find(phrase, start + 1)
    return False
