"""Stable identifier helpers (UUID4) with validation for path-safe use."""

from __future__ import annotations

import uuid


def new_id() -> str:
    """Return a new random UUID4 string."""
    return str(uuid.uuid4())


def is_valid_uuid(value: str) -> bool:
    """True if ``value`` is a syntactically valid UUID string."""
    try:
        uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return True


def validate_uuid(value: str) -> str:
    """Return ``value`` if it is a valid UUID, else raise ``ValueError``.

    Used before any UUID is embedded in a filesystem path (SR-14).
    """
    if not is_valid_uuid(value):
        raise ValueError("identifier is not a valid UUID")
    return value
