"""Read-only authenticated observation study chain queries."""

from __future__ import annotations

from sqlalchemy.orm import Session

from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.observation_geometry.models import ComputedVisibilityInterval
from orbitmind.observation_planning.models import ObservationPlanningSourceMode
from orbitmind.observation_planning.provenance import (
    EligibilityDeclarationMode,
    EligibilityWindow,
    PinnedInputSourceMode,
    PinnedInputSourceType,
    ScientificInputVerificationStatus,
)
from orbitmind.observation_studies.models import (
    OBSERVATION_STUDY_LIMITATION,
    GeometryStudySummary,
    ObservationStudyChain,
    ObservationStudyCheck,
    PlanningStudySummary,
    StudyEligibilitySummary,
)
from orbitmind.persistence.observation_geometry_repository import (
    SqlAlchemyObservationGeometryRepository,
    StoredObservationGeometryRequest,
    StoredObservationGeometryRun,
)
from orbitmind.persistence.observation_planning_link_repository import (
    SqlAlchemyObservationPlanningLinkRepository,
    StoredProvenancePlanningLink,
)
from orbitmind.persistence.observation_planning_provenance_repository import (
    SqlAlchemyObservationPlanningProvenanceRepository,
    StoredEligibilityWindowSet,
    StoredPinnedInputProvenance,
)
from orbitmind.persistence.observation_planning_repository import (
    SqlAlchemyObservationPlanningRepository,
    StoredObservationPlanningRequest,
    StoredObservationPlanningRun,
    normalize_owner_id,
)

_MAX_IDENTIFIER_LENGTH = 120
_GEOMETRY_DERIVED_DATASET_PREFIX = "geometry:"
_GEOMETRY_DERIVED_SOURCE_PREFIX = "geometry-source:"


def get_geometry_planning_study_chain(
    session: Session,
    owner_id: str,
    *,
    geometry_run_id: str,
    provenance_link_id: str,
) -> ObservationStudyChain:
    """Return an authenticated read-only geometry-derived planning study chain.

    The query performs no writes, does not recompute geometry, and does not execute planning.
    It uses existing authenticated repositories, then verifies that the supplied geometry run
    and provenance-planning link agree through geometry-derived provenance checksums.
    """

    owner = normalize_owner_id(owner_id)
    run_id = _clean_identifier(geometry_run_id, "geometry_run_id")
    link_id = _clean_identifier(provenance_link_id, "provenance_link_id")

    geometry_repository = SqlAlchemyObservationGeometryRepository(session)
    stored_run = geometry_repository.get_geometry_run(run_id, owner_id=owner)
    if stored_run is None:
        raise NotFoundError("observation-geometry run not found")
    stored_request = geometry_repository.get_geometry_request(stored_run.request_id, owner_id=owner)
    if stored_request is None:
        raise ValidationError("observation-geometry run request relationship mismatch")

    link_repository = SqlAlchemyObservationPlanningLinkRepository(session)
    link = link_repository.get_provenance_planning_link(link_id, owner_id=owner)
    if link is None:
        raise NotFoundError("provenance-planning link not found")

    provenance_repository = SqlAlchemyObservationPlanningProvenanceRepository(session)
    provenance = provenance_repository.get_provenance(link.provenance_record_id, owner_id=owner)
    if provenance is None:
        raise ValidationError("study chain provenance missing")
    window_set = provenance_repository.get_eligibility_window_set(
        link.eligibility_set_record_id,
        owner_id=owner,
    )
    if window_set is None:
        raise ValidationError("study chain eligibility set missing")

    planning_repository = SqlAlchemyObservationPlanningRepository(session)
    planning_request = planning_repository.get_planning_request(
        link.planning_request_id,
        owner_id=owner,
    )
    if planning_request is None:
        raise ValidationError("study chain planning request missing")
    planning_run = planning_repository.get_planning_run(link.planning_run_id, owner_id=owner)
    if planning_run is None:
        raise ValidationError("study chain planning run missing")

    checks = _validate_geometry_derived_chain(
        stored_run=stored_run,
        stored_request=stored_request,
        provenance=provenance,
        window_set=window_set,
        link=link,
        planning_request=planning_request,
        planning_run=planning_run,
    )

    return ObservationStudyChain(
        owner_id=owner,
        geometry=GeometryStudySummary(
            request_id=stored_request.id,
            run_id=stored_run.id,
            request_checksum=stored_run.request_checksum,
            geometry_checksum=stored_run.geometry_checksum,
            element_checksum=stored_run.result.element_checksum,
            source_identity_checksum=stored_run.result.source_identity_checksum,
            satellite_id=stored_request.request.elements.source.satellite_id,
            site_id=stored_request.request.site.site_id,
            sample_count=stored_run.result.sample_count,
            failed_sample_count=stored_run.result.failed_sample_count,
            interval_count=len(stored_run.result.intervals),
            computation_version=stored_run.result.computation_version,
            epistemic_status=stored_run.result.epistemic_status,
            limitations=stored_run.result.limitations,
        ),
        eligibility=StudyEligibilitySummary(
            provenance_record_id=provenance.id,
            provenance_checksum=provenance.provenance_checksum,
            eligibility_set_record_id=window_set.id,
            eligibility_set_checksum=window_set.eligibility_set_checksum,
            source_type=provenance.provenance.source.source_type,
            source_mode=provenance.provenance.source.source_mode,
            verification_status=provenance.provenance.verification_status,
            generation_rule_version=window_set.window_set.generation_rule_version,
            window_count=len(window_set.window_set.windows),
            selected_window_ids=link.selected_window_ids,
            limitations=window_set.window_set.limitations,
        ),
        planning=PlanningStudySummary(
            preparation_checksum=link.preparation_checksum,
            planning_request_id=planning_request.id,
            planning_request_checksum=planning_request.request_checksum,
            planning_request_source_mode=planning_request.request.source_mode,
            planning_run_id=planning_run.id,
            planning_scientific_identity_checksum=planning_run.scientific_identity_checksum,
            observation_plan_id=link.observation_plan_id,
            link_record_id=link.id,
            link_checksum=link.link_checksum,
            planning_status=planning_run.result.status,
            authoritative_solver=link.authoritative_solver,
            optimality_label=planning_run.result.optimality_label,
            feasible=planning_run.result.feasible,
            objective_value=planning_run.result.objective_value,
            limitations=link.limitations,
        ),
        checks=checks,
        limitations=_study_limitations(
            geometry_limitations=stored_run.result.limitations,
            eligibility_limitations=window_set.window_set.limitations,
            link_limitations=link.limitations,
        ),
    )


