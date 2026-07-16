"""Repository for Phase 2 source entities (fetches, cache, health, elements).

Domain code depends on the :class:`SourceRepository` Protocol. Row<->domain mapping
is internal. Raw payloads are not stored here — only metadata + checksum + the
relative cache path (the body lives under the controlled cache directory).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.persistence.models import (
    OrbitalElementRecordRow,
    SourceCacheEntryRow,
    SourceDefinitionRow,
    SourceFetchRow,
    SourceHealthEventRow,
    SourcePolicyRow,
)
from orbitmind.sources.models import (
    FetchOutcome,
    MissionSourceData,
    OrbitalElementRecord,
    SourceCacheRecord,
    SourceDefinition,
    SourceFetchRecord,
    SourceHealth,
)


class SourceRepository(Protocol):
    """Persistence boundary for source operations."""

    def sync_definition(self, definition: SourceDefinition) -> None: ...
    def add_fetch(self, record: SourceFetchRecord) -> None: ...
    def get_cache_entry(self, cache_key: str) -> SourceCacheRecord | None: ...
    def upsert_cache_entry(self, record: SourceCacheRecord) -> None: ...
    def list_cache_for_source(self, source_id: str) -> list[SourceCacheRecord]: ...
    def add_health_event(self, source_id: str, health: SourceHealth, detail: str) -> None: ...
    def last_fetch_outcomes(
        self, source_id: str
    ) -> tuple[datetime | None, datetime | None, str | None]: ...
    def add_element_record(
        self, record: OrbitalElementRecord, mission_id: str | None, policy_version: str
    ) -> None: ...
    def get_mission_source_data(self, mission_id: str) -> MissionSourceData | None: ...


class SqlAlchemySourceRepository:
    """SQLAlchemy-backed :class:`SourceRepository`."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def sync_definition(self, definition: SourceDefinition) -> None:
        now: datetime | None = None

        def sync_time() -> datetime:
            nonlocal now
            if now is None:
                now = utcnow()
            return now

        row = self._s.get(SourceDefinitionRow, definition.source_id)
        if row is None:
            self._s.add(
                SourceDefinitionRow(
                    source_id=definition.source_id,
                    name=definition.name,
                    kind=definition.kind.value,
                    description=definition.description,
                    enabled=definition.enabled,
                    updated_at=sync_time(),
                )
            )
        else:
            definition_changed = False
            if row.name != definition.name:
                row.name = definition.name
                definition_changed = True
            if row.kind != definition.kind.value:
                row.kind = definition.kind.value
                definition_changed = True
            if row.description != definition.description:
                row.description = definition.description
                definition_changed = True
            if row.enabled != definition.enabled:
                row.enabled = definition.enabled
                definition_changed = True
            if definition_changed:
                row.updated_at = sync_time()

        policy = definition.policy
        existing = (
            self._s.execute(
                select(SourcePolicyRow).where(SourcePolicyRow.source_id == definition.source_id)
            )
            .scalars()
            .first()
        )
        snapshot = policy.model_dump(mode="json")
        if existing is None:
            self._s.add(
                SourcePolicyRow(
                    id=new_id(),
                    source_id=policy.source_id,
                    policy_version=policy.policy_version,
                    base_url=policy.base_url,
                    schema_format=policy.schema_format.value,
                    schema_version=policy.schema_version,
                    network_enabled=policy.network_enabled,
                    snapshot=snapshot,
                    recorded_at=sync_time(),
                )
            )
        else:
            policy_changed = False
            if existing.policy_version != policy.policy_version:
                existing.policy_version = policy.policy_version
                policy_changed = True
            if existing.base_url != policy.base_url:
                existing.base_url = policy.base_url
                policy_changed = True
            if existing.schema_format != policy.schema_format.value:
                existing.schema_format = policy.schema_format.value
                policy_changed = True
            if existing.schema_version != policy.schema_version:
                existing.schema_version = policy.schema_version
                policy_changed = True
            if existing.network_enabled != policy.network_enabled:
                existing.network_enabled = policy.network_enabled
                policy_changed = True
            if existing.snapshot != snapshot:
                existing.snapshot = snapshot
                policy_changed = True
            if policy_changed:
                existing.recorded_at = sync_time()

    def add_fetch(self, record: SourceFetchRecord) -> None:
        self._s.add(
            SourceFetchRow(
                id=record.id,
                source_id=record.source_id,
                cache_key=record.cache_key,
                url=record.url,
                outcome=record.outcome.value,
                http_status=record.http_status,
                content_type=record.content_type,
                response_bytes=record.response_bytes,
                checksum=record.checksum,
                schema_version=record.schema_version,
                from_cache=record.from_cache,
                error=record.error,
                requested_at=record.requested_at,
                completed_at=record.completed_at,
            )
        )

    def get_cache_entry(self, cache_key: str) -> SourceCacheRecord | None:
        row = self._s.get(SourceCacheEntryRow, cache_key)
        return _row_to_cache(row) if row is not None else None

    def upsert_cache_entry(self, record: SourceCacheRecord) -> None:
        row = self._s.get(SourceCacheEntryRow, record.cache_key)
        if row is None:
            self._s.add(
                SourceCacheEntryRow(
                    cache_key=record.cache_key,
                    source_id=record.source_id,
                    url=record.url,
                    body_path=record.body_path,
                    checksum=record.checksum,
                    schema_version=record.schema_version,
                    http_status=record.http_status,
                    content_type=record.content_type,
                    fetched_at=record.fetched_at,
                    expires_at=record.expires_at,
                    effective_epoch=record.effective_epoch,
                    last_success_at=record.last_success_at,
                    last_failure_at=record.last_failure_at,
                    failure_reason=record.failure_reason,
                )
            )
        else:
            row.url = record.url
            row.body_path = record.body_path
            row.checksum = record.checksum
            row.schema_version = record.schema_version
            row.http_status = record.http_status
            row.content_type = record.content_type
            row.fetched_at = record.fetched_at
            row.expires_at = record.expires_at
            row.effective_epoch = record.effective_epoch
            row.last_success_at = record.last_success_at
            row.last_failure_at = record.last_failure_at
            row.failure_reason = record.failure_reason

    def list_cache_for_source(self, source_id: str) -> list[SourceCacheRecord]:
        stmt = select(SourceCacheEntryRow).where(SourceCacheEntryRow.source_id == source_id)
        return [_row_to_cache(r) for r in self._s.execute(stmt).scalars().all()]

    def add_health_event(self, source_id: str, health: SourceHealth, detail: str) -> None:
        self._s.add(
            SourceHealthEventRow(
                id=new_id(),
                source_id=source_id,
                health=health.value,
                detail=detail,
                at=utcnow(),
            )
        )

    def last_fetch_outcomes(
        self, source_id: str
    ) -> tuple[datetime | None, datetime | None, str | None]:
        success_stmt = (
            select(SourceFetchRow)
            .where(
                SourceFetchRow.source_id == source_id,
                SourceFetchRow.outcome.in_((FetchOutcome.FETCHED.value, FetchOutcome.CACHED.value)),
            )
            .order_by(SourceFetchRow.requested_at.desc())
        )
        failure_stmt = (
            select(SourceFetchRow)
            .where(
                SourceFetchRow.source_id == source_id,
                SourceFetchRow.outcome == FetchOutcome.FAILED.value,
            )
            .order_by(SourceFetchRow.requested_at.desc())
        )
        success = self._s.execute(success_stmt).scalars().first()
        failure = self._s.execute(failure_stmt).scalars().first()
        last_success = success.completed_at or success.requested_at if success else None
        last_failure = failure.requested_at if failure else None
        reason = failure.error if failure else None
        return (last_success, last_failure, reason)

    def add_element_record(
        self, record: OrbitalElementRecord, mission_id: str | None, policy_version: str
    ) -> None:
        self._s.add(
            OrbitalElementRecordRow(
                id=new_id(),
                mission_id=mission_id,
                source_id=record.source_id,
                satellite_id=record.satellite_id,
                norad_cat_id=record.norad_cat_id,
                object_name=record.object_name,
                epoch=record.epoch,
                tle_line1=record.tle_line1,
                tle_line2=record.tle_line2,
                checksum=record.checksum,
                freshness_state=record.freshness.state.value,
                liveness=record.freshness.liveness.value,
                cache_status=record.freshness.cache_status.value,
                policy_version=policy_version,
                fetched_at=record.freshness.fetched_at,
                created_at=utcnow(),
            )
        )

    def get_mission_source_data(self, mission_id: str) -> MissionSourceData | None:
        stmt = select(OrbitalElementRecordRow).where(
            OrbitalElementRecordRow.mission_id == mission_id
        )
        row = self._s.execute(stmt).scalars().first()
        if row is None:
            return None
        identifier = str(row.norad_cat_id) if row.norad_cat_id is not None else row.satellite_id
        if row.source_id == "sample":
            limitations = "Bundled stale sample TLE; deterministic calculation, NOT live data."
        else:
            limitations = (
                f"External orbital data via '{row.source_id}'; freshness="
                f"{row.freshness_state}. Not a real-time observation; usage rights require review."
            )
        return MissionSourceData(
            source_id=row.source_id,
            record_identifier=identifier,
            object_name=row.object_name,
            data_epoch=row.epoch,
            fetched_at=row.fetched_at,
            cache_status=row.cache_status,
            freshness_state=row.freshness_state,
            liveness=row.liveness,
            policy_version=row.policy_version,
            checksum=row.checksum,
            limitations=limitations,
        )


def _row_to_cache(row: SourceCacheEntryRow) -> SourceCacheRecord:
    return SourceCacheRecord(
        cache_key=row.cache_key,
        source_id=row.source_id,
        url=row.url,
        body_path=row.body_path,
        checksum=row.checksum,
        schema_version=row.schema_version,
        http_status=row.http_status,
        content_type=row.content_type,
        fetched_at=row.fetched_at,
        expires_at=row.expires_at,
        effective_epoch=row.effective_epoch,
        last_success_at=row.last_success_at,
        last_failure_at=row.last_failure_at,
        failure_reason=row.failure_reason,
    )
