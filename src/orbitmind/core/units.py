"""Physical constants and unit labels (explicit, documented; SR-02).

Frames/units used by the orbital slice:
- Positions in the TEME frame, kilometres (km).
- Velocities in km/s.
- Geodetic latitude/longitude in degrees, altitude above the WGS-84 ellipsoid in km.
"""

from __future__ import annotations

from typing import Final

# WGS-84 ellipsoid
WGS84_A_KM: Final[float] = 6378.137  # semi-major axis (equatorial radius), km
WGS84_F: Final[float] = 1.0 / 298.257223563  # flattening
WGS84_B_KM: Final[float] = WGS84_A_KM * (1.0 - WGS84_F)  # semi-minor axis, km
WGS84_E2: Final[float] = WGS84_F * (2.0 - WGS84_F)  # first eccentricity squared

# Earth rotation
EARTH_ROTATION_RATE_RAD_S: Final[float] = 7.2921150e-5  # rad/s (sidereal)

# Sanity bounds for low-to-geostationary Earth orbits (km above ellipsoid)
ALTITUDE_MIN_KM: Final[float] = 80.0  # below this is effectively re-entry/decay
ALTITUDE_MAX_KM: Final[float] = 50_000.0  # comfortably beyond GEO (~35,786 km)

# Canonical unit labels recorded alongside values
UNITS: Final[dict[str, str]] = {
    "position": "km (TEME)",
    "velocity": "km/s (TEME)",
    "latitude": "degrees (geodetic, WGS-84)",
    "longitude": "degrees (geodetic, WGS-84)",
    "altitude": "km (above WGS-84 ellipsoid)",
    "time": "UTC (timezone-aware ISO-8601)",
}
