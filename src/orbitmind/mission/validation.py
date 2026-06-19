"""Settings-dependent mission validation (safety bounds, supported ids).

Static field checks (ranges, end>start) live on the Pydantic models. This module
enforces bounds that depend on configuration or external registries and raises a
safe :class:`~orbitmind.core.errors.ValidationError` on failure.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from orbitmind.core.config import Settings
from orbitmind.core.errors import ValidationError
from orbitmind.mission.models import MissionRequest, MissionSource

# CelesTrak satellite ids are NORAD catalog numbers (digits only), not arbitrary input.
_NORAD_ID = re.compile(r"^\d{1,9}$")


def validate_mission_request(
    request: MissionRequest,
    settings: Settings,
    supported_satellite_ids: Iterable[str],
) -> None:
    """Validate a request against configured safety bounds. Raises on violation."""
    if request.source is MissionSource.SAMPLE and request.satellite_id not in set(
        supported_satellite_ids
    ):
        raise ValidationError("unsupported satellite identifier")
    if request.source is MissionSource.CELESTRAK and not _NORAD_ID.match(request.satellite_id):
        raise ValidationError(
            "CelesTrak satellite identifier must be a NORAD catalog number (digits)"
        )

    max_seconds = settings.max_propagation_hours * 3600.0
    if request.duration_seconds > max_seconds:
        raise ValidationError(
            f"requested duration exceeds maximum of {settings.max_propagation_hours} hours"
        )

    if request.step_seconds < settings.min_step_seconds:
        raise ValidationError(f"step_seconds below minimum of {settings.min_step_seconds}")
    if request.step_seconds > settings.max_step_seconds:
        raise ValidationError(f"step_seconds above maximum of {settings.max_step_seconds}")

    if request.expected_sample_count() > settings.max_samples:
        raise ValidationError(f"requested sample count exceeds maximum of {settings.max_samples}")

    if not request.output_types:
        raise ValidationError("at least one output type is required")
