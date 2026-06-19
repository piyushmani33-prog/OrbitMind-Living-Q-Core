"""SGP4 element-set helpers: OMM/GP -> canonical TLE, and validation.

Keeps all sgp4-library usage inside the ``space`` domain. The connector normalizes
a source's structured GP/OMM fields into the OMM standard field names and calls
:func:`omm_fields_to_tle` to obtain canonical TLE lines for the existing,
unchanged propagation path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sgp4 import exporter, omm
from sgp4.api import Satrec


class ElementParseError(ValueError):
    """Raised when an element set cannot be parsed or propagated."""


# OMM fields required to build a valid SGP4 satellite record.
REQUIRED_OMM_FIELDS = (
    "EPOCH",
    "MEAN_MOTION",
    "ECCENTRICITY",
    "INCLINATION",
    "RA_OF_ASC_NODE",
    "ARG_OF_PERICENTER",
    "MEAN_ANOMALY",
    "NORAD_CAT_ID",
)


def omm_fields_to_tle(fields: dict[str, Any]) -> tuple[str, str]:
    """Build a Satrec from OMM/GP fields and export canonical TLE lines.

    Raises :class:`ElementParseError` if fields are missing or unusable.
    """
    missing = [k for k in REQUIRED_OMM_FIELDS if k not in fields or fields[k] in (None, "")]
    if missing:
        raise ElementParseError(f"missing required OMM fields: {', '.join(missing)}")
    try:
        satrec = Satrec()
        omm.initialize(satrec, fields)
        line1, line2 = exporter.export_tle(satrec)
    except (ValueError, KeyError, TypeError) as exc:
        raise ElementParseError(f"could not build element set from OMM fields: {exc}") from exc
    validate_propagatable(line1, line2)
    return (line1, line2)


def validate_propagatable(line1: str, line2: str) -> None:
    """Verify TLE lines parse and propagate at epoch (error code 0)."""
    try:
        satrec = Satrec.twoline2rv(line1, line2)
        error_code, _r, _v = satrec.sgp4(satrec.jdsatepoch, satrec.jdsatepochF)
    except (ValueError, RuntimeError) as exc:
        raise ElementParseError(f"TLE failed to parse: {exc}") from exc
    if error_code != 0:
        raise ElementParseError(f"element set failed to propagate at epoch (code {error_code})")


def parse_omm_epoch(fields: dict[str, Any]) -> datetime:
    """Parse the OMM ``EPOCH`` field into a timezone-aware UTC datetime."""
    raw = fields.get("EPOCH")
    if not raw:
        raise ElementParseError("OMM record has no EPOCH")
    text = str(raw).replace("Z", "")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ElementParseError(f"unparseable EPOCH '{raw}': {exc}") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
