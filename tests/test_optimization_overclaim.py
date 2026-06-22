"""Bounded overclaim validator: affirmation rejected, disclaimer permitted (High #4;
fourth review, Medium #2 — NFKC/punctuation/negation matrix)."""

from __future__ import annotations

import pytest

from orbitmind.optimization.overclaim import PERMITTED_DISCLAIMERS, contains_overclaim

_EM_DASH = chr(0x2014)
_BOM = chr(0xFEFF)
_FULLWIDTH_A = chr(0xFF41)  # 'a' (NFKC-folds to ASCII 'a')


@pytest.mark.parametrize(
    "text",
    [
        "Quantum advantage verified on this instance.",
        "QUANTUM SUPERIORITY achieved",
        "quantum wins over the classical baseline",
        "this is better than classical",
        "faster than classical solvers",
        "production-ready quantum control",
        "production quantum control deployed",
        "  proven   quantum   advantage  ",  # normalized whitespace still matches
    ],
)
def test_affirmative_overclaims_are_rejected(text: str) -> None:
    assert contains_overclaim(text)


@pytest.mark.parametrize(
    "text",
    [
        "Not evidence of quantum advantage.",
        "No quantum advantage is claimed.",
        "Simulator-only; does not demonstrate hardware advantage.",
        "model-estimate; bounded simulator benchmark on a tiny fixture.",
        "",
    ],
)
def test_disclaimers_are_permitted(text: str) -> None:
    assert not contains_overclaim(text)


def test_documented_disclaimers_pass() -> None:
    for disclaimer in PERMITTED_DISCLAIMERS:
        assert not contains_overclaim(disclaimer)


@pytest.mark.parametrize(
    "text",
    [
        "quantum-advantage demonstrated",  # hyphen
        "quantum_advantage verified",  # underscore
        "Quantum" + _EM_DASH + "Advantage Demonstrated",  # em dash + case
        "quantum   advantage   proven",  # extra whitespace
        _BOM + "quantum advantage verified",  # NFKC / BOM
        "qu" + _FULLWIDTH_A + "ntum advantage verified",  # NFKC fold of full-width letter
        "this OUTPERFORMS classical decisively",
    ],
)
def test_obfuscated_overclaims_still_rejected(text: str) -> None:
    assert contains_overclaim(text)


@pytest.mark.parametrize(
    "text",
    [
        "we make no claim of quantum advantage here",
        "this does not demonstrate quantum advantage",
        "the run is never better than classical",
        "without any quantum advantage being shown",
        "results are not faster than classical baselines",
    ],
)
def test_negated_claims_are_permitted(text: str) -> None:
    assert not contains_overclaim(text)


@pytest.mark.parametrize(
    "text",
    [
        "no quantum advantage is claimed, but quantum advantage exists",
        "not faster than classical; however, faster than classical in production",
        "we make no such disclaimer in this work; quantum supremacy was clearly achieved",
    ],
)
def test_affirmative_after_negated_occurrence_still_rejected(text: str) -> None:
    # A negated first occurrence must not mask a later affirmative one (fifth review, Low #1).
    assert contains_overclaim(text)
