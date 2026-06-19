"""Timezone-aware UTC time helpers.

The system MUST NOT depend on system local time (NFR-02). All datetimes are
timezone-aware UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as timezone-aware UTC.

    Naive datetimes are rejected: callers must supply explicit timezone info so we
    never silently assume local time.
    """
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware (naive datetimes are rejected)")
    return value.astimezone(UTC)


def isoformat_utc(value: datetime) -> str:
    """ISO-8601 string in UTC with a trailing ``Z`` style offset."""
    return ensure_utc(value).isoformat()
