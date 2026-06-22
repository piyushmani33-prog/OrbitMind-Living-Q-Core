"""Independent known-answer test for the receipt HMAC primitive (fourth review, Low #1).

Pins the exact HMAC-SHA256 output for a fixed key + payload so an accidental change to the
signing algorithm, digest, or encoding is caught without trusting any other project code.
"""

from __future__ import annotations

import hashlib
import hmac

from orbitmind.optimization.receipts import HmacSha256EvidenceReceiptSigner

# A fixed key + payload with a literal expected HMAC-SHA256 hex digest.
_KEY = b"known-answer-key-0123456789abcdef"
_DATA = b"orbitmind-receipt-known-answer"
_EXPECTED = "8e4e70efe71271028df9caaae952d59dddbccc3670471f2bef07308a66a99540"


def test_signer_matches_literal_known_answer() -> None:
    signer = HmacSha256EvidenceReceiptSigner(_KEY, "ka")
    assert signer.sign(_DATA) == _EXPECTED


def test_signer_matches_stdlib_reference() -> None:
    signer = HmacSha256EvidenceReceiptSigner(_KEY, "ka")
    reference = hmac.new(_KEY, _DATA, hashlib.sha256).hexdigest()
    assert signer.sign(_DATA) == reference == _EXPECTED


def test_signature_is_lowercase_hex_of_fixed_length() -> None:
    sig = HmacSha256EvidenceReceiptSigner(_KEY, "ka").sign(_DATA)
    assert len(sig) == 64 and sig == sig.lower()
    assert all(c in "0123456789abcdef" for c in sig)
