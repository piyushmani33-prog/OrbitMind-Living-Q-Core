"""Bounded overclaim validator: affirmation rejected, disclaimer permitted (High #4)."""

from __future__ import annotations

import pytest

from orbitmind.optimization.overclaim import PERMITTED_DISCLAIMERS, contains_overclaim


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
