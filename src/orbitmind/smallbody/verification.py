"""Deterministic validation of small-body records (never raises on bad data).

Passing these checks proves the record is internally consistent with the
implemented rules — NOT that the orbit is correct.
"""

from __future__ import annotations

import math

from orbitmind.objects.models import ObjectVerificationStatus, SpaceObjectKind
from orbitmind.smallbody.models import CloseApproachRecord, SmallBodyRecord
from orbitmind.verification.models import (
    CheckCategory,
    FindingStatus,
    Severity,
    VerificationFinding,
)

_PASS = FindingStatus.PASSED
_FAIL = FindingStatus.FAILED
_SKIP = FindingStatus.SKIPPED


def _finite(*values: float | None) -> bool:
    return all(v is not None and math.isfinite(v) for v in values)


def _finding(
    check_id: str,
    *,
    ok: bool,
    severity: Severity,
    category: CheckCategory,
    yes: str,
    no: str,
    values: dict[str, object] | None = None,
    units: str = "",
    skipped: bool = False,
) -> VerificationFinding:
    status = _SKIP if skipped else (_PASS if ok else _FAIL)
    return VerificationFinding(
        check_id=check_id,
        severity=severity,
        status=status,
        explanation=(yes if ok else no),
        values=values or {},
        category=category,
        units=units,
    )


