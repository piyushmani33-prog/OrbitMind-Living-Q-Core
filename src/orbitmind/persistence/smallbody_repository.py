"""Repository for unified space objects + small-body records and close approaches."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.objects.models import CatalogIdentifier, ObjectAlias
from orbitmind.objects.orbits import SmallBodyOrbitElements
from orbitmind.persistence.models import (
    CloseApproachRow,
    SmallBodyClassificationRow,
    SmallBodyOrbitRow,
    SmallBodyPhysicalRow,
    SmallBodyQueryRunRow,
    SpaceObjectAliasRow,
    SpaceObjectIdentifierRow,
    SpaceObjectRow,
)
from orbitmind.smallbody.models import (
    CloseApproachDistance,
    CloseApproachResultSet,
    CloseApproachVelocity,
    HazardDesignation,
    ObservationArc,
    OrbitSolutionMetadata,
    OrbitUncertainty,
    SmallBodyClassification,
    SmallBodyOrbit,
    SmallBodyPhysicalProperties,
    SmallBodyRecord,
)

NORMALIZATION_VERSION = "jpl-normalize-1"


class StoredSpaceObject(BaseModel):
    """A persisted unified space object (read view)."""

    id: str
    kind: str
    canonical_name: str
    primary_identifier: CatalogIdentifier
    designation: str | None
    number: str | None
    aliases: list[ObjectAlias]
    source_id: str
    source_record_id: str
    requested_identifier: str
    data_epoch: str | None
    fetched_at: datetime | None
    freshness_state: str
    checksum: str
    schema_version: str
    policy_version: str
    epistemic_status: str
    verification_status: str
    limitations: str
    created_at: datetime


class StoredSmallBody(StoredSpaceObject):
    """A persisted small body (read view) with orbit/physical/classification/hazard."""

    orbit: SmallBodyOrbit
    physical: SmallBodyPhysicalProperties
    classification: SmallBodyClassification
    hazard: HazardDesignation


class StoredCloseApproach(BaseModel):
    """A persisted close approach (read view)."""

    id: str
    designation: str
    full_name: str | None
    orbit_id: str | None
    time_utc: datetime
    time_jd: float | None
    body: str
    distance: CloseApproachDistance
    velocity: CloseApproachVelocity
    absolute_magnitude_h: float | None
    source_id: str
    freshness_state: str


class SqlAlchemySmallBodyRepository:
    """Persists/reads unified objects, small-body records, and close approaches."""

    def __init__(self, session: Session) -> None:
        self._s = session

    # ---- write -------------------------------------------------------------
    def save_small_body(self, record: SmallBodyRecord) -> str:
        identity = record.identity
        self._s.add(
            SpaceObjectRow(
                id=record.id,
                kind=identity.kind.value,
                canonical_name=identity.canonical_name,
                primary_catalog=identity.primary_identifier.catalog,
                primary_identifier=identity.primary_identifier.identifier,
                designation=identity.designation,
                number=identity.number,
                source_id=record.source.source_id,
                source_record_id=record.source.source_record_id,
                requested_identifier=record.source.requested_identifier,
                data_epoch=record.freshness.data_epoch.isoformat()
                if record.freshness.data_epoch
                else None,
                fetched_at=record.freshness.fetched_at,
                freshness_state=record.freshness.state.value,
                liveness=record.freshness.liveness.value,
                cache_status=record.freshness.cache_status.value,
                checksum=record.source.checksum,
                schema_version=record.source.schema_version,
                policy_version=record.source.policy_version,
                epistemic_status=record.epistemic_status.value,
                verification_status=record.verification_status.value,
                limitations=record.limitations,
                created_at=utcnow(),
            )
        )
        self._s.add(
            SpaceObjectIdentifierRow(
                id=new_id(),
                space_object_id=record.id,
                catalog=identity.primary_identifier.catalog,
                identifier=identity.primary_identifier.identifier,
            )
        )
        for alias in identity.aliases:
            self._s.add(
                SpaceObjectAliasRow(
                    id=new_id(), space_object_id=record.id, alias=alias.alias, kind=alias.kind
                )
            )
        e = record.orbit.elements
        sol = record.orbit.solution
        arc = record.orbit.observation_arc
        self._s.add(
            SmallBodyOrbitRow(
                id=new_id(),
                space_object_id=record.id,
                epoch_jd=e.epoch_jd,
                eccentricity=e.eccentricity,
                semimajor_axis_au=e.semimajor_axis_au,
                perihelion_distance_au=e.perihelion_distance_au,
                aphelion_distance_au=e.aphelion_distance_au,
                inclination_deg=e.inclination_deg,
                ascending_node_deg=e.ascending_node_deg,
                arg_perihelion_deg=e.arg_perihelion_deg,
                mean_anomaly_deg=e.mean_anomaly_deg,
                orbital_period_days=e.orbital_period_days,
                mean_motion_deg_per_day=e.mean_motion_deg_per_day,
                time_of_perihelion_jd=e.time_of_perihelion_jd,
                condition_code=sol.condition_code,
                solution_date=sol.solution_date,
                moid_au=sol.moid_au,
                rms=sol.rms,
                arc_days=arc.arc_days,
                n_obs_used=arc.n_observations_used,
                units=dict(e.units),
                normalization_version=NORMALIZATION_VERSION,
            )
        )
        p = record.physical
        self._s.add(
            SmallBodyPhysicalRow(
                id=new_id(),
                space_object_id=record.id,
                absolute_magnitude_h=p.absolute_magnitude_h,
                diameter_km=p.diameter_km,
                diameter_min_km=p.diameter_min_km,
                diameter_max_km=p.diameter_max_km,
                albedo=p.albedo,
                rotation_period_h=p.rotation_period_h,
                units=dict(p.units),
            )
        )
        c = record.classification
        self._s.add(
            SmallBodyClassificationRow(
                id=new_id(),
                space_object_id=record.id,
                orbit_class_code=c.orbit_class_code,
                orbit_class_name=c.orbit_class_name,
                near_earth_object_source=record.hazard.near_earth_object_source,
                potentially_hazardous_source=record.hazard.potentially_hazardous_source,
                spectral_type=c.spectral_type,
            )
        )
        return record.id

    def save_close_approaches(
        self, result: CloseApproachResultSet, run_type: str, params_key: str
    ) -> str:
        run_id = new_id()
        self._s.add(
            SmallBodyQueryRunRow(
                id=run_id,
                source_id=result.source.source_id,
                run_type=run_type,
                params_key=params_key,
                total_reported=result.total_reported,
                returned=result.returned,
                truncated=result.truncated,
                freshness_state=result.freshness.state.value,
                checksum=result.source.checksum,
                fetched_at=result.source.fetched_at,
                created_at=utcnow(),
            )
        )
        # Ensure the query-run row exists before inserting nullable-FK close-approach rows;
        # PostgreSQL enforces query_run_id during flush.
        self._s.flush()
        for ca in result.records:
            self._s.add(
                CloseApproachRow(
                    id=ca.id,
                    query_run_id=run_id,
                    designation=ca.designation,
                    full_name=ca.full_name,
                    orbit_id=ca.orbit_id,
                    time_utc=ca.time_utc,
                    time_jd=ca.time_jd,
                    body=ca.body.name,
                    dist_nominal_au=ca.distance.nominal_au,
                    dist_min_au=ca.distance.minimum_au,
                    dist_max_au=ca.distance.maximum_au,
                    v_rel_kms=ca.velocity.relative_kms,
                    v_inf_kms=ca.velocity.infinity_kms,
                    absolute_magnitude_h=ca.absolute_magnitude_h,
                    time_sigma=ca.time_sigma,
                    source_id=ca.source.source_id,
                    checksum=ca.source.checksum,
                    schema_version=ca.source.schema_version,
                    freshness_state=ca.freshness.state.value,
                    created_at=utcnow(),
                )
            )
        return run_id

    def save_query_run(
        self,
        source_id: str,
        run_type: str,
        params_key: str,
        total: int,
        returned: int,
        truncated: bool,
        freshness_state: str,
        checksum: str,
        fetched_at: datetime | None,
    ) -> str:
        run_id = new_id()
        self._s.add(
            SmallBodyQueryRunRow(
                id=run_id,
                source_id=source_id,
                run_type=run_type,
                params_key=params_key,
                total_reported=total,
                returned=returned,
                truncated=truncated,
                freshness_state=freshness_state,
                checksum=checksum,
                fetched_at=fetched_at,
                created_at=utcnow(),
            )
        )
        return run_id

    # ---- read --------------------------------------------------------------
    def get_space_object(self, object_id: str) -> StoredSpaceObject | None:
        row = self._s.get(SpaceObjectRow, object_id)
        return self._to_space_object(row) if row is not None else None

    def list_space_objects(self, limit: int, offset: int) -> list[StoredSpaceObject]:
        stmt = (
            select(SpaceObjectRow)
            .order_by(SpaceObjectRow.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [self._to_space_object(r) for r in self._s.execute(stmt).scalars().all()]

    def count_space_objects(self) -> int:
        return int(self._s.execute(select(func.count()).select_from(SpaceObjectRow)).scalar_one())

    def get_small_body(self, object_id: str) -> StoredSmallBody | None:
        row = self._s.get(SpaceObjectRow, object_id)
        if row is None:
            return None
        orbit = (
            self._s.execute(
                select(SmallBodyOrbitRow).where(SmallBodyOrbitRow.space_object_id == object_id)
            )
            .scalars()
            .first()
        )
        phys = (
            self._s.execute(
                select(SmallBodyPhysicalRow).where(
                    SmallBodyPhysicalRow.space_object_id == object_id
                )
            )
            .scalars()
            .first()
        )
        cls = (
            self._s.execute(
                select(SmallBodyClassificationRow).where(
                    SmallBodyClassificationRow.space_object_id == object_id
                )
            )
            .scalars()
            .first()
        )
        if orbit is None:
            return None
        base = self._to_space_object(row)
        return StoredSmallBody(
            **base.model_dump(),
            orbit=_to_orbit(orbit),
            physical=_to_physical(phys),
            classification=_to_classification(cls),
            hazard=HazardDesignation(
                near_earth_object_source=cls.near_earth_object_source if cls else None,
                potentially_hazardous_source=cls.potentially_hazardous_source if cls else None,
            ),
        )

    def get_close_approaches_for_designation(self, designation: str) -> list[StoredCloseApproach]:
        stmt = (
            select(CloseApproachRow)
            .where(CloseApproachRow.designation == designation)
            .order_by(CloseApproachRow.time_utc)
        )
        return [_to_close_approach(r) for r in self._s.execute(stmt).scalars().all()]

    def _to_space_object(self, row: SpaceObjectRow) -> StoredSpaceObject:
        aliases = (
            self._s.execute(
                select(SpaceObjectAliasRow).where(SpaceObjectAliasRow.space_object_id == row.id)
            )
            .scalars()
            .all()
        )
        return StoredSpaceObject(
            id=row.id,
            kind=row.kind,
            canonical_name=row.canonical_name,
            primary_identifier=CatalogIdentifier(
                catalog=row.primary_catalog, identifier=row.primary_identifier
            ),
            designation=row.designation,
            number=row.number,
            aliases=[ObjectAlias(alias=a.alias, kind=a.kind) for a in aliases],
            source_id=row.source_id,
            source_record_id=row.source_record_id,
            requested_identifier=row.requested_identifier,
            data_epoch=row.data_epoch,
            fetched_at=row.fetched_at,
            freshness_state=row.freshness_state,
            checksum=row.checksum,
            schema_version=row.schema_version,
            policy_version=row.policy_version,
            epistemic_status=row.epistemic_status,
            verification_status=row.verification_status,
            limitations=row.limitations,
            created_at=row.created_at,
        )


def _to_orbit(row: SmallBodyOrbitRow) -> SmallBodyOrbit:
    return SmallBodyOrbit(
        elements=SmallBodyOrbitElements(
            epoch_jd=row.epoch_jd,
            eccentricity=row.eccentricity,
            semimajor_axis_au=row.semimajor_axis_au,
            perihelion_distance_au=row.perihelion_distance_au,
            aphelion_distance_au=row.aphelion_distance_au,
            inclination_deg=row.inclination_deg,
            ascending_node_deg=row.ascending_node_deg,
            arg_perihelion_deg=row.arg_perihelion_deg,
            mean_anomaly_deg=row.mean_anomaly_deg,
            orbital_period_days=row.orbital_period_days,
            mean_motion_deg_per_day=row.mean_motion_deg_per_day,
            time_of_perihelion_jd=row.time_of_perihelion_jd,
        ),
        solution=OrbitSolutionMetadata(
            epoch_jd=row.epoch_jd,
            solution_date=row.solution_date,
            condition_code=row.condition_code,
            moid_au=row.moid_au,
            rms=row.rms,
        ),
        uncertainty=OrbitUncertainty(condition_code=row.condition_code),
        observation_arc=ObservationArc(arc_days=row.arc_days, n_observations_used=row.n_obs_used),
    )


def _to_physical(row: SmallBodyPhysicalRow | None) -> SmallBodyPhysicalProperties:
    if row is None:
        return SmallBodyPhysicalProperties()
    return SmallBodyPhysicalProperties(
        absolute_magnitude_h=row.absolute_magnitude_h,
        diameter_km=row.diameter_km,
        diameter_min_km=row.diameter_min_km,
        diameter_max_km=row.diameter_max_km,
        albedo=row.albedo,
        rotation_period_h=row.rotation_period_h,
    )


def _to_classification(row: SmallBodyClassificationRow | None) -> SmallBodyClassification:
    if row is None:
        return SmallBodyClassification()
    return SmallBodyClassification(
        orbit_class_code=row.orbit_class_code,
        orbit_class_name=row.orbit_class_name,
        spectral_type=row.spectral_type,
    )


def _to_close_approach(row: CloseApproachRow) -> StoredCloseApproach:
    return StoredCloseApproach(
        id=row.id,
        designation=row.designation,
        full_name=row.full_name,
        orbit_id=row.orbit_id,
        time_utc=row.time_utc,
        time_jd=row.time_jd,
        body=row.body,
        distance=CloseApproachDistance(
            nominal_au=row.dist_nominal_au,
            minimum_au=row.dist_min_au,
            maximum_au=row.dist_max_au,
        ),
        velocity=CloseApproachVelocity(relative_kms=row.v_rel_kms, infinity_kms=row.v_inf_kms),
        absolute_magnitude_h=row.absolute_magnitude_h,
        source_id=row.source_id,
        freshness_state=row.freshness_state,
    )
