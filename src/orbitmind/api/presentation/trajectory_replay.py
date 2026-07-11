"""Display-only projection for server-rendered trajectory replay HTML.

This module maps already verified geodetic replay samples into SVG coordinates.
It does not propagate orbits, transform frames, calculate geodetic coordinates,
or derive observer geometry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from typing import Any

from orbitmind.trajectory_replay.models import TrajectoryReplayResult

SVG_WIDTH = 1000
SVG_HEIGHT = 500
PAYLOAD_SCHEMA_VERSION = "trajectory-replay-display-v1"


@dataclass(frozen=True)
class ReplayDisplayProjection:
    """Compact display projection consumed by the Workbench replay page."""

    payload_json: str
    payload_size_bytes: int
    polyline_points: tuple[str, ...]
    observer_x: float
    observer_y: float


def build_replay_display_projection(result: TrajectoryReplayResult) -> ReplayDisplayProjection:
    """Build a script-safe display payload from server-authoritative replay samples."""

    if result.observer is None:
        raise ValueError("trajectory replay display requires an observer")
    projected_samples: list[dict[str, int | float | str]] = []
    coordinates_by_sequence: dict[int, tuple[float, float]] = {}
    for sample in result.samples:
        x, y = _project(sample.longitude_deg, sample.latitude_deg)
        coordinates_by_sequence[sample.sequence] = (x, y)
        row: dict[str, int | float | str] = {
            "sequence": sample.sequence,
            "timestamp_utc": _format_utc(sample.timestamp),
            "latitude_deg": round(sample.latitude_deg, 6),
            "longitude_deg": round(sample.longitude_deg, 6),
            "altitude_km": round(sample.altitude_km, 6),
            "x": round(x, 3),
            "y": round(y, 3),
        }
        if sample.observer_azimuth_deg is not None:
            row["azimuth_deg"] = round(sample.observer_azimuth_deg, 6)
            row["elevation_deg"] = round(sample.observer_elevation_deg or 0.0, 6)
            row["range_km"] = round(sample.observer_slant_range_km or 0.0, 6)
        projected_samples.append(row)

    segment_indexes = tuple(tuple(segment.sample_indexes) for segment in result.track_segments)
    polylines = tuple(
        " ".join(_format_point(coordinates_by_sequence[index]) for index in segment)
        for segment in segment_indexes
    )
    observer_x, observer_y = _project(result.observer.longitude_deg, result.observer.latitude_deg)
    payload = {
        "schema_version": PAYLOAD_SCHEMA_VERSION,
        "sample_count": result.sample_count,
        "sample_interval_seconds": result.sample_interval_seconds,
        "svg_width": SVG_WIDTH,
        "svg_height": SVG_HEIGHT,
        "samples": projected_samples,
        "segments": segment_indexes,
        "observer": {
            "latitude_deg": result.observer.latitude_deg,
            "longitude_deg": result.observer.longitude_deg,
            "altitude_km": result.observer.altitude_km,
            "x": round(observer_x, 3),
            "y": round(observer_y, 3),
        },
        "source_identity": {
            "object_label": result.source_identity.object_label,
            "object_id": result.source_identity.object_id,
            "norad_catalog_id": result.source_identity.norad_catalog_id,
            "trajectory_reference": result.source_identity.trajectory_reference,
            "source_epoch": _format_utc(result.source_identity.source_epoch),
        },
        "references": {
            "input_reference": result.input_reference,
            "result_reference": result.result_reference,
        },
        "limitations": result.limitations,
    }
    payload_json = script_safe_json(payload)
    return ReplayDisplayProjection(
        payload_json=payload_json,
        payload_size_bytes=len(payload_json.encode("utf-8")),
        polyline_points=polylines,
        observer_x=observer_x,
        observer_y=observer_y,
    )


def script_safe_json(value: Any) -> str:
    """Return compact JSON that is safe inside a non-executable script block."""

    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return (
        raw.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def escape_attr(value: str) -> str:
    """HTML-escape one attribute value."""

    return escape(value, quote=True)


def _project(longitude_deg: float, latitude_deg: float) -> tuple[float, float]:
    x = ((longitude_deg + 180.0) / 360.0) * SVG_WIDTH
    y = ((90.0 - latitude_deg) / 180.0) * SVG_HEIGHT
    return x, y


def _format_point(point: tuple[float, float]) -> str:
    return f"{point[0]:.2f},{point[1]:.2f}"


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
