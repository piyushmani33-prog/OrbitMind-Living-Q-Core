"""Signing-key configuration hardening (fourth review, High #3)."""

from __future__ import annotations

import pytest

from orbitmind.api.container import _build_evidence_signers
from orbitmind.core.config import Settings
from orbitmind.optimization import fixtures
from orbitmind.optimization.benchmark import run_benchmark
from orbitmind.optimization.problem import normalize_problem
from orbitmind.optimization.receipts import build_receipt, verify_receipt

_GOOD = "a-strong-evidence-signing-key-0123456789"  # >= 32 bytes, not a placeholder
_OTHER = "another-strong-evidence-signing-key-9876543210"


def _settings(**kw: object) -> Settings:
    return Settings(database_url="sqlite:///:memory:", env="test", **kw)  # type: ignore[arg-type]


def test_no_implicit_test_signer() -> None:
    # env=test with NO configured key must NOT silently gain a signer (High #3).
    active, signers = _build_evidence_signers(_settings())
    assert active is None and signers == {}


def test_valid_key_builds_active_signer() -> None:
    active, signers = _build_evidence_signers(_settings(evidence_signing_key=_GOOD))
    assert active is not None and active.key_id in signers


def test_empty_key_is_no_signer_not_an_error() -> None:
    # An empty configured key is the legitimate no-signer mode (not an error).
    active, signers = _build_evidence_signers(_settings(evidence_signing_key=""))
    assert active is None and signers == {}


@pytest.mark.parametrize("weak", ["abc", "changeme", "  placeholder  ", "secret", "x" * 31])
def test_weak_or_placeholder_active_key_rejected(weak: str) -> None:
    with pytest.raises(ValueError) as exc:
        _build_evidence_signers(_settings(evidence_signing_key=weak))
    assert weak not in str(exc.value)  # the secret is never echoed in the error


def test_duplicate_active_and_retired_id_rejected() -> None:
    with pytest.raises(ValueError):
        _build_evidence_signers(
            _settings(
                evidence_signing_key=_GOOD,
                evidence_signing_key_id="dup",
                evidence_signing_retired_keys=f"dup:{_OTHER}",
            )
        )


@pytest.mark.parametrize(
    "retired",
    [
        "no-colon-here",  # missing separator
        ":secretwithoutidsecretwithoutid00",  # blank id
        "kid-without-secret:",  # blank secret
        f"kid1:{_OTHER},kid1:{_GOOD}",  # duplicate key id
        f"a:{_OTHER},b:{_OTHER}",  # duplicate material
        "weakid:short",  # weak retired key
        "phid:changeme",  # placeholder retired key
    ],
)
def test_malformed_retired_config_fails_startup(retired: str) -> None:
    # Malformed retired-key configuration must FAIL startup, never be silently skipped (Low #2).
    with pytest.raises(ValueError):
        _build_evidence_signers(
            _settings(evidence_signing_key=_GOOD, evidence_signing_retired_keys=retired)
        )


def test_blank_active_key_id_with_configured_key_fails_startup() -> None:
    with pytest.raises(ValueError):
        _build_evidence_signers(_settings(evidence_signing_key=_GOOD, evidence_signing_key_id="  "))


def test_active_id_repeated_in_retired_fails_startup() -> None:
    with pytest.raises(ValueError):
        _build_evidence_signers(
            _settings(
                evidence_signing_key=_GOOD,
                evidence_signing_key_id="shared",
                evidence_signing_retired_keys=f"shared:{_OTHER}",
            )
        )


def test_trailing_comma_in_retired_is_tolerated() -> None:
    active, signers = _build_evidence_signers(
        _settings(evidence_signing_key=_GOOD, evidence_signing_retired_keys=f"old:{_OTHER},")
    )
    assert active is not None and "old" in signers


def test_secret_is_redacted_in_repr_and_dump() -> None:
    s = _settings(evidence_signing_key=_GOOD)
    assert _GOOD not in repr(s)
    assert _GOOD not in str(s.model_dump())
    assert s.evidence_signing_key.get_secret_value() == _GOOD  # only via explicit accessor


def test_retired_key_verifies_then_becomes_unverifiable_when_removed() -> None:
    # Rotation: a receipt signed by a now-retired key still verifies while the key is in the
    # keyring, and degrades to an honest "unknown-key-id" (not a crash) once removed.
    active, signers = _build_evidence_signers(
        _settings(
            evidence_signing_key=_GOOD,
            evidence_signing_key_id="new",
            evidence_signing_retired_keys=f"old:{_OTHER}",
        )
    )
    assert active is not None and active.key_id == "new"
    old = signers["old"]
    run = run_benchmark(normalize_problem(fixtures.fixture("default")), seed=7, run_quantum=False)
    receipt = build_receipt(run, signer=old)  # signed by the retired key
    assert verify_receipt(receipt, run=run, signers=signers).ok  # retired key still verifies
    pruned = verify_receipt(receipt, run=run, signers={"new": active})
    assert not pruned.ok and "unknown-key-id" in pruned.reasons
