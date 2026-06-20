"""SQLAlchemy ORM models (the persistence schema).

These are deliberately separate from the Pydantic domain models. Binary images are
never stored here — only artifact metadata + filesystem paths (DATA_MODEL.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from orbitmind.persistence.database import Base, UTCDateTime


class MissionRow(Base):
    __tablename__ = "missions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    satellite_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16))
    raw_request: Mapped[dict[str, Any]] = mapped_column(JSON)
    normalized_request: Mapped[dict[str, Any]] = mapped_column(JSON)
    epistemic_status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class MissionInputRow(Base):
    __tablename__ = "mission_inputs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    key: Mapped[str] = mapped_column(String(64))
    value: Mapped[dict[str, Any]] = mapped_column(JSON)


class WorkflowRunRow(Base):
    __tablename__ = "workflow_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    workflow_name: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    steps: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class OrbitalSampleRow(Base):
    __tablename__ = "orbital_samples"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    ts: Mapped[datetime] = mapped_column(UTCDateTime)
    pos_x_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    pos_y_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    pos_z_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    vel_x_kmps: Mapped[float | None] = mapped_column(Float, nullable=True)
    vel_y_kmps: Mapped[float | None] = mapped_column(Float, nullable=True)
    vel_z_kmps: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    alt_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(8))
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_orbital_samples_mission_ts", "mission_id", "ts"),)


class VerificationFindingRow(Base):
    __tablename__ = "verification_findings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    check_id: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    explanation: Mapped[str] = mapped_column(Text)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ProvenanceRow(Base):
    __tablename__ = "provenance_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    subject_ref: Mapped[str] = mapped_column(String(64))
    source_ref: Mapped[str] = mapped_column(String(128))
    method: Mapped[str] = mapped_column(String(64))
    inputs_hash: Mapped[str] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)


class ArtifactRow(Base):
    __tablename__ = "artifact_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    type: Mapped[str] = mapped_column(String(32))
    path: Mapped[str] = mapped_column(String(255))
    sidecar_path: Mapped[str] = mapped_column(String(255))
    checksum: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


# --------------------------------------------------------------------------
# Phase 2 — sources, policies, fetches, cache, health, normalized elements
# --------------------------------------------------------------------------
class SourceDefinitionRow(Base):
    __tablename__ = "source_definitions"

    source_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SourcePolicyRow(Base):
    __tablename__ = "source_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("source_definitions.source_id"), index=True)
    policy_version: Mapped[str] = mapped_column(String(16))
    base_url: Mapped[str] = mapped_column(String(255))
    schema_format: Mapped[str] = mapped_column(String(32))
    schema_version: Mapped[str] = mapped_column(String(32))
    network_enabled: Mapped[bool] = mapped_column(Boolean)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)


class SourceFetchRow(Base):
    __tablename__ = "source_fetches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    cache_key: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(String(512))
    outcome: Mapped[str] = mapped_column(String(16))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    response_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    from_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class SourceCacheEntryRow(Base):
    __tablename__ = "source_cache_entries"

    cache_key: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(String(512))
    body_path: Mapped[str] = mapped_column(String(512))
    checksum: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(32))
    http_status: Mapped[int] = mapped_column(Integer)
    content_type: Mapped[str] = mapped_column(String(128))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    effective_epoch: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_failure_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceHealthEventRow(Base):
    __tablename__ = "source_health_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    health: Mapped[str] = mapped_column(String(16))
    detail: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class OrbitalElementRecordRow(Base):
    __tablename__ = "orbital_element_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    mission_id: Mapped[str | None] = mapped_column(
        ForeignKey("missions.id"), nullable=True, index=True
    )
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    satellite_id: Mapped[str] = mapped_column(String(64), index=True)
    norad_cat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_name: Mapped[str] = mapped_column(String(128))
    epoch: Mapped[datetime] = mapped_column(UTCDateTime)
    tle_line1: Mapped[str] = mapped_column(String(80))
    tle_line2: Mapped[str] = mapped_column(String(80))
    checksum: Mapped[str] = mapped_column(String(64))
    freshness_state: Mapped[str] = mapped_column(String(16))
    liveness: Mapped[str] = mapped_column(String(16))
    cache_status: Mapped[str] = mapped_column(String(16))
    policy_version: Mapped[str] = mapped_column(String(16))
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


# --------------------------------------------------------------------------
# Phase 3A — unified space objects + small-body (asteroid/comet) records
# --------------------------------------------------------------------------
class SpaceObjectRow(Base):
    __tablename__ = "space_objects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    canonical_name: Mapped[str] = mapped_column(String(255), index=True)
    primary_catalog: Mapped[str] = mapped_column(String(64))
    primary_identifier: Mapped[str] = mapped_column(String(128), index=True)
    designation: Mapped[str | None] = mapped_column(String(64), nullable=True)
    number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    source_record_id: Mapped[str] = mapped_column(String(128))
    requested_identifier: Mapped[str] = mapped_column(String(64))
    data_epoch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    freshness_state: Mapped[str] = mapped_column(String(16))
    liveness: Mapped[str] = mapped_column(String(16))
    cache_status: Mapped[str] = mapped_column(String(16))
    checksum: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(16))
    epistemic_status: Mapped[str] = mapped_column(String(32))
    verification_status: Mapped[str] = mapped_column(String(24))
    limitations: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class SpaceObjectIdentifierRow(Base):
    __tablename__ = "space_object_identifiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_object_id: Mapped[str] = mapped_column(ForeignKey("space_objects.id"), index=True)
    catalog: Mapped[str] = mapped_column(String(64))
    identifier: Mapped[str] = mapped_column(String(128))


class SpaceObjectAliasRow(Base):
    __tablename__ = "space_object_aliases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_object_id: Mapped[str] = mapped_column(ForeignKey("space_objects.id"), index=True)
    alias: Mapped[str] = mapped_column(String(255))
    kind: Mapped[str] = mapped_column(String(32))


class SmallBodyOrbitRow(Base):
    __tablename__ = "small_body_orbits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_object_id: Mapped[str] = mapped_column(ForeignKey("space_objects.id"), index=True)
    epoch_jd: Mapped[float | None] = mapped_column(Float, nullable=True)
    eccentricity: Mapped[float | None] = mapped_column(Float, nullable=True)
    semimajor_axis_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    perihelion_distance_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    aphelion_distance_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    inclination_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    ascending_node_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    arg_perihelion_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_anomaly_deg: Mapped[float | None] = mapped_column(Float, nullable=True)
    orbital_period_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    mean_motion_deg_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_of_perihelion_jd: Mapped[float | None] = mapped_column(Float, nullable=True)
    condition_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    solution_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    moid_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    rms: Mapped[float | None] = mapped_column(Float, nullable=True)
    arc_days: Mapped[float | None] = mapped_column(Float, nullable=True)
    n_obs_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    units: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    normalization_version: Mapped[str] = mapped_column(String(16))


class SmallBodyPhysicalRow(Base):
    __tablename__ = "small_body_physical_properties"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_object_id: Mapped[str] = mapped_column(ForeignKey("space_objects.id"), index=True)
    absolute_magnitude_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    diameter_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    diameter_min_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    diameter_max_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    albedo: Mapped[float | None] = mapped_column(Float, nullable=True)
    rotation_period_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    units: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class SmallBodyClassificationRow(Base):
    __tablename__ = "small_body_classifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    space_object_id: Mapped[str] = mapped_column(ForeignKey("space_objects.id"), index=True)
    orbit_class_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    orbit_class_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    near_earth_object_source: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    potentially_hazardous_source: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    spectral_type: Mapped[str | None] = mapped_column(String(16), nullable=True)


class SmallBodyQueryRunRow(Base):
    __tablename__ = "small_body_query_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(64), index=True)
    run_type: Mapped[str] = mapped_column(String(24))  # sbdb-query | cad
    params_key: Mapped[str] = mapped_column(String(512))
    total_reported: Mapped[int] = mapped_column(Integer)
    returned: Mapped[int] = mapped_column(Integer)
    truncated: Mapped[bool] = mapped_column(Boolean)
    freshness_state: Mapped[str] = mapped_column(String(16))
    checksum: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class CloseApproachRow(Base):
    __tablename__ = "close_approaches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    query_run_id: Mapped[str | None] = mapped_column(
        ForeignKey("small_body_query_runs.id"), nullable=True, index=True
    )
    designation: Mapped[str] = mapped_column(String(64), index=True)
    full_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    orbit_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    time_utc: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    time_jd: Mapped[float | None] = mapped_column(Float, nullable=True)
    body: Mapped[str] = mapped_column(String(16))
    dist_nominal_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    dist_min_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    dist_max_au: Mapped[float | None] = mapped_column(Float, nullable=True)
    v_rel_kms: Mapped[float | None] = mapped_column(Float, nullable=True)
    v_inf_kms: Mapped[float | None] = mapped_column(Float, nullable=True)
    absolute_magnitude_h: Mapped[float | None] = mapped_column(Float, nullable=True)
    time_sigma: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str] = mapped_column(String(64))
    checksum: Mapped[str] = mapped_column(String(64))
    schema_version: Mapped[str] = mapped_column(String(32))
    freshness_state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
