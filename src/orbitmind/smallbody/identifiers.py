"""Validation of small-body identifiers (no arbitrary query-string fragments)."""

from __future__ import annotations

import re

from orbitmind.core.errors import ValidationError

# Accept numbers ("433"), names ("Eros"), provisional designations ("2021 AB"),
# and comet designations ("1P/Halley", "C/2014 Q2"). Reject query-injection chars
# (& = ? # %) and anything outside this conservative set.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _/().+-]{0,40}$")


def validate_small_body_identifier(identifier: str) -> str:
    """Return a trimmed identifier if it is an approved small-body identifier."""
    value = identifier.strip()
    if not _IDENTIFIER.match(value):
        raise ValidationError("unsupported small-body identifier format")
    return value
