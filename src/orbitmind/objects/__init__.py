"""Unified space-object domain model (kind-agnostic identity + orbit representations).

Different object classes keep their scientific differences: satellites/debris use
TLE/GP + SGP4; asteroids/comets use heliocentric small-body elements; planets/moons
use ephemerides; stars/galaxies use fixed-sky catalogues; signals use time-series.
This module models that separation without collapsing it (ADR-0013).
"""
