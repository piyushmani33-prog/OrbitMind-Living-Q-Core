"""Coordinate transforms: TEME -> ECEF -> geodetic (WGS-84).

Deterministic, dependency-free scalar math (SR-01). Precision note: we apply the
Earth-rotation (GMST) rotation only and ignore polar motion, nutation, and the
equation of equinoxes. This is adequate for demonstration-scale ground tracks and
altitude; sub-kilometre frame precision is out of scope for Phase 1 (ADR-0007).
"""

from __future__ import annotations

import math

from orbitmind.core.units import WGS84_A_KM, WGS84_E2


def gmst_radians(jd_ut1: float) -> float:
    """Greenwich Mean Sidereal Time (radians) from a UT1 Julian Date.

    Uses the IAU-1982 GMST polynomial. UT1 is approximated by UTC (sub-second
    difference, negligible at this precision).
    """
    t = (jd_ut1 - 2451545.0) / 36525.0
    gmst_sec = (
        67310.54841
        + (876600.0 * 3600.0 + 8640184.812866) * t
        + 0.093104 * t * t
        - 6.2e-6 * t * t * t
    )
    # 86400 sidereal seconds == 360 degrees == 2*pi radians.
    gmst_deg = (gmst_sec / 240.0) % 360.0
    return math.radians(gmst_deg)


def teme_to_ecef(
    position_km: tuple[float, float, float], gmst: float
) -> tuple[float, float, float]:
    """Rotate a TEME position into an Earth-fixed (PEF/ECEF) frame by GMST."""
    x, y, z = position_km
    cos_g = math.cos(gmst)
    sin_g = math.sin(gmst)
    x_ecef = cos_g * x + sin_g * y
    y_ecef = -sin_g * x + cos_g * y
    return (x_ecef, y_ecef, z)


def ecef_to_geodetic(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert ECEF (km) to geodetic latitude/longitude (deg) and altitude (km).

    Iterative Bowring-style solution against the WGS-84 ellipsoid.
    """
    a = WGS84_A_KM
    e2 = WGS84_E2
    lon = math.atan2(y, x)
    p = math.hypot(x, y)

    if p == 0.0:  # at a pole
        lat = math.copysign(math.pi / 2.0, z)
        alt = abs(z) - a * math.sqrt(1.0 - e2)
        return (math.degrees(lat), math.degrees(lon), alt)

    lat = math.atan2(z, p * (1.0 - e2))
    n = a
    alt = 0.0
    for _ in range(8):
        sin_lat = math.sin(lat)
        n = a / math.sqrt(1.0 - e2 * sin_lat * sin_lat)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1.0 - e2 * n / (n + alt)))

    lon_deg = (math.degrees(lon) + 180.0) % 360.0 - 180.0
    return (math.degrees(lat), lon_deg, alt)


def teme_to_geodetic(
    position_km: tuple[float, float, float], jd_ut1: float
) -> tuple[float, float, float]:
    """Full TEME -> geodetic (lat_deg, lon_deg, alt_km) at a given UT1 Julian Date."""
    gmst = gmst_radians(jd_ut1)
    x, y, z = teme_to_ecef(position_km, gmst)
    return ecef_to_geodetic(x, y, z)
