"""Deterministic SGP4 orbital propagation (SR-01).

Propagates a satellite from a TLE element set over a bounded UTC window and
derives geodetic position. Per-sample failures are reported explicitly and never
silently discarded (SR-08).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib.metadata import PackageNotFoundError, version
from typing import Literal, cast

from sgp4.api import SGP4_ERRORS, Satrec, jday

from orbitmind import __version__ as orbitmind_version
from orbitmind.core.timeutils import ensure_utc
from orbitmind.mission.models import MissionRequest
from orbitmind.space.geodesy import teme_to_geodetic
from orbitmind.space.models import (
    OrbitalSourceRecord,
    OrbitalStateSample,
    SampleStatus,
    ScientificResult,
    Vector3,
)

COMPUTATION_VERSION: Literal["orbitmind-sgp4-wgs72-1.0"] = "orbitmind-sgp4-wgs72-1.0"


@dataclass(frozen=True)
class Sgp4StateVector:
    """One pinned SGP4 outcome in TEME, with UTC used for the Julian-date input."""

    timestamp: datetime
    julian_date_utc_as_ut1: float
    error_code: int
    position_km: tuple[float, float, float] | None
    velocity_kmps: tuple[float, float, float] | None


def propagate_sgp4_state(satrec: Satrec, timestamp: datetime) -> Sgp4StateVector:
    """Evaluate one UTC instant through the shared python-sgp4/WGS72 path."""

    timestamp_utc = ensure_utc(timestamp)
    seconds = timestamp_utc.second + timestamp_utc.microsecond / 1_000_000.0
    jd, fr = jday(
        timestamp_utc.year,
        timestamp_utc.month,
        timestamp_utc.day,
        timestamp_utc.hour,
        timestamp_utc.minute,
        seconds,
    )
    error_code, position, velocity = satrec.sgp4(jd, fr)
    if error_code != 0:
        return Sgp4StateVector(
            timestamp=timestamp_utc,
            julian_date_utc_as_ut1=float(jd + fr),
            error_code=int(error_code),
            position_km=None,
            velocity_kmps=None,
        )
    return Sgp4StateVector(
        timestamp=timestamp_utc,
        julian_date_utc_as_ut1=float(jd + fr),
        error_code=0,
        position_km=cast(
            tuple[float, float, float],
            tuple(float(component) for component in position),
        ),
        velocity_kmps=cast(
            tuple[float, float, float],
            tuple(float(component) for component in velocity),
        ),
    )


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:  # pragma: no cover - defensive
        return "unknown"


def _software_versions() -> dict[str, str]:
    return {
        "orbitmind": orbitmind_version,
        "sgp4": _pkg_version("sgp4"),
        "numpy": _pkg_version("numpy"),
    }


class PropagationService:
    """Propagates a TLE over a requested window into a ``ScientificResult``."""

    def propagate(
        self,
        *,
        mission_id: str,
        request: MissionRequest,
        source: OrbitalSourceRecord,
        tle_line1: str,
        tle_line2: str,
    ) -> ScientificResult:
        satrec = Satrec.twoline2rv(tle_line1, tle_line2)
        start = ensure_utc(request.start_time)
        samples: list[OrbitalStateSample] = []

        for i in range(request.expected_sample_count()):
            t = start + timedelta(seconds=i * request.step_seconds)
            state = propagate_sgp4_state(satrec, t)

            if state.error_code != 0 or state.position_km is None or state.velocity_kmps is None:
                samples.append(
                    OrbitalStateSample(
                        timestamp=t,
                        status=SampleStatus.ERROR,
                        error=SGP4_ERRORS.get(
                            state.error_code,
                            f"sgp4 error {state.error_code}",
                        ),
                    )
                )
                continue

            position = state.position_km
            velocity = state.velocity_kmps
            lat, lon, alt = teme_to_geodetic(
                position,
                state.julian_date_utc_as_ut1,
            )
            samples.append(
                OrbitalStateSample(
                    timestamp=t,
                    position_km=Vector3(x=position[0], y=position[1], z=position[2]),
                    velocity_kmps=Vector3(
                        x=velocity[0],
                        y=velocity[1],
                        z=velocity[2],
                    ),
                    latitude_deg=lat,
                    longitude_deg=lon,
                    altitude_km=alt,
                    status=SampleStatus.OK,
                )
            )

        return ScientificResult(
            mission_id=mission_id,
            satellite_id=request.satellite_id,
            samples=samples,
            computation_version=COMPUTATION_VERSION,
            software_versions=_software_versions(),
            source=source,
            summary=summarize_samples(samples),
        )


def summarize_samples(samples: list[OrbitalStateSample]) -> dict[str, float]:
    altitudes = [s.altitude_km for s in samples if s.altitude_km is not None]
    ok = sum(1 for s in samples if s.status is SampleStatus.OK)
    errors = len(samples) - ok
    summary: dict[str, float] = {
        "sample_count": float(len(samples)),
        "ok_count": float(ok),
        "error_count": float(errors),
    }
    if altitudes:
        summary["altitude_min_km"] = min(altitudes)
        summary["altitude_max_km"] = max(altitudes)
        summary["altitude_mean_km"] = sum(altitudes) / len(altitudes)
    return summary
