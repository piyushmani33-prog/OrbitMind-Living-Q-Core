"""Pure scalar WGS84 topocentric geometry helpers."""

from __future__ import annotations

import math

from orbitmind.core.units import WGS84_A_KM, WGS84_E2
from orbitmind.observation_geometry.models import GeodeticPosition
from orbitmind.space.geodesy import gmst_radians, teme_to_ecef


def geodetic_to_ecef_km(position: GeodeticPosition) -> tuple[float, float, float]:
    """Convert geodetic WGS84 coordinates to ECEF kilometres."""

    lat = math.radians(position.latitude_deg)
    lon = math.radians(position.longitude_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    n = WGS84_A_KM / math.sqrt(1.0 - WGS84_E2 * sin_lat * sin_lat)
    radius = n + position.altitude_km
    x = radius * cos_lat * math.cos(lon)
    y = radius * cos_lat * math.sin(lon)
    z = (n * (1.0 - WGS84_E2) + position.altitude_km) * sin_lat
    _require_finite_vector((x, y, z), "ecef")
    return (x, y, z)


def teme_to_ecef_km(
    position_km: tuple[float, float, float],
    julian_date_ut1: float,
) -> tuple[float, float, float]:
    """Rotate TEME position into the project ECEF approximation."""

    _require_finite_vector(position_km, "teme")
    return teme_to_ecef(position_km, gmst_radians(julian_date_ut1))


def relative_ecef_to_enu_km(
    relative_ecef_km: tuple[float, float, float],
    observer: GeodeticPosition,
) -> tuple[float, float, float]:
    """Rotate an ECEF relative vector into local east/north/up coordinates."""

    _require_finite_vector(relative_ecef_km, "relative_ecef")
    lat = math.radians(observer.latitude_deg)
    lon = math.radians(observer.longitude_deg)
    sin_lat = math.sin(lat)
    cos_lat = math.cos(lat)
    sin_lon = math.sin(lon)
    cos_lon = math.cos(lon)
    dx, dy, dz = relative_ecef_km
    east = -sin_lon * dx + cos_lon * dy
    north = -sin_lat * cos_lon * dx - sin_lat * sin_lon * dy + cos_lat * dz
    up = cos_lat * cos_lon * dx + cos_lat * sin_lon * dy + sin_lat * dz
    _require_finite_vector((east, north, up), "enu")
    return (east, north, up)


def enu_to_azimuth_elevation_range(
    enu_km: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Convert an ENU relative vector to azimuth, elevation, and slant range."""

    _require_finite_vector(enu_km, "enu")
    east, north, up = enu_km
    horizontal = math.hypot(east, north)
    slant_range = math.sqrt(east * east + north * north + up * up)
    if slant_range <= 0.0:
        raise ValueError("slant range must be positive")
    azimuth = math.degrees(math.atan2(east, north)) % 360.0
    elevation = math.degrees(math.atan2(up, horizontal))
    if azimuth >= 360.0:
        azimuth = 0.0
    return (azimuth, elevation, slant_range)


def look_angles_from_ecef(
    satellite_ecef_km: tuple[float, float, float],
    observer: GeodeticPosition,
) -> tuple[float, float, float]:
    """Compute observer-relative azimuth/elevation/range from a satellite ECEF position."""

    observer_ecef = geodetic_to_ecef_km(observer)
    relative = (
        satellite_ecef_km[0] - observer_ecef[0],
        satellite_ecef_km[1] - observer_ecef[1],
        satellite_ecef_km[2] - observer_ecef[2],
    )
    enu = relative_ecef_to_enu_km(relative, observer)
    return enu_to_azimuth_elevation_range(enu)


def _require_finite_vector(values: tuple[float, float, float], name: str) -> None:
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{name} vector components must be finite")
