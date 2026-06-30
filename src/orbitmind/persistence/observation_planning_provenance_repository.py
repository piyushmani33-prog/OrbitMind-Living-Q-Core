"""Repository for immutable observation-planning provenance and eligibility persistence."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.observation_planning.provenance import (
    EligibilityWindow,
    EligibilityWindowSet,
    PinnedInputProvenance,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    eligibility_window_set_checksum,
    provenance_checksum,
)
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationEligibilityWindowSetRow,
    ObservationInputProvenanceParentRow,
    ObservationInputProvenanceRow,
)
from orbitmind.persistence.observation_planning_repository import normalize_owner_id

PROVENANCE_SCHEMA_VERSION = "1"
ELIGIBILITY_SET_SCHEMA_VERSION = "1"


class StoredPinnedInputProvenance(BaseModel):
    """Typed persisted provenance result."""

    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    provenance_checksum: str
    provenance: PinnedInputProvenance
    parent_ids: tuple[str, ...] = ()


class StoredEligibilityWindowSet(BaseModel):
    """Typed persisted eligibility-window-set result."""

    model_config = ConfigDict(frozen=True)

    id: str
    owner_id: str
    eligibility_set_checksum: str
    source_provenance_id: str
    window_set: EligibilityWindowSet


class SqlAlchemyObservationPlanningProvenanceRepository:
    """Owner-scoped append-only persistence for pinned inputs and eligibility sets."""

    def __init__(self, session: Session) -> None:
        self._s = session

    def create_provenance(
        self,
        provenance: PinnedInputProvenance,
        *,
        owner_id: str,
        use_savepoint: bool = True,
    ) -> StoredPinnedInputProvenance:
        owner = normalize_owner_id(owner_id)
        checksum = provenance_checksum(provenance)
        existing = self._find_provenance_by_checksum(owner, checksum)
        if existing is not None:
            stored = self._row_to_provenance(existing)
            if stored.provenance != provenance:
                raise ValidationError("stored provenance content disagrees with checksum")
            return stored

        parent_rows = self._resolve_parent_rows(owner, provenance)
        row = ObservationInputProvenanceRow(
            id=new_id(),
            owner_id=owner,
            provenance_checksum=checksum,
            schema_version=provenance.schema_version,
            source_type=provenance.source.source_type.value,
            verification_status=provenance.verification_status.value,
            provenance_json=provenance.model_dump(mode="json"),
            artifact_checksum=provenance.artifact.content_checksum,
            created_at=utcnow(),
        )

        def insert() -> None:
            self._s.add(row)
            self._s.flush()
            for parent in parent_rows:
                self._s.add(
                    ObservationInputProvenanceParentRow(
                        id=new_id(),
                        owner_id=owner,
                        child_provenance_id=row.id,
                        parent_provenance_id=parent.id,
                        parent_provenance_checksum=parent.provenance_checksum,
                        created_at=utcnow(),
                    )
                )
            self._s.flush()

        if use_savepoint:
            try:
                with self._s.begin_nested():
                    insert()
            except IntegrityError:
                self._s.expire_all()
                existing = self._find_provenance_by_checksum(owner, checksum)
                if existing is None:
                    raise
                stored = self._row_to_provenance(existing)
                if stored.provenance != provenance:
                    raise ValidationError(
                        "stored provenance content disagrees with checksum"
                    ) from None
                return stored
        else:
            insert()
        return self._row_to_provenance(row)

    def get_provenance(
        self,
        provenance_id: str,
        *,
        owner_id: str,
    ) -> StoredPinnedInputProvenance | None:
        row = self._provenance_row(provenance_id, normalize_owner_id(owner_id))
        return self._row_to_provenance(row) if row is not None else None

    def get_provenance_by_checksum(
        self,
        provenance_checksum: str,
        *,
        owner_id: str,
    ) -> StoredPinnedInputProvenance | None:
        row = self._find_provenance_by_checksum(normalize_owner_id(owner_id), provenance_checksum)
        return self._row_to_provenance(row) if row is not None else None

    def create_eligibility_window_set(
        self,
        window_set: EligibilityWindowSet,
        *,
        owner_id: str,
        use_savepoint: bool = True,
    ) -> StoredEligibilityWindowSet:
        owner = normalize_owner_id(owner_id)
        source = self.get_provenance_by_checksum(
            window_set.source_provenance.checksum,
            owner_id=owner,
        )
        if source is None:
            raise NotFoundError("source provenance not found")
        if source.provenance != window_set.source_provenance:
            raise ValidationError("eligibility set source provenance snapshot mismatch")
        checksum = eligibility_window_set_checksum(window_set)
        existing = self._find_window_set_by_checksum(owner, checksum)
        if existing is not None:
            stored = self._row_to_window_set(existing)
            if stored.window_set != window_set:
                raise ValidationError("stored eligibility-window set disagrees with checksum")
            return stored

        row = ObservationEligibilityWindowSetRow(
            id=new_id(),
            owner_id=owner,
            eligibility_set_checksum=checksum,
            schema_version=window_set.schema_version,
            source_provenance_id=source.id,
            source_provenance_checksum=source.provenance_checksum,
            generation_rule_version=window_set.generation_rule_version,
            window_count=len(window_set.windows),
            limitations_json=list(window_set.limitations),
            eligibility_set_json=window_set.model_dump(mode="json"),
            created_at=utcnow(),
        )

        def insert() -> None:
            self._s.add(row)
            self._s.flush()
            for window in window_set.windows:
                self._s.add(_window_row(row.id, owner, window))
            self._s.flush()

        if use_savepoint:
            try:
                with self._s.begin_nested():
                    insert()
            except IntegrityError:
                self._s.expire_all()
                existing = self._find_window_set_by_checksum(owner, checksum)
                if existing is None:
                    raise
                stored = self._row_to_window_set(existing)
                if stored.window_set != window_set:
                    raise ValidationError(
                        "stored eligibility-window set disagrees with checksum"
                    ) from None
                return stored
        else:
            insert()
        return self._row_to_window_set(row)

    def get_eligibility_window_set(
        self,
        window_set_id: str,
        *,
        owner_id: str,
    ) -> StoredEligibilityWindowSet | None:
        row = self._window_set_row(window_set_id, normalize_owner_id(owner_id))
        return self._row_to_window_set(row) if row is not None else None

    def get_eligibility_window_set_by_checksum(
        self,
        window_set_checksum: str,
        *,
        owner_id: str,
    ) -> StoredEligibilityWindowSet | None:
        row = self._find_window_set_by_checksum(
            normalize_owner_id(owner_id),
            window_set_checksum,
        )
        return self._row_to_window_set(row) if row is not None else None

    def _resolve_parent_rows(
        self,
        owner_id: str,
        provenance: PinnedInputProvenance,
    ) -> tuple[ObservationInputProvenanceRow, ...]:
        if provenance.source.source_type != PinnedInputSourceType.DERIVED:
            return ()
        rows: list[ObservationInputProvenanceRow] = []
        for checksum in provenance.parent_provenance_checksums:
            row = self._find_provenance_by_checksum(owner_id, checksum)
            if row is None:
                raise NotFoundError("parent provenance not found")
            rows.append(row)
        return tuple(rows)

    def _find_provenance_by_checksum(
        self,
        owner_id: str,
        checksum: str,
    ) -> ObservationInputProvenanceRow | None:
        return (
            self._s.execute(
                select(ObservationInputProvenanceRow).where(
                    ObservationInputProvenanceRow.owner_id == owner_id,
                    ObservationInputProvenanceRow.provenance_checksum == checksum,
                )
            )
            .scalars()
            .first()
        )

    def _provenance_row(
        self,
        provenance_id: str,
        owner_id: str,
    ) -> ObservationInputProvenanceRow | None:
        return (
            self._s.execute(
                select(ObservationInputProvenanceRow).where(
                    ObservationInputProvenanceRow.owner_id == owner_id,
                    ObservationInputProvenanceRow.id == provenance_id,
                )
            )
            .scalars()
            .first()
        )

    def _parent_rows(
        self,
        child_id: str,
        owner_id: str,
    ) -> tuple[ObservationInputProvenanceParentRow, ...]:
        rows = (
            self._s.execute(
                select(ObservationInputProvenanceParentRow)
                .where(
                    ObservationInputProvenanceParentRow.owner_id == owner_id,
                    ObservationInputProvenanceParentRow.child_provenance_id == child_id,
                )
                .order_by(ObservationInputProvenanceParentRow.parent_provenance_checksum)
            )
            .scalars()
            .all()
        )
        return tuple(rows)

    def _find_window_set_by_checksum(
        self,
        owner_id: str,
        checksum: str,
    ) -> ObservationEligibilityWindowSetRow | None:
        return (
            self._s.execute(
                select(ObservationEligibilityWindowSetRow).where(
                    ObservationEligibilityWindowSetRow.owner_id == owner_id,
                    ObservationEligibilityWindowSetRow.eligibility_set_checksum == checksum,
                )
            )
            .scalars()
            .first()
        )

    def _window_set_row(
        self,
        window_set_id: str,
        owner_id: str,
    ) -> ObservationEligibilityWindowSetRow | None:
        return (
            self._s.execute(
                select(ObservationEligibilityWindowSetRow).where(
                    ObservationEligibilityWindowSetRow.owner_id == owner_id,
                    ObservationEligibilityWindowSetRow.id == window_set_id,
                )
            )
            .scalars()
            .first()
        )

    def _window_rows(
        self,
        set_id: str,
        owner_id: str,
    ) -> tuple[ObservationEligibilityWindowRow, ...]:
        rows = (
            self._s.execute(
                select(ObservationEligibilityWindowRow)
                .where(
                    ObservationEligibilityWindowRow.owner_id == owner_id,
                    ObservationEligibilityWindowRow.set_id == set_id,
                )
                .order_by(
                    ObservationEligibilityWindowRow.asset_id,
                    ObservationEligibilityWindowRow.target_id,
                    ObservationEligibilityWindowRow.start_at,
                    ObservationEligibilityWindowRow.window_id,
                )
            )
            .scalars()
            .all()
        )
        return tuple(rows)

    def _row_to_provenance(
        self,
        row: ObservationInputProvenanceRow,
    ) -> StoredPinnedInputProvenance:
        if row.schema_version != PROVENANCE_SCHEMA_VERSION:
            raise ValidationError("unsupported input provenance schema version")
        try:
            provenance = PinnedInputProvenance.model_validate(row.provenance_json)
        except PydanticValidationError as exc:
            raise ValidationError("malformed input provenance snapshot") from exc
        checksum = provenance_checksum(provenance)
        if checksum != row.provenance_checksum:
            raise ValidationError("input provenance checksum mismatch")
        if provenance.schema_version != row.schema_version:
            raise ValidationError("input provenance schema version mismatch")
        if provenance.source.source_type.value != row.source_type:
            raise ValidationError("input provenance source type mismatch")
        if provenance.verification_status.value != row.verification_status:
            raise ValidationError("input provenance verification status mismatch")
        if provenance.artifact.content_checksum != row.artifact_checksum:
            raise ValidationError("input provenance artifact checksum mismatch")
        parent_rows = self._parent_rows(row.id, row.owner_id)
        parent_checksums = tuple(parent.parent_provenance_checksum for parent in parent_rows)
        if parent_checksums != provenance.parent_provenance_checksums:
            raise ValidationError("input provenance parent links mismatch")
        parent_ids: list[str] = []
        for parent in parent_rows:
            parent_row = self._provenance_row(parent.parent_provenance_id, row.owner_id)
            if (
                parent_row is None
                or parent_row.provenance_checksum != parent.parent_provenance_checksum
            ):
                raise ValidationError("input provenance parent reference mismatch")
            parent_ids.append(parent.parent_provenance_id)
        geometry_derived = (
            provenance.source.source_type == PinnedInputSourceType.DERIVED
            and provenance.source.source_mode == PinnedInputSourceMode.DERIVED_FROM_GEOMETRY
        )
        if (
            provenance.source.source_type == PinnedInputSourceType.DERIVED
            and not geometry_derived
            and not parent_rows
        ):
            raise ValidationError("derived input provenance requires parent links")
        if provenance.source.source_type != PinnedInputSourceType.DERIVED and parent_rows:
            raise ValidationError("non-derived input provenance cannot have parent links")
        return StoredPinnedInputProvenance(
            id=row.id,
            owner_id=row.owner_id,
            provenance_checksum=row.provenance_checksum,
            provenance=provenance,
            parent_ids=tuple(parent_ids),
        )

    def _row_to_window_set(
        self,
        row: ObservationEligibilityWindowSetRow,
    ) -> StoredEligibilityWindowSet:
        if row.schema_version != ELIGIBILITY_SET_SCHEMA_VERSION:
            raise ValidationError("unsupported eligibility-window-set schema version")
        source = self.get_provenance(row.source_provenance_id, owner_id=row.owner_id)
        if source is None:
            raise ValidationError("eligibility-window set source provenance missing")
        if source.provenance_checksum != row.source_provenance_checksum:
            raise ValidationError("eligibility-window set provenance checksum mismatch")
        try:
            snapshot = EligibilityWindowSet.model_validate(row.eligibility_set_json)
        except PydanticValidationError as exc:
            raise ValidationError("malformed eligibility-window set snapshot") from exc
        if snapshot.source_provenance != source.provenance:
            raise ValidationError("eligibility-window set source provenance snapshot mismatch")
        windows = tuple(
            self._row_to_window(window) for window in self._window_rows(row.id, row.owner_id)
        )
        if len(windows) != row.window_count:
            raise ValidationError("eligibility-window set window count mismatch")
        if tuple(snapshot.windows) != windows:
            raise ValidationError("eligibility-window set window snapshot mismatch")
        rebuilt = EligibilityWindowSet(
            schema_version=snapshot.schema_version,
            source_provenance=source.provenance,
            windows=windows,
            generation_rule_version=snapshot.generation_rule_version,
            limitations=snapshot.limitations,
        )
        checksum = eligibility_window_set_checksum(rebuilt)
        if checksum != row.eligibility_set_checksum:
            raise ValidationError("eligibility-window set checksum mismatch")
        if snapshot.schema_version != row.schema_version:
            raise ValidationError("eligibility-window set schema version mismatch")
        if snapshot.generation_rule_version != row.generation_rule_version:
            raise ValidationError("eligibility-window set generation rule mismatch")
        if tuple(row.limitations_json) != snapshot.limitations:
            raise ValidationError("eligibility-window set limitations mismatch")
        return StoredEligibilityWindowSet(
            id=row.id,
            owner_id=row.owner_id,
            eligibility_set_checksum=row.eligibility_set_checksum,
            source_provenance_id=row.source_provenance_id,
            window_set=rebuilt,
        )

    def _row_to_window(self, row: ObservationEligibilityWindowRow) -> EligibilityWindow:
        try:
            window = EligibilityWindow.model_validate(row.window_json)
        except PydanticValidationError as exc:
            raise ValidationError("malformed eligibility window snapshot") from exc
        if window.id != row.window_id:
            raise ValidationError("eligibility window ID mismatch")
        if window.asset_id != row.asset_id:
            raise ValidationError("eligibility window asset mismatch")
        if window.target_id != row.target_id:
            raise ValidationError("eligibility window target mismatch")
        if window.start != row.start_at or window.end != row.end_at:
            raise ValidationError("eligibility window time mismatch")
        if window.source_provenance_checksum != row.source_provenance_checksum:
            raise ValidationError("eligibility window provenance checksum mismatch")
        if window.declaration_mode.value != row.declaration_mode:
            raise ValidationError("eligibility window declaration mode mismatch")
        if window.verification_status.value != row.verification_status:
            raise ValidationError("eligibility window verification status mismatch")
        return window


def _window_row(
    set_id: str,
    owner_id: str,
    window: EligibilityWindow,
) -> ObservationEligibilityWindowRow:
    return ObservationEligibilityWindowRow(
        id=new_id(),
        set_id=set_id,
        owner_id=owner_id,
        window_id=window.id,
        asset_id=window.asset_id,
        target_id=window.target_id,
        start_at=window.start,
        end_at=window.end,
        source_provenance_checksum=window.source_provenance_checksum,
        declaration_mode=window.declaration_mode.value,
        verification_status=window.verification_status.value,
        window_json=window.model_dump(mode="json"),
        created_at=utcnow(),
    )
