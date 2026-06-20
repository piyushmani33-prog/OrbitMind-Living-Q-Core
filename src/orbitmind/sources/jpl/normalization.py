"""Deterministic normalization of JPL responses into OrbitMind domain models.

Pure functions applying reproducible conversions to source data (no network, no
randomness). Missing values become ``None`` — never zero. JPL response structures
do not leave this package; only domain models are returned.
"""

from __future__ import annotations

from datetime import UTC, datetime

from orbitmind.objects.models import (
    CatalogIdentifier,
    ObjectAlias,
    ObjectClassification,
    SpaceObjectIdentity,
    SpaceObjectKind,
)
from orbitmind.objects.orbits import SmallBodyOrbitElements
from orbitmind.smallbody.models import (
    CloseApproachBody,
    CloseApproachDistance,
    CloseApproachRecord,
    CloseApproachVelocity,
    HazardDesignation,
    JplSourceRecord,
    ObservationArc,
    OrbitSolutionMetadata,
    OrbitUncertainty,
    SmallBodyClassification,
    SmallBodyIdentity,
    SmallBodyOrbit,
    SmallBodyPhysicalProperties,
    SmallBodyRecord,
)
from orbitmind.smallbody.query import SmallBodyQueryItem
from orbitmind.sources.errors import SourceSchemaError
from orbitmind.sources.jpl.cad_models import CadResponse
from orbitmind.sources.jpl.query_models import SbdbQueryResponse
from orbitmind.sources.jpl.sbdb_models import SbdbResponse
from orbitmind.sources.models import SourceFreshnessAssessment

_CAD_DATE_FORMATS = ("%Y-%b-%d %H:%M", "%Y-%b-%d %H:%M:%S", "%Y-%b-%d")


def _to_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _to_bool_yn(value: str | None) -> bool | None:
    if value is None or value == "":
        return None
    if value in ("Y", "y", "1", "true", "True"):
        return True
    if value in ("N", "n", "0", "false", "False"):
        return False
    return None


def _kind_from_jpl(kind_code: str | None, fullname: str | None) -> SpaceObjectKind:
    if kind_code in ("cn", "cu"):
        return SpaceObjectKind.COMET
    if kind_code in ("an", "au"):
        return SpaceObjectKind.ASTEROID
    name = (fullname or "").strip()
    if name[:2] in ("P/", "C/", "D/", "X/") or "/" in name.split(" ")[0]:
        return SpaceObjectKind.COMET
    return SpaceObjectKind.ASTEROID


def normalize_sbdb(
    response: SbdbResponse,
    *,
    requested_identifier: str,
    source_id: str,
    fetched_at: datetime | None,
    checksum: str,
    schema_version: str,
    policy_version: str,
    freshness: SourceFreshnessAssessment,
) -> SmallBodyRecord:
    """Normalize a FOUND SBDB response into a ``SmallBodyRecord``."""
    obj = response.object
    if obj is None:  # pragma: no cover - guarded by caller
        raise SourceSchemaError("SBDB response has no object to normalize")

    elems = {e.name: e.value for e in (response.orbit.elements if response.orbit else [])}
    orbit_block = response.orbit
    kind = _kind_from_jpl(obj.kind, obj.fullname)
    spk = str(obj.spkid) if obj.spkid is not None else (obj.des or requested_identifier)
    full_name = obj.fullname or obj.shortname or obj.des or requested_identifier
    numbered = obj.kind in ("an", "cn")

    elements = SmallBodyOrbitElements(
        epoch_jd=_to_float(orbit_block.epoch) if orbit_block else None,
        eccentricity=_to_float(elems.get("e")),
        semimajor_axis_au=_to_float(elems.get("a")),
        perihelion_distance_au=_to_float(elems.get("q")),
        aphelion_distance_au=_to_float(elems.get("ad")),
        inclination_deg=_to_float(elems.get("i")),
        ascending_node_deg=_to_float(elems.get("om")),
        arg_perihelion_deg=_to_float(elems.get("w")),
        mean_anomaly_deg=_to_float(elems.get("ma")),
        orbital_period_days=_to_float(elems.get("per")),
        mean_motion_deg_per_day=_to_float(elems.get("n")),
        time_of_perihelion_jd=_to_float(elems.get("tp")),
    )
    solution = OrbitSolutionMetadata(
        epoch_jd=elements.epoch_jd,
        solution_date=orbit_block.soln_date if orbit_block else None,
        condition_code=orbit_block.condition_code if orbit_block else None,
        moid_au=_to_float(orbit_block.moid) if orbit_block else None,
        rms=_to_float(orbit_block.rms) if orbit_block else None,
    )
    arc = ObservationArc(
        first_observation=orbit_block.first_obs if orbit_block else None,
        last_observation=orbit_block.last_obs if orbit_block else None,
        arc_days=_to_float(orbit_block.data_arc) if orbit_block else None,
        n_observations_used=orbit_block.n_obs_used if orbit_block else None,
    )
    phys = {p.name: p.value for p in response.phys_par}
    physical = SmallBodyPhysicalProperties(
        absolute_magnitude_h=_to_float(phys.get("H")),
        diameter_km=_to_float(phys.get("diameter")),
        albedo=_to_float(phys.get("albedo")),
        rotation_period_h=_to_float(phys.get("rot_per")),
    )
    oclass = obj.orbit_class
    classification = SmallBodyClassification(
        orbit_class_code=oclass.code if oclass else None,
        orbit_class_name=oclass.name if oclass else None,
    )
    hazard = HazardDesignation(
        near_earth_object_source=obj.neo, potentially_hazardous_source=obj.pha
    )
    aliases = [
        ObjectAlias(alias=a, kind=k)
        for a, k in ((obj.shortname, "shortname"), (obj.des, "designation"))
        if a
    ]
    identity = SpaceObjectIdentity(
        kind=kind,
        canonical_name=full_name,
        primary_identifier=CatalogIdentifier(catalog="jpl-spk", identifier=spk),
        designation=obj.des,
        number=obj.des if numbered else None,
        aliases=aliases,
        classifications=[
            ObjectClassification(
                scheme="jpl-orbit-class",
                code=oclass.code if oclass else None,
                name=oclass.name if oclass else None,
            )
        ],
    )
    source = JplSourceRecord(
        source_id=source_id,
        source_record_id=spk,
        requested_identifier=requested_identifier,
        signature_version=response.signature.version if response.signature else None,
        fetched_at=fetched_at,
        checksum=checksum,
        schema_version=schema_version,
        policy_version=policy_version,
    )
    return SmallBodyRecord(
        identity=identity,
        small_body_identity=SmallBodyIdentity(
            kind=kind,
            full_name=full_name,
            designation=obj.des,
            number=obj.des if numbered else None,
            spk_id=spk,
        ),
        orbit=SmallBodyOrbit(
            elements=elements,
            solution=solution,
            uncertainty=OrbitUncertainty(condition_code=solution.condition_code),
            observation_arc=arc,
        ),
        physical=physical,
        classification=classification,
        hazard=hazard,
        source=source,
        freshness=freshness,
    )


