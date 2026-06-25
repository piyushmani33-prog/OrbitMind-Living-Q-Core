"""SQLite tests for immutable observation-planning provenance persistence."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import orbitmind.persistence.observation_planning_provenance_repository as provenance_repo_module
from orbitmind.core.checksums import sha256_text
from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_planning.provenance import (
    EligibilityDeclarationMode,
    EligibilityWindow,
    EligibilityWindowSet,
    InputRightsDeclaration,
    InputRightsPermission,
    InputRightsStatus,
    InputSourceIdentity,
    PinnedInputArtifact,
    PinnedInputProvenance,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
    eligibility_window_set_checksum,
)
from orbitmind.persistence.database import Database
from orbitmind.persistence.observation_planning_models import (
    ObservationEligibilityWindowRow,
    ObservationEligibilityWindowSetRow,
    ObservationInputProvenanceParentRow,
    ObservationInputProvenanceRow,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
)


def _checksum(label: str) -> str:
    return sha256_text(label)


def _db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{(tmp_path / 'planning-provenance.db').as_posix()}")
    db.create_all()
    return db


def _session(tmp_path: Path) -> Session:
    return _db(tmp_path).session()


def _rights(status: InputRightsStatus = InputRightsStatus.DECLARED) -> InputRightsDeclaration:
    return InputRightsDeclaration(
        rights_status=status,
        redistribution=InputRightsPermission.UNKNOWN,
        commercial_use=InputRightsPermission.UNKNOWN,
        attribution_required=status == InputRightsStatus.VERIFIED,
        user_responsibility="caller retains responsibility for declared input rights",
        limitations=("recorded declaration only",),
    )


def _artifact(label: str) -> PinnedInputArtifact:
    return PinnedInputArtifact(
        artifact_id=f"artifact-{label}",
        content_checksum=_checksum(label),
        media_type="application/json",
        record_count=2,
    )


def _fixture_provenance(label: str = "fixture") -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=PinnedInputSourceType.FIXTURE,
            source_mode=PinnedInputSourceMode.FIXTURE_BACKED,
            publisher="OrbitMind",
            dataset_name="fixture-observation-eligibility",
            dataset_version="v1",
            dataset_revision="rev-a",
        ),
        artifact=_artifact(label),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_start=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        effective_end=dt.datetime(2026, 6, 21, 12, 0, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.VERIFIED),
        verification_status=ScientificInputVerificationStatus.FIXTURE_VERIFIED,
    )


def _declared_provenance(label: str = "declared") -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id=f"{label}-source",
            source_type=PinnedInputSourceType.USER_DECLARED,
            source_mode=PinnedInputSourceMode.USER_DECLARED,
        ),
        artifact=_artifact(label),
        declared_at=dt.datetime(2026, 6, 21, 9, 0, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.DECLARED),
        verification_status=ScientificInputVerificationStatus.USER_DECLARED,
    )


def _derived_provenance(parent: PinnedInputProvenance) -> PinnedInputProvenance:
    return PinnedInputProvenance(
        source=InputSourceIdentity(
            source_id="derived-source",
            source_type=PinnedInputSourceType.DERIVED,
            source_mode=PinnedInputSourceMode.DERIVED_FROM_DECLARED_INPUT,
            dataset_name="derived-eligibility",
            dataset_version="v1",
        ),
        artifact=_artifact("derived"),
        retrieved_at=dt.datetime(2026, 6, 21, 9, 5, tzinfo=dt.UTC),
        rights=_rights(InputRightsStatus.DECLARED),
        verification_status=ScientificInputVerificationStatus.DERIVED_FROM_DECLARED,
        parent_provenance_checksums=(parent.checksum,),
    )


def _window(
    window_id: str,
    provenance: PinnedInputProvenance,
    *,
    start_minute: int = 0,
    end_minute: int = 30,
    asset_id: str = "SAT-A",
    target_id: str = "T1",
    checksum: str | None = None,
    mode: EligibilityDeclarationMode | None = None,
) -> EligibilityWindow:
    start = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC) + dt.timedelta(minutes=start_minute)
    end = dt.datetime(2026, 6, 21, 10, 0, tzinfo=dt.UTC) + dt.timedelta(minutes=end_minute)
    if mode is None:
        mode = (
            EligibilityDeclarationMode.FIXTURE_BACKED
            if provenance.source.source_type == PinnedInputSourceType.FIXTURE
            else EligibilityDeclarationMode.USER_DECLARED
            if provenance.source.source_type == PinnedInputSourceType.USER_DECLARED
            else EligibilityDeclarationMode.DERIVED_FROM_DECLARED_INPUT
        )
    return EligibilityWindow(
        id=window_id,
        asset_id=asset_id,
        target_id=target_id,
        start=start,
        end=end,
        source_provenance_checksum=checksum or provenance.checksum,
        declaration_mode=mode,
        eligibility_reason="declared-candidate",
        verification_status=(
            ScientificInputVerificationStatus.FIXTURE_VERIFIED
            if mode == EligibilityDeclarationMode.FIXTURE_BACKED
            else ScientificInputVerificationStatus.USER_DECLARED
            if mode == EligibilityDeclarationMode.USER_DECLARED
            else ScientificInputVerificationStatus.DERIVED_FROM_DECLARED
        ),
    )


def _window_set(
    provenance: PinnedInputProvenance,
    windows: tuple[EligibilityWindow, ...] | None = None,
) -> EligibilityWindowSet:
    return EligibilityWindowSet(
        source_provenance=provenance,
        windows=windows
        if windows is not None
        else (
            _window("W1", provenance),
            _window("W2", provenance, start_minute=40, end_minute=70),
        ),
    )


def _count(session: Session, table: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(table)) or 0)


def _repo(session: Session) -> SqlAlchemyObservationPlanningProvenanceRepository:
    return SqlAlchemyObservationPlanningProvenanceRepository(session)


def test_persist_and_retrieve_fixture_provenance(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        repo = _repo(session)
        stored = repo.create_provenance(provenance, owner_id="owner-a")
        fetched = repo.get_provenance(stored.id, owner_id="owner-a")

    assert fetched is not None
    assert fetched.provenance == provenance
    assert fetched.provenance_checksum == provenance.checksum


def test_persist_and_retrieve_user_declared_provenance(tmp_path: Path) -> None:
    provenance = _declared_provenance()
    with _session(tmp_path) as session:
        repo = _repo(session)
        stored = repo.create_provenance(provenance, owner_id="owner-a")
        fetched = repo.get_provenance_by_checksum(provenance.checksum, owner_id="owner-a")

    assert fetched is not None
    assert fetched.id == stored.id
    assert fetched.provenance.source.source_type == PinnedInputSourceType.USER_DECLARED


def test_persist_and_retrieve_derived_provenance_parent_links(tmp_path: Path) -> None:
    parent = _declared_provenance()
    derived = _derived_provenance(parent)
    with _session(tmp_path) as session:
        repo = _repo(session)
        parent_stored = repo.create_provenance(parent, owner_id="owner-a")
        child_stored = repo.create_provenance(derived, owner_id="owner-a")
        fetched = repo.get_provenance(child_stored.id, owner_id="owner-a")

    assert fetched is not None
    assert fetched.parent_ids == (parent_stored.id,)
    assert fetched.provenance.parent_provenance_checksums == (parent.checksum,)


def test_owner_scoped_replay_and_cross_owner_identity(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        repo = _repo(session)
        first = repo.create_provenance(provenance, owner_id="owner-a")
        replay = repo.create_provenance(provenance, owner_id="owner-a")
        other_owner = repo.create_provenance(provenance, owner_id="owner-b")

    assert first.id == replay.id
    assert first.id != other_owner.id


def test_cross_owner_retrieval_is_not_found(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = _repo(session)
        stored = repo.create_provenance(_fixture_provenance(), owner_id="owner-a")

        assert repo.get_provenance(stored.id, owner_id="owner-b") is None


def test_provenance_snapshot_and_scalar_tampering_detected(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        repo = _repo(session)
        stored = repo.create_provenance(provenance, owner_id="owner-a")
        row = session.get(ObservationInputProvenanceRow, stored.id)
        assert row is not None
        tampered = dict(row.provenance_json)
        tampered["verification_status"] = ScientificInputVerificationStatus.UNKNOWN.value
        row.provenance_json = tampered

        with pytest.raises(ValidationError, match="checksum"):
            repo.get_provenance(stored.id, owner_id="owner-a")

        row.provenance_json = provenance.model_dump(mode="json")
        row.artifact_checksum = _checksum("wrong")
        with pytest.raises(ValidationError, match="artifact checksum"):
            repo.get_provenance(stored.id, owner_id="owner-a")


def test_parent_link_tampering_detected(tmp_path: Path) -> None:
    parent = _declared_provenance()
    derived = _derived_provenance(parent)
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(parent, owner_id="owner-a")
        child = repo.create_provenance(derived, owner_id="owner-a")
        session.execute(
            update(ObservationInputProvenanceParentRow)
            .where(ObservationInputProvenanceParentRow.child_provenance_id == child.id)
            .values(parent_provenance_checksum=_checksum("wrong-parent"))
        )
        session.flush()

        with pytest.raises(ValidationError, match="parent links"):
            repo.get_provenance(child.id, owner_id="owner-a")


def test_unsupported_provenance_schema_detected(tmp_path: Path) -> None:
    with _session(tmp_path) as session:
        repo = _repo(session)
        stored = repo.create_provenance(_fixture_provenance(), owner_id="owner-a")
        row = session.get(ObservationInputProvenanceRow, stored.id)
        assert row is not None
        snapshot = dict(row.provenance_json)
        snapshot["schema_version"] = "2"
        row.provenance_json = snapshot

        with pytest.raises(ValidationError, match="malformed input provenance"):
            repo.get_provenance(stored.id, owner_id="owner-a")


def test_persist_and_retrieve_empty_eligibility_set(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    window_set = _window_set(provenance, ())
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        stored = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        fetched = repo.get_eligibility_window_set(stored.id, owner_id="owner-a")

    assert fetched is not None
    assert fetched.window_set.windows == ()


def test_persist_and_retrieve_populated_eligibility_set_ordered(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    first = _window("W1", provenance, start_minute=0, end_minute=30)
    second = _window("W2", provenance, start_minute=40, end_minute=70)
    window_set = _window_set(provenance, (second, first))
    with _session(tmp_path) as session:
        repo = _repo(session)
        source = repo.create_provenance(provenance, owner_id="owner-a")
        stored = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        fetched = repo.get_eligibility_window_set(stored.id, owner_id="owner-a")

    assert fetched is not None
    assert fetched.source_provenance_id == source.id
    assert fetched.window_set.windows == (first, second)


def test_eligibility_window_retrieval_uses_domain_canonical_order(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    sat_a_later = _window(
        "W-SAT-A-LATE",
        provenance,
        asset_id="SAT-A",
        start_minute=60,
        end_minute=90,
    )
    sat_b_earlier = _window(
        "W-SAT-B-EARLY",
        provenance,
        asset_id="SAT-B",
        start_minute=0,
        end_minute=30,
    )
    window_set = _window_set(provenance, (sat_b_earlier, sat_a_later))
    assert window_set.windows == (sat_a_later, sat_b_earlier)

    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        stored = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        fetched = repo.get_eligibility_window_set(stored.id, owner_id="owner-a")
        replay = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        row_count = _count(session, ObservationEligibilityWindowRow)

    assert fetched is not None
    assert fetched.window_set == window_set
    assert fetched.eligibility_set_checksum == eligibility_window_set_checksum(window_set)
    assert fetched.window_set.windows == (sat_a_later, sat_b_earlier)
    assert replay.id == stored.id
    assert row_count == 2


def test_eligibility_replay_and_cross_owner_identity(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    window_set = _window_set(provenance)
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        repo.create_provenance(provenance, owner_id="owner-b")
        first = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        replay = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        other_owner = repo.create_eligibility_window_set(window_set, owner_id="owner-b")

    assert first.id == replay.id
    assert first.id != other_owner.id


def test_cross_owner_provenance_reference_rejected(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(provenance, owner_id="owner-a")

        with pytest.raises(NotFoundError):
            repo.create_eligibility_window_set(_window_set(provenance), owner_id="owner-b")


def test_cross_owner_parent_rejected(tmp_path: Path) -> None:
    parent = _declared_provenance()
    derived = _derived_provenance(parent)
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(parent, owner_id="owner-a")

        with pytest.raises(NotFoundError):
            repo.create_provenance(derived, owner_id="owner-b")


def test_eligibility_set_and_window_tampering_detected(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    window_set = _window_set(provenance)
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        stored = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        set_row = session.get(ObservationEligibilityWindowSetRow, stored.id)
        assert set_row is not None
        set_row.eligibility_set_checksum = _checksum("wrong-set")
        with pytest.raises(ValidationError, match="checksum"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")

        set_row.eligibility_set_checksum = stored.eligibility_set_checksum
        window_row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id == stored.id
            )
        )
        assert window_row is not None
        window_row.asset_id = "SAT-Z"
        with pytest.raises(ValidationError, match="asset"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")
        window_row.asset_id = window_row.window_json["asset_id"]

        window_row.target_id = "T-Z"
        with pytest.raises(ValidationError, match="target"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")
        window_row.target_id = window_row.window_json["target_id"]

        window_row.start_at = window_row.start_at + dt.timedelta(minutes=1)
        with pytest.raises(ValidationError, match="time"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")
        window_row.start_at = dt.datetime.fromisoformat(window_row.window_json["start"])

        tampered_snapshot = dict(window_row.window_json)
        tampered_snapshot["target_id"] = "T-SNAPSHOT"
        window_row.window_json = tampered_snapshot
        with pytest.raises(ValidationError, match=r"checksum|target|snapshot"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")


def test_missing_extra_and_count_window_tampering_detected(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    window_set = _window_set(provenance)
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        stored = repo.create_eligibility_window_set(window_set, owner_id="owner-a")
        window_row = session.scalar(
            select(ObservationEligibilityWindowRow).where(
                ObservationEligibilityWindowRow.set_id == stored.id
            )
        )
        assert window_row is not None
        session.delete(window_row)
        session.flush()
        with pytest.raises(ValidationError, match="window count"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")

        session.rollback()
        repo = _repo(session)
        fetched = repo.get_eligibility_window_set(stored.id, owner_id="owner-a")
        assert fetched is not None
        set_row = session.get(ObservationEligibilityWindowSetRow, stored.id)
        assert set_row is not None
        set_row.window_count = 1
        with pytest.raises(ValidationError, match="window count"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")

        set_row.window_count = len(fetched.window_set.windows)
        extra = provenance_repo_module._window_row(
            stored.id,
            "owner-a",
            _window("W3", provenance, asset_id="SAT-C", start_minute=80, end_minute=110),
        )
        session.add(extra)
        session.flush()
        with pytest.raises(ValidationError, match="window count"):
            repo.get_eligibility_window_set(stored.id, owner_id="owner-a")


def test_atomic_rollback_of_parent_links(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _declared_provenance()
    derived = _derived_provenance(parent)
    with _session(tmp_path) as session:
        repo = _repo(session)
        parent_stored = repo.create_provenance(parent, owner_id="owner-a")
        parent_row = session.get(ObservationInputProvenanceRow, parent_stored.id)
        assert parent_row is not None
        monkeypatch.setattr(
            repo, "_resolve_parent_rows", lambda owner, prov: (parent_row, parent_row)
        )

        with pytest.raises(IntegrityError):
            repo.create_provenance(derived, owner_id="owner-a")

        assert _count(session, ObservationInputProvenanceRow) == 1
        assert _count(session, ObservationInputProvenanceParentRow) == 0


def test_atomic_rollback_of_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    provenance = _fixture_provenance()
    windows = (
        _window("W1", provenance),
        _window("W2", provenance, start_minute=40, end_minute=70),
    )
    window_set = _window_set(provenance, windows)
    with _session(tmp_path) as session:
        repo = _repo(session)
        repo.create_provenance(provenance, owner_id="owner-a")
        original = provenance_repo_module._window_row

        def duplicate_window_row(set_id: str, owner_id: str, window: EligibilityWindow) -> object:
            row = original(set_id, owner_id, window)
            row.window_id = "duplicate"
            return row

        monkeypatch.setattr(provenance_repo_module, "_window_row", duplicate_window_row)

        with pytest.raises(IntegrityError):
            repo.create_eligibility_window_set(window_set, owner_id="owner-a")

        assert _count(session, ObservationEligibilityWindowSetRow) == 0
        assert _count(session, ObservationEligibilityWindowRow) == 0


def test_restrictive_deletion_behaviour_with_foreign_keys(tmp_path: Path) -> None:
    db = _db(tmp_path)
    with db.session() as session:
        repo = _repo(session)
        provenance = _fixture_provenance()
        stored_provenance = repo.create_provenance(provenance, owner_id="owner-a")
        stored_set = repo.create_eligibility_window_set(_window_set(provenance), owner_id="owner-a")
        session.commit()

    with db.session() as session:
        session.execute(text("PRAGMA foreign_keys=ON"))
        with pytest.raises(IntegrityError):
            session.execute(
                delete(ObservationInputProvenanceRow).where(
                    ObservationInputProvenanceRow.id == stored_provenance.id
                )
            )
            session.flush()
        session.rollback()

    with db.session() as session:
        repo = _repo(session)
        assert repo.get_provenance(stored_provenance.id, owner_id="owner-a") is not None
        assert repo.get_eligibility_window_set(stored_set.id, owner_id="owner-a") is not None


def test_unexpected_integrity_error_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        repo = _repo(session)

        def no_replay(owner_id: str, checksum: str) -> None:
            return None

        monkeypatch.setattr(repo, "_find_provenance_by_checksum", no_replay)
        repo.create_provenance(provenance, owner_id="owner-a")
        with pytest.raises(IntegrityError):
            repo.create_provenance(provenance, owner_id="owner-a")


def test_repository_returns_typed_models_not_orm_rows(tmp_path: Path) -> None:
    provenance = _fixture_provenance()
    with _session(tmp_path) as session:
        repo = _repo(session)
        stored = repo.create_provenance(provenance, owner_id="owner-a")
        window_set = repo.create_eligibility_window_set(_window_set(provenance), owner_id="owner-a")

    assert not isinstance(stored, ObservationInputProvenanceRow)
    assert not isinstance(window_set, ObservationEligibilityWindowSetRow)


def test_repository_module_does_not_import_geometry_providers_or_quantum() -> None:
    source = Path(provenance_repo_module.__file__).read_text(encoding="utf-8")

    assert "orbitmind.space" not in source
    assert "orbitmind.sources" not in source
    assert "orbitmind.quantum" not in source