def _validate_geometry_derived_chain(
    *,
    stored_run: StoredObservationGeometryRun,
    stored_request: StoredObservationGeometryRequest,
    provenance: StoredPinnedInputProvenance,
    window_set: StoredEligibilityWindowSet,
    link: StoredProvenancePlanningLink,
    planning_request: StoredObservationPlanningRequest,
    planning_run: StoredObservationPlanningRun,
) -> tuple[ObservationStudyCheck, ...]:
    provenance_record = provenance.provenance
    source = provenance_record.source
    if source.source_type != PinnedInputSourceType.DERIVED:
        raise ValidationError("study chain provenance is not derived")
    if source.source_mode != PinnedInputSourceMode.DERIVED_FROM_GEOMETRY:
        raise ValidationError("study chain provenance is not geometry-derived")
    if provenance_record.verification_status != ScientificInputVerificationStatus.GEOMETRY_DERIVED:
        raise ValidationError("study chain provenance verification status mismatch")
    if (
        source.dataset_revision
        != f"{_GEOMETRY_DERIVED_DATASET_PREFIX}{stored_run.geometry_checksum}"
    ):
        raise ValidationError("study chain geometry checksum mismatch")
    if (
        source.source_id
        != f"{_GEOMETRY_DERIVED_SOURCE_PREFIX}{stored_request.source_identity_checksum}"
    ):
        raise ValidationError("study chain source identity checksum mismatch")
    if stored_run.request_checksum != stored_request.request_checksum:
        raise ValidationError("study chain geometry request checksum mismatch")
    if stored_run.result.request_checksum != stored_request.request_checksum:
        raise ValidationError("study chain geometry result request checksum mismatch")
    if stored_run.result.element_checksum != stored_request.element_checksum:
        raise ValidationError("study chain element checksum mismatch")
    if stored_run.result.source_identity_checksum != stored_request.source_identity_checksum:
        raise ValidationError("study chain result source identity checksum mismatch")
    if window_set.source_provenance_id != provenance.id:
        raise ValidationError("study chain eligibility provenance mismatch")
    if window_set.window_set.source_provenance != provenance_record:
        raise ValidationError("study chain eligibility source snapshot mismatch")
    if link.provenance_record_id != provenance.id:
        raise ValidationError("study chain link provenance mismatch")
    if link.provenance_checksum != provenance.provenance_checksum:
        raise ValidationError("study chain link provenance checksum mismatch")
    if link.eligibility_set_record_id != window_set.id:
        raise ValidationError("study chain link eligibility set mismatch")
    if link.eligibility_set_checksum != window_set.eligibility_set_checksum:
        raise ValidationError("study chain link eligibility checksum mismatch")
    if link.planning_request_id != planning_request.id:
        raise ValidationError("study chain planning request mismatch")
    if link.planning_run_id != planning_run.id:
        raise ValidationError("study chain planning run mismatch")
    if planning_run.request_id != planning_request.id:
        raise ValidationError("study chain planning run/request mismatch")
    if planning_request.request.source_mode != ObservationPlanningSourceMode.DECLARED:
        raise ValidationError("study chain planning request must remain declared")
    _validate_geometry_windows(
        windows=window_set.window_set.windows,
        intervals=stored_run.result.intervals,
        expected_asset_id=stored_request.request.elements.source.satellite_id,
        expected_target_id=stored_request.request.site.site_id,
        expected_provenance_checksum=provenance.provenance_checksum,
    )
    selected_ids = set(link.selected_window_ids)
    window_ids = {window.id for window in window_set.window_set.windows}
    if any(window_id not in window_ids for window_id in selected_ids):
        raise ValidationError("study chain selected window mismatch")

    return (
        ObservationStudyCheck(
            check_id="geometry-provenance-checksum",
            message="Geometry-derived provenance points at the authenticated geometry checksum.",
        ),
        ObservationStudyCheck(
            check_id="geometry-source-identity",
            message=(
                "Geometry-derived provenance source identity matches the authenticated "
                "orbit source."
            ),
        ),
        ObservationStudyCheck(
            check_id="eligibility-window-geometry",
            message="Eligibility windows align with authenticated geometry visibility intervals.",
        ),
        ObservationStudyCheck(
            check_id="planning-link-authenticated",
            message="Planning request, run, plan, and provenance link authenticated successfully.",
        ),
    )


