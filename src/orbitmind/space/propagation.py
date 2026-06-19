"""Deterministic SGP4 orbital propagation (SR-01).

Propagates a satellite from a TLE element set over a bounded UTC window and
derives geodetic position. Per-sample failures are reported explicitly and never
silently discarded (SR-08).
"""

from __future__ import annotations

from datetime import timedelta
from importlib.metadata import PackageNotFoundError, version

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

COMPUTATION_VERSION = "orbitmind-sgp4-wgs72-1.0"


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
            seconds = t.second + t.microsecond / 1_000_000.0
            jd, fr = jday(t.year, t.month, t.day, t.hour, t.minute, seconds)
            error_code, r, v = satrec.sgp4(jd, fr)

            if error_code != 0:
                samples.append(
                    OrbitalStateSample(
                        timestamp=t,
                        status=SampleStatus.ERROR,
                        error=SGP4_ERRORS.get(error_code, f"sgp4 error {error_code}"),
                    )
                )
                continue

            lat, lon, alt = teme_to_geodetic((r[0], r[1], r[2]), jd + fr)
            samples.append(
                OrbitalStateSample(
                    timestamp=t,
                    position_km=Vector3(x=r[0], y=r[1], z=r[2]),
                    velocity_kmps=Vector3(x=v[0], y=v[1], z=v[2]),
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