class SmallBodyVerificationService:
    """Runs deterministic consistency checks over a small-body record."""

    def verify(self, record: SmallBodyRecord) -> list[VerificationFinding]:
        e = record.orbit.elements
        kind = record.identity.kind
        findings = [
            self._identifier_completeness(record),
            self._provenance_completeness(record),
            self._missing_critical_fields(record),
            self._finite_values(record),
            self._eccentricity_bounds(record),
            self._semimajor_axis(record),
            self._perihelion_aphelion(record),
            self._period_consistency(record),
            self._angular_bounds(record),
            self._epoch_parsing(record),
            self._observation_arc(record),
            self._diameter_ordering(record),
            self._physical_units(record),
            self._freshness_status(record),
            self._schema_version(record),
            self._orbit_type_supported(record),
        ]
        _ = (e, kind)
        return findings

    def verify_close_approaches(
        self, records: list[CloseApproachRecord]
    ) -> list[VerificationFinding]:
        findings: list[VerificationFinding] = []
        bad_dist = [i for i, r in enumerate(records) if (r.distance.nominal_au or 0) < 0]
        findings.append(
            _finding(
                "ca_distance_positive",
                ok=not bad_dist,
                severity=Severity.ERROR,
                category=CheckCategory.MATHEMATICS,
                yes="all close-approach distances are non-negative",
                no="negative close-approach distance found",
                values={"bad_indices": bad_dist},
                units="au",
            )
        )
        bad_vel = [
            i
            for i, r in enumerate(records)
            if r.velocity.relative_kms is not None and r.velocity.relative_kms < 0
        ]
        findings.append(
            _finding(
                "ca_velocity_positive",
                ok=not bad_vel,
                severity=Severity.ERROR,
                category=CheckCategory.MATHEMATICS,
                yes="all relative velocities are non-negative",
                no="negative relative velocity found",
                values={"bad_indices": bad_vel},
                units="km/s",
            )
        )
        times = [r.time_utc for r in records]
        ordered = all(times[i] <= times[i + 1] for i in range(len(times) - 1))
        findings.append(
            _finding(
                "ca_chronological_order",
                ok=ordered,
                severity=Severity.WARNING,
                category=CheckCategory.STRUCTURE,
                yes="close-approach records are in chronological order",
                no="close-approach records are not chronologically ordered",
                values={"count": len(times)},
            )
        )
        return findings

    # ---- individual small-body checks --------------------------------------
    @staticmethod
    def _identifier_completeness(r: SmallBodyRecord) -> VerificationFinding:
        ident = r.small_body_identity
        ok = bool(ident.full_name and (ident.spk_id or ident.designation))
        return _finding(
            "identifier_completeness",
            ok=ok,
            severity=Severity.ERROR,
            category=CheckCategory.PROVENANCE,
            yes="object identity is complete",
            no="object identity is incomplete",
            values={"spk_id": ident.spk_id, "designation": ident.designation},
        )

    @staticmethod
    def _provenance_completeness(r: SmallBodyRecord) -> VerificationFinding:
        s = r.source
        ok = bool(s.source_record_id and s.checksum and s.schema_version)
        return _finding(
            "provenance_completeness",
            ok=ok,
            severity=Severity.ERROR,
            category=CheckCategory.PROVENANCE,
            yes="source provenance is complete",
            no="source provenance is incomplete",
            values={"source_id": s.source_id, "has_checksum": bool(s.checksum)},
        )

    @staticmethod
    def _missing_critical_fields(r: SmallBodyRecord) -> VerificationFinding:
        e = r.orbit.elements
        ok = any(
            v is not None for v in (e.semimajor_axis_au, e.eccentricity, e.perihelion_distance_au)
        )
        return _finding(
            "missing_critical_fields",
            ok=ok,
            severity=Severity.CRITICAL,
            category=CheckCategory.STRUCTURE,
            yes="critical orbital elements are present",
            no="all critical orbital elements are missing",
        )

    @staticmethod
    def _finite_values(r: SmallBodyRecord) -> VerificationFinding:
        e = r.orbit.elements
        candidates = [
            v
            for v in (
                e.eccentricity,
                e.semimajor_axis_au,
                e.inclination_deg,
                e.perihelion_distance_au,
                e.ascending_node_deg,
                e.arg_perihelion_deg,
            )
            if v is not None
        ]
        ok = all(math.isfinite(v) for v in candidates)
        return _finding(
            "finite_values",
            ok=ok,
            severity=Severity.CRITICAL,
            category=CheckCategory.MATHEMATICS,
            yes="all present orbital values are finite",
            no="found non-finite orbital values",
        )

    @staticmethod
    def _eccentricity_bounds(r: SmallBodyRecord) -> VerificationFinding:
        e = r.orbit.elements.eccentricity
        if e is None:
            return _finding(
                "eccentricity_bounds",
                ok=True,
                severity=Severity.ERROR,
                category=CheckCategory.MATHEMATICS,
                yes="eccentricity not provided",
                no="",
                skipped=True,
            )
        # e >= 0 always; e >= 1 is hyperbolic (valid for comets, suspicious for asteroids).
        if e < 0:
            ok, severity = False, Severity.CRITICAL
        elif e >= 1.0 and r.identity.kind is SpaceObjectKind.ASTEROID:
            ok, severity = False, Severity.WARNING
        else:
            ok, severity = True, Severity.ERROR
        return _finding(
            "eccentricity_bounds",
            ok=ok,
            severity=severity,
            category=CheckCategory.MATHEMATICS,
            yes="eccentricity within expected bounds",
            no="eccentricity outside expected bounds",
            values={"e": e},
        )

    @staticmethod
    def _semimajor_axis(r: SmallBodyRecord) -> VerificationFinding:
        a = r.orbit.elements.semimajor_axis_au
        if a is None or r.identity.kind is SpaceObjectKind.COMET:
            return _finding(
                "positive_semimajor_axis",
                ok=True,
                severity=Severity.ERROR,
                category=CheckCategory.MATHEMATICS,
                yes="semimajor axis check not applicable",
                no="",
                skipped=True,
            )
        return _finding(
            "positive_semimajor_axis",
            ok=a > 0,
            severity=Severity.ERROR,
            category=CheckCategory.MATHEMATICS,
            yes="semimajor axis is positive",
            no="semimajor axis is not positive",
            values={"a": a},
            units="au",
        )

    @staticmethod
    def _perihelion_aphelion(r: SmallBodyRecord) -> VerificationFinding:
        e = r.orbit.elements
        if not _finite(e.perihelion_distance_au, e.aphelion_distance_au):
            return _finding(
                "perihelion_aphelion_consistency",
                ok=True,
                severity=Severity.WARNING,
                category=CheckCategory.MATHEMATICS,
                yes="insufficient data for q/Q check",
                no="",
                skipped=True,
            )
        ok = (e.perihelion_distance_au or 0) <= (e.aphelion_distance_au or 0)
        return _finding(
            "perihelion_aphelion_consistency",
            ok=ok,
            severity=Severity.WARNING,
            category=CheckCategory.MATHEMATICS,
            yes="perihelion <= aphelion",
            no="perihelion > aphelion",
            values={"q": e.perihelion_distance_au, "ad": e.aphelion_distance_au},
            units="au",
        )

    @staticmethod
    def _period_consistency(r: SmallBodyRecord) -> VerificationFinding:
        e = r.orbit.elements
        a, per = e.semimajor_axis_au, e.orbital_period_days
        if not _finite(a, per) or (a or 0) <= 0:
            return _finding(
                "orbital_period_consistency",
                ok=True,
                severity=Severity.WARNING,
                category=CheckCategory.MATHEMATICS,
                yes="insufficient data for period check",
                no="",
                skipped=True,
            )
        expected = 365.25 * (a or 0) ** 1.5  # Kepler's third law, heliocentric (a in au)
        rel = abs((per or 0) - expected) / expected
        return _finding(
            "orbital_period_consistency",
            ok=rel < 0.05,
            severity=Severity.WARNING,
            category=CheckCategory.MATHEMATICS,
            yes="orbital period consistent with semimajor axis (Kepler III)",
            no="orbital period inconsistent with semimajor axis",
            values={"period_days": per, "expected_days": round(expected, 2)},
            units="days",
        )

    @staticmethod
    def _angular_bounds(r: SmallBodyRecord) -> VerificationFinding:
        e = r.orbit.elements
        bad = []
        if e.inclination_deg is not None and not 0.0 <= e.inclination_deg <= 180.0:
            bad.append("i")
        for name, val in (
            ("om", e.ascending_node_deg),
            ("w", e.arg_perihelion_deg),
            ("ma", e.mean_anomaly_deg),
        ):
            if val is not None and not -360.0 <= val <= 360.0:
                bad.append(name)
        return _finding(
            "angular_bounds",
            ok=not bad,
            severity=Severity.ERROR,
            category=CheckCategory.MATHEMATICS,
            yes="angular elements within bounds",
            no="angular elements out of bounds",
            values={"out_of_bounds": bad},
            units="degrees",
        )

    @staticmethod
    def _epoch_parsing(r: SmallBodyRecord) -> VerificationFinding:
        epoch = r.orbit.elements.epoch_jd
        ok = epoch is not None and math.isfinite(epoch) and epoch > 0
        return _finding(
            "epoch_parsing",
            ok=ok,
            severity=Severity.ERROR,
            category=CheckCategory.STRUCTURE,
            yes="orbit epoch parsed",
            no="orbit epoch missing/invalid",
            values={"epoch_jd": epoch},
            units="JD",
        )

    @staticmethod
    def _observation_arc(r: SmallBodyRecord) -> VerificationFinding:
        arc = r.orbit.observation_arc.arc_days
        ok = arc is None or arc >= 0
        return _finding(
            "observation_arc_validity",
            ok=ok,
            severity=Severity.WARNING,
            category=CheckCategory.STRUCTURE,
            yes="observation arc is valid",
            no="observation arc is negative",
            values={"arc_days": arc},
            units="days",
        )

    @staticmethod
    def _diameter_ordering(r: SmallBodyRecord) -> VerificationFinding:
        p = r.physical
        if not _finite(p.diameter_min_km, p.diameter_max_km):
            return _finding(
                "diameter_range_ordering",
                ok=True,
                severity=Severity.WARNING,
                category=CheckCategory.MATHEMATICS,
                yes="no diameter range to order",
                no="",
                skipped=True,
            )
        ok = (p.diameter_min_km or 0) <= (p.diameter_max_km or 0)
        return _finding(
            "diameter_range_ordering",
            ok=ok,
            severity=Severity.WARNING,
            category=CheckCategory.MATHEMATICS,
            yes="diameter min <= max",
            no="diameter min > max",
            units="km",
        )

    @staticmethod
    def _physical_units(r: SmallBodyRecord) -> VerificationFinding:
        ok = bool(r.physical.units)
        return _finding(
            "physical_property_units",
            ok=ok,
            severity=Severity.WARNING,
            category=CheckCategory.POLICY,
            yes="physical-property units present",
            no="physical-property units missing",
        )

    @staticmethod
    def _freshness_status(r: SmallBodyRecord) -> VerificationFinding:
        state = r.freshness.state.value
        ok = state not in ("invalid", "unavailable")
        return _finding(
            "freshness_status",
            ok=ok,
            severity=Severity.WARNING,
            category=CheckCategory.POLICY,
            yes="freshness status is usable",
            no="freshness status is invalid/unavailable",
            values={"freshness": state},
        )

    @staticmethod
    def _schema_version(r: SmallBodyRecord) -> VerificationFinding:
        ok = bool(r.source.schema_version)
        return _finding(
            "schema_version",
            ok=ok,
            severity=Severity.WARNING,
            category=CheckCategory.POLICY,
            yes="schema version recorded",
            no="schema version missing",
            values={"schema_version": r.source.schema_version},
        )

    @staticmethod
    def _orbit_type_supported(r: SmallBodyRecord) -> VerificationFinding:
        ok = r.identity.kind in (SpaceObjectKind.ASTEROID, SpaceObjectKind.COMET)
        return _finding(
            "supported_orbit_type",
            ok=ok,
            severity=Severity.ERROR,
            category=CheckCategory.POLICY,
            yes="object kind is supported (asteroid/comet)",
            no="unsupported object kind for small-body model",
            values={"kind": r.identity.kind.value},
        )


def overall_status(findings: list[VerificationFinding]) -> ObjectVerificationStatus:
    """Roll findings up into an object verification status."""
    failed = [f for f in findings if f.status is FindingStatus.FAILED]
    if any(f.severity in (Severity.ERROR, Severity.CRITICAL) for f in failed):
        return ObjectVerificationStatus.FAILED
    if failed:
        return ObjectVerificationStatus.PASSED_WITH_WARNINGS
    return ObjectVerificationStatus.PASSED