def normalize_query(
    response: SbdbQueryResponse, *, limit: int
) -> tuple[list[SmallBodyQueryItem], int, bool]:
    """Normalize an SBDB query response into items + (total_reported, truncated)."""
    index = {name: i for i, name in enumerate(response.fields)}

    def cell(row: list[str | None], field: str) -> str | None:
        i = index.get(field)
        return row[i] if i is not None and i < len(row) else None

    items: list[SmallBodyQueryItem] = []
    for row in response.data[:limit]:
        items.append(
            SmallBodyQueryItem(
                full_name=cell(row, "full_name"),
                designation=cell(row, "pdes"),
                near_earth_object_source=_to_bool_yn(cell(row, "neo")),
                potentially_hazardous_source=_to_bool_yn(cell(row, "pha")),
                orbit_class_code=cell(row, "class"),
                semimajor_axis_au=_to_float(cell(row, "a")),
                eccentricity=_to_float(cell(row, "e")),
                inclination_deg=_to_float(cell(row, "i")),
                perihelion_distance_au=_to_float(cell(row, "q")),
                absolute_magnitude_h=_to_float(cell(row, "H")),
                diameter_km=_to_float(cell(row, "diameter")),
                moid_au=_to_float(cell(row, "moid")),
            )
        )
    total = response.count or len(response.data)
    truncated = total > len(items)
    return items, total, truncated


def _parse_cad_date(value: str | None) -> datetime:
    if not value:
        raise SourceSchemaError("close-approach record has no date")
    for fmt in _CAD_DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise SourceSchemaError(f"unparseable close-approach date '{value}'")


def normalize_cad(
    response: CadResponse,
    *,
    default_body: str,
    source: JplSourceRecord,
    freshness: SourceFreshnessAssessment,
    limit: int,
) -> tuple[list[CloseApproachRecord], int, bool]:
    """Normalize a CAD response into close-approach records + (total, truncated)."""
    index = {name: i for i, name in enumerate(response.fields)}

    def cell(row: list[str | None], field: str) -> str | None:
        i = index.get(field)
        return row[i] if i is not None and i < len(row) else None

    records: list[CloseApproachRecord] = []
    for row in response.data[:limit]:
        designation = cell(row, "des") or "unknown"
        records.append(
            CloseApproachRecord(
                designation=designation,
                full_name=cell(row, "fullname"),
                orbit_id=cell(row, "orbit_id"),
                time_utc=_parse_cad_date(cell(row, "cd")),
                time_jd=_to_float(cell(row, "jd")),
                body=CloseApproachBody(name=cell(row, "body") or default_body),
                distance=CloseApproachDistance(
                    nominal_au=_to_float(cell(row, "dist")),
                    minimum_au=_to_float(cell(row, "dist_min")),
                    maximum_au=_to_float(cell(row, "dist_max")),
                ),
                velocity=CloseApproachVelocity(
                    relative_kms=_to_float(cell(row, "v_rel")),
                    infinity_kms=_to_float(cell(row, "v_inf")),
                ),
                absolute_magnitude_h=_to_float(cell(row, "h")),
                time_sigma=cell(row, "t_sigma_f"),
                source=source,
                freshness=freshness,
            )
        )
    total = response.count or len(response.data)
    truncated = total > len(records)
    return records, total, truncated
