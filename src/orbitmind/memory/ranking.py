"""Explicit, deterministic lexical ranking formula.

Recorded per result so every ranking is explainable and reproducible. Identical on
SQLite and PostgreSQL; only the *candidate selection* differs by dialect (PostgreSQL
uses stemmed full-text matching, SQLite uses exact-term matching).
"""

from __future__ import annotations

from collections import Counter

from orbitmind.memory.models import RankingComponents

TITLE_BOOST = 0.5
SECTION_BOOST = 0.3
IDENTIFIER_BOOST = 0.5


def is_identifier(term: str) -> bool:
    """Heuristic: identifier-like tokens contain a digit or a path/dot separator."""
    return any(c.isdigit() for c in term) or "/" in term or "." in term or "_" in term


def score(
    query_terms: set[str],
    chunk_tokens: list[str],
    title_tokens: set[str],
    section_tokens: set[str],
) -> tuple[RankingComponents, list[str]]:
    """Score one chunk against the query; return components + matched terms."""
    counts = Counter(chunk_tokens)
    matched = sorted(t for t in query_terms if t in counts)
    occurrences = sum(counts[t] for t in matched)
    lexical = float(len(matched)) + 0.05 * float(occurrences)

    title_boost = TITLE_BOOST if any(t in title_tokens for t in query_terms) else 0.0
    section_boost = SECTION_BOOST if any(t in section_tokens for t in query_terms) else 0.0
    identifier_boost = IDENTIFIER_BOOST * float(sum(1 for t in matched if is_identifier(t)))
    total = round(lexical + title_boost + section_boost + identifier_boost, 6)
    return (
        RankingComponents(
            lexical=round(lexical, 6),
            title_boost=title_boost,
            section_boost=section_boost,
            identifier_boost=identifier_boost,
            total=total,
        ),
        matched,
    )
