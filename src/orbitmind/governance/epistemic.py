"""Epistemic status policy (ADR-0006).

Every major output carries exactly one ``EpistemicStatus``. Deterministic
calculations must never be labelled ``VERIFIED_FACT`` and must never receive a
confidence percentage.
"""

from __future__ import annotations

from enum import StrEnum


class EpistemicStatus(StrEnum):
    """The kind of epistemic claim an output represents."""

    VERIFIED_FACT = "verified-fact"
    DETERMINISTIC_CALCULATION = "deterministic-calculation"
    MODEL_ESTIMATE = "model-estimate"
    HYPOTHESIS = "hypothesis"
    ASSUMPTION = "assumption"
    UNKNOWN = "unknown"
    REJECTED = "rejected"


# Statuses for which a numeric confidence score is NOT meaningful/allowed.
_CONFIDENCE_FORBIDDEN: frozenset[EpistemicStatus] = frozenset(
    {
        EpistemicStatus.VERIFIED_FACT,
        EpistemicStatus.DETERMINISTIC_CALCULATION,
    }
)


def confidence_allowed(status: EpistemicStatus) -> bool:
    """Whether attaching a confidence percentage is defensible for ``status``."""
    return status not in _CONFIDENCE_FORBIDDEN


def assert_not_verified_generated(status: EpistemicStatus, *, is_generated_text: bool) -> None:
    """Guard: a generated natural-language explanation can never be a verified fact.

    Raises ``ValueError`` if a generated explanation is labelled ``VERIFIED_FACT``
    (SR-04).
    """
    if is_generated_text and status is EpistemicStatus.VERIFIED_FACT:
        raise ValueError("a generated explanation may not be labelled verified-fact")