def _validate_geometry_windows(
    *,
    windows: tuple[EligibilityWindow, ...],
    intervals: tuple[ComputedVisibilityInterval, ...],
    expected_asset_id: str,
    expected_target_id: str,
    expected_provenance_checksum: str,
) -> None:
    interval_bounds = {(interval.rise_time, interval.set_time) for interval in intervals}
    for window in windows:
        if window.declaration_mode != EligibilityDeclarationMode.DERIVED_FROM_GEOMETRY:
            raise ValidationError("study chain eligibility window is not geometry-derived")
        if window.verification_status != ScientificInputVerificationStatus.GEOMETRY_DERIVED:
            raise ValidationError("study chain eligibility window verification mismatch")
        if window.asset_id != expected_asset_id:
            raise ValidationError("study chain eligibility asset mismatch")
        if window.target_id != expected_target_id:
            raise ValidationError("study chain eligibility target mismatch")
        if window.source_provenance_checksum != expected_provenance_checksum:
            raise ValidationError("study chain eligibility provenance checksum mismatch")
        if (window.start, window.end) not in interval_bounds:
            raise ValidationError("study chain eligibility window does not match geometry interval")


def _study_limitations(
    *,
    geometry_limitations: tuple[str, ...],
    eligibility_limitations: tuple[str, ...],
    link_limitations: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            (
                *geometry_limitations,
                *eligibility_limitations,
                *link_limitations,
                OBSERVATION_STUDY_LIMITATION,
            )
        )
    )


def _clean_identifier(value: str, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value) > _MAX_IDENTIFIER_LENGTH
        or any(char in value for char in "\r\n\t")
    ):
        raise ValidationError(f"{field_name} must be non-empty, unpadded, and bounded")
    return value
