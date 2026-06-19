"""Unit tests for epistemic-status policy (ADR-0006)."""

from __future__ import annotations

import pytest

from orbitmind.governance.epistemic import (
    EpistemicStatus,
    assert_not_verified_generated,
    confidence_allowed,
)


def test_confidence_forbidden_for_deterministic_and_verified() -> None:
    assert not confidence_allowed(EpistemicStatus.DETERMINISTIC_CALCULATION)
    assert not confidence_allowed(EpistemicStatus.VERIFIED_FACT)


def test_confidence_allowed_for_estimates_and_hypotheses() -> None:
    assert confidence_allowed(EpistemicStatus.MODEL_ESTIMATE)
    assert confidence_allowed(EpistemicStatus.HYPOTHESIS)


def test_generated_text_cannot_be_verified_fact() -> None:
    with pytest.raises(ValueError, match="verified-fact"):
        assert_not_verified_generated(EpistemicStatus.VERIFIED_FACT, is_generated_text=True)


def test_generated_text_may_be_hypothesis() -> None:
    # Should not raise.
    assert_not_verified_generated(EpistemicStatus.HYPOTHESIS, is_generated_text=True)


def test_status_serializes_to_value() -> None:
    assert EpistemicStatus.DETERMINISTIC_CALCULATION.value == "deterministic-calculation"
    assert str(EpistemicStatus.ASSUMPTION) == "assumption"
