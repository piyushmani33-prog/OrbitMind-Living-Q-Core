"""One-command offline sample runner for the bundled ISS mission.

Run with:

    python -m orbitmind.sample

The runner uses the existing mission workflow and response projections without
starting an API server. It is local, deterministic, and sample-data only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TextIO

from orbitmind.api.container import AppContainer
from orbitmind.api.routers.missions import _build_detail
from orbitmind.api.schemas import MissionDetailResponse, OrbitPropagationRequest
from orbitmind.api.static_report_schemas import MissionStaticReportResponse
from orbitmind.api.visual_manifest_schemas import MissionVisualManifestResponse
from orbitmind.core.checksums import sha256_file, sha256_text
from orbitmind.core.config import PROJECT_ROOT, Settings
from orbitmind.core.errors import NotFoundError, OrbitMindError
from orbitmind.core.logging import configure_logging
from orbitmind.governance.provenance import EvidenceReference
from orbitmind.observation_geometry.models import (
    GeodeticPosition,
    GeometryComputationRequest,
    GeometryComputationResult,
    GroundObservationSite,
    PinnedOrbitElementSet,
)
from orbitmind.observation_geometry.service import compute_observation_geometry
from orbitmind.orchestration.orchestrator import PrimeOrchestrator
from orbitmind.orchestration.source_resolver import SourceResolver
from orbitmind.persistence.repositories import SqlAlchemyMissionRepository
from orbitmind.persistence.source_repository import SqlAlchemySourceRepository
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.elements import ElementParseError, validate_propagatable
from orbitmind.space.models import OrbitalSourceRecord, OrbitalStateSample
from orbitmind.space.propagation import PropagationService
from orbitmind.verification.checks import VerificationService
from orbitmind.visualization.charts import VisualizationService
from orbitmind.visualization.models import ArtifactRecord

SAMPLE_DATABASE_PATH = PROJECT_ROOT / "data" / "orbitmind_sample.db"
DEFAULT_SAMPLE_ID = "iss"
CUSTOM_TLE_SATELLITE_ID = "CUSTOM_TLE"
MAX_CUSTOM_TLE_LABEL_LENGTH = 80
MAX_CUSTOM_TLE_LINE_LENGTH = 100
OBSERVE_STEP_SECONDS = 120
MAX_OBSERVE_WINDOW_HOURS = 24

_BUNDLED_SAMPLE_MARKDOWN_SAFETY_BOUNDARY = (
    "Bundled stale sample TLE only; not live tracking.",
    "No provider fetch.",
    "No command readiness, approval, or certification.",
    "No quantum advantage claim.",
)
_CUSTOM_TLE_MARKDOWN_SAFETY_BOUNDARY = (
    "User-provided offline TLE only; not live tracking.",
    "No provider fetch.",
    "No CelesTrak fetch.",
    "No command readiness, approval, or certification.",
    "No quantum advantage claim.",
)


@dataclass(frozen=True)
class OfflineSampleDefinition:
    """Bundled offline sample metadata and request payload."""

    sample_id: str
    description: str
    orbit_class: str
    request: dict[str, object]


OFFLINE_SAMPLES: dict[str, OfflineSampleDefinition] = {
    "iss": OfflineSampleDefinition(
        sample_id="iss",
        description="Bundled stale ISS sample TLE; test-only; not live tracking",
        orbit_class="LEO",
        request={
            "satellite_id": "ISS",
            "start_time": "2019-12-09T17:00:00Z",
            "end_time": "2019-12-09T18:00:00Z",
            "step_seconds": 120,
        },
    )
}


@dataclass(frozen=True)
class BundledOfflineCatalogEntry:
    """Safe display metadata for one verified bundled offline fixture."""

    sample_id: str
    display_name: str
    norad_catalog_id: int | None
    orbit_class: str
    tle_epoch_utc: datetime
    tle_age_days: int
    age_observed_at_utc: datetime
    source_label: str
    source_note: str
    accuracy_note: str


@dataclass(frozen=True)
class BundledObservationRun:
    """One bounded observer-relative run over a reviewed bundled TLE fixture."""

    sample_id: str
    source: OrbitalSourceRecord
    observer: GeodeticPosition
    start: datetime
    end: datetime
    mission_result: SampleRunResult
    geometry: GeometryComputationResult


class CustomOfflineTleRegistry(SourceRegistry):
    """Single-record in-memory registry for reviewer-provided offline TLE input."""

    def __init__(
        self,
        *,
        satellite_id: str,
        satellite_label: str,
        tle_line1: str,
        tle_line2: str,
        epoch_utc: datetime,
    ) -> None:
        checksum = sha256_text(f"{tle_line1}\n{tle_line2}\n")
        self._satellite_id = satellite_id
        self._tle_line1 = tle_line1
        self._tle_line2 = tle_line2
        self._record = OrbitalSourceRecord(
            satellite_id=satellite_id,
            name=satellite_label,
            norad_cat_id=_parse_tle_norad_id(tle_line1),
            source_name="user-provided offline TLE",
            source_url="(reviewer form input)",
            epoch_utc=epoch_utc.isoformat(),
            fixture_created="provided during local reviewer run",
            data_use_note=(
                "User-provided offline TLE for local reviewer sandbox only; NOT live tracking."
            ),
            checksum=checksum,
            test_only=True,
        )

    def supported_satellite_ids(self) -> set[str]:
        """Identifiers available in this one-off offline registry."""

        return {self._satellite_id}

    def get_source_record(self, satellite_id: str) -> OrbitalSourceRecord:
        """Return provenance for the reviewer-provided TLE."""

        if satellite_id != self._satellite_id:
            raise NotFoundError("unknown satellite identifier")
        return self._record

    def get_tle(self, satellite_id: str) -> tuple[str, str]:
        """Return the reviewer-provided TLE lines after the caller selects the record."""

        self.get_source_record(satellite_id)
        return (self._tle_line1, self._tle_line2)

    def evidence_reference(self, satellite_id: str) -> EvidenceReference:
        """A path-free evidence pointer for reviewer-provided offline input."""

        record = self.get_source_record(satellite_id)
        return EvidenceReference(
            kind="tle-user-input",
            locator="reviewer:offline-custom-tle",
            description=(
                f"{record.name} (user-provided offline TLE, sha256={record.checksum[:12]}...)"
            ),
        )


@dataclass(frozen=True)
class SampleRunResult:
    """Result bundle returned by the offline sample runner."""

    mission: MissionDetailResponse
    static_report: MissionStaticReportResponse
    artifacts_root: Path
    static_report_path: Path
    static_report_checksum: str
    static_report_markdown_path: Path
    static_report_markdown_checksum: str

    def artifact_path(self, artifact: ArtifactRecord) -> Path:
        """Return the absolute image path for an artifact record."""
        return self.artifacts_root / artifact.path

    def sidecar_path(self, artifact: ArtifactRecord) -> Path:
        """Return the absolute sidecar path for an artifact record."""
        return self.artifacts_root / artifact.sidecar_path

    def display_artifact_path(self, artifact: ArtifactRecord) -> Path:
        """Return a local, project-relative image path for CLI display."""
        return _display_path(self.artifact_path(artifact), self.artifacts_root)

    def display_sidecar_path(self, artifact: ArtifactRecord) -> Path:
        """Return a local, project-relative sidecar path for CLI display."""
        return _display_path(self.sidecar_path(artifact), self.artifacts_root)

    def display_static_report_path(self) -> Path:
        """Return a local, project-relative static report path for CLI display."""
        return _display_path(self.static_report_path, self.artifacts_root)

    def display_static_report_markdown_path(self) -> Path:
        """Return a local, project-relative Markdown report path for CLI display."""
        return _display_path(self.static_report_markdown_path, self.artifacts_root)


def run_sample(
    settings: Settings | None = None,
    *,
    sample_id: str = DEFAULT_SAMPLE_ID,
) -> SampleRunResult:
    """Run the bundled deterministic ISS sample mission without an API server."""

    sample = _get_sample_definition(sample_id)
    effective_settings = settings or _sample_settings()
    return _run_offline_mission(
        settings=effective_settings,
        request_payload=sample.request,
        markdown_safety_boundary=_BUNDLED_SAMPLE_MARKDOWN_SAFETY_BOUNDARY,
    )


def get_bundled_offline_catalog(
    registry: SourceRegistry,
    *,
    observed_at: datetime | None = None,
) -> tuple[BundledOfflineCatalogEntry, ...]:
    """Project verified local fixtures into a bounded reviewer catalog.

    New catalog fixtures require their own source and legal review before they are
    added to ``OFFLINE_SAMPLES`` and the bundled fixture manifest.
    """

    reference_time = observed_at or datetime.now(UTC)
    if reference_time.tzinfo is None:
        raise ValueError("catalog observation time must be timezone-aware")
    observed_at_utc = reference_time.astimezone(UTC)
    entries: list[BundledOfflineCatalogEntry] = []
    for sample_id in sorted(OFFLINE_SAMPLES):
        sample = OFFLINE_SAMPLES[sample_id]
        satellite_id = str(sample.request["satellite_id"])
        source = registry.get_source_record(satellite_id)
        tle_line1, _ = registry.get_tle(satellite_id)
        tle_epoch_utc = _parse_tle_epoch(tle_line1)
        tle_age_days = max(0, (observed_at_utc - tle_epoch_utc).days)
        entries.append(
            BundledOfflineCatalogEntry(
                sample_id=sample.sample_id,
                display_name=source.name,
                norad_catalog_id=source.norad_cat_id,
                orbit_class=sample.orbit_class,
                tle_epoch_utc=tle_epoch_utc,
                tle_age_days=tle_age_days,
                age_observed_at_utc=observed_at_utc,
                source_label="bundled sample/test-only",
                source_note=source.data_use_note,
                accuracy_note=(
                    "Bundled stale sample/test-only data; deterministic SGP4 propagation "
                    "is educational/advisory only."
                ),
            )
        )
    return tuple(entries)


def get_bundled_offline_catalog_entry(
    registry: SourceRegistry,
    sample_id: str,
) -> BundledOfflineCatalogEntry:
    """Return one selected bundled catalog entry without accepting external inputs."""

    normalized_sample_id = sample_id.strip().lower()
    for entry in get_bundled_offline_catalog(registry):
        if entry.sample_id == normalized_sample_id:
            return entry
    raise ValueError("selected bundled offline catalog sample is not available")


def resolve_bundled_observation_sample(
    registry: SourceRegistry,
    satellite_identifier: str,
) -> OfflineSampleDefinition:
    """Resolve a friendly name, bundled ID, or NORAD ID to one local fixture only."""

    normalized_identifier = _normalize_bundled_identifier(satellite_identifier)
    if not normalized_identifier:
        raise ValueError("satellite identifier is required")
    for sample_id in sorted(OFFLINE_SAMPLES):
        sample = OFFLINE_SAMPLES[sample_id]
        satellite_id = str(sample.request["satellite_id"])
        source = registry.get_source_record(satellite_id)
        aliases = {
            sample.sample_id,
            satellite_id,
            source.name,
            str(source.norad_cat_id) if source.norad_cat_id is not None else "",
        }
        if normalized_identifier in {_normalize_bundled_identifier(alias) for alias in aliases}:
            return sample
    raise ValueError("bundled offline satellite was not found")


def run_bundled_observation(
    settings: Settings | None = None,
    *,
    sample_id: str,
    observer_latitude_deg: float,
    observer_longitude_deg: float,
    observer_altitude_km: float,
    time_window_hours: int,
) -> BundledObservationRun:
    """Run a bounded observer-relative report anchored to the fixture TLE epoch."""

    if time_window_hours < 1 or time_window_hours > MAX_OBSERVE_WINDOW_HOURS:
        raise ValueError("observation time window must be between 1 and 24 hours")
    sample = _get_sample_definition(sample_id)
    registry = SourceRegistry()
    satellite_id = str(sample.request["satellite_id"])
    source = registry.get_source_record(satellite_id)
    tle_line1, tle_line2 = registry.get_tle(satellite_id)
    elements = PinnedOrbitElementSet(
        source=source,
        tle_line1=tle_line1,
        tle_line2=tle_line2,
    )
    if elements.orbit_epoch is None:  # pragma: no cover - validated TLE always carries an epoch.
        raise RuntimeError("bundled TLE epoch was not available")
    start = elements.orbit_epoch
    observer = GeodeticPosition(
        latitude_deg=observer_latitude_deg,
        longitude_deg=observer_longitude_deg,
        altitude_km=observer_altitude_km,
    )
    end = start + timedelta(hours=time_window_hours)
    request_payload = {
        **sample.request,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "step_seconds": OBSERVE_STEP_SECONDS,
        "observer_latitude": observer.latitude_deg,
        "observer_longitude": observer.longitude_deg,
        "observer_altitude_km": observer.altitude_km,
    }
    effective_settings = settings or _sample_settings()
    mission_result = _run_offline_mission(
        settings=effective_settings,
        request_payload=request_payload,
        registry=registry,
        markdown_safety_boundary=_BUNDLED_SAMPLE_MARKDOWN_SAFETY_BOUNDARY,
    )
    geometry_request = GeometryComputationRequest(
        elements=elements,
        site=GroundObservationSite(
            site_id="review-observer",
            name="Review observer",
            position=observer,
        ),
        start=start,
        end=end,
        step_seconds=OBSERVE_STEP_SECONDS,
        minimum_elevation_deg=0.0,
    )
    return BundledObservationRun(
        sample_id=sample.sample_id,
        source=source,
        observer=observer,
        start=start,
        end=end,
        mission_result=mission_result,
        geometry=compute_observation_geometry(geometry_request),
    )


def run_custom_tle_sample(
    settings: Settings | None = None,
    *,
    satellite_label: str | None,
    tle_line1: str,
    tle_line2: str,
) -> SampleRunResult:
    """Run a deterministic local reviewer mission from one pasted offline TLE."""

    label = _normalize_custom_tle_label(satellite_label)
    line1 = _normalize_custom_tle_line(tle_line1, field_name="TLE line 1")
    line2 = _normalize_custom_tle_line(tle_line2, field_name="TLE line 2")
    try:
        validate_propagatable(line1, line2)
    except ElementParseError as exc:
        raise ValueError("TLE lines must parse and propagate at epoch") from exc
    epoch_utc = _parse_tle_epoch(line1)
    registry = CustomOfflineTleRegistry(
        satellite_id=CUSTOM_TLE_SATELLITE_ID,
        satellite_label=label,
        tle_line1=line1,
        tle_line2=line2,
        epoch_utc=epoch_utc,
    )
    request_payload = {
        "satellite_id": CUSTOM_TLE_SATELLITE_ID,
        "start_time": epoch_utc.isoformat(),
        "end_time": (epoch_utc + timedelta(hours=1)).isoformat(),
        "step_seconds": 120,
    }
    effective_settings = settings or _sample_settings()
    return _run_offline_mission(
        settings=effective_settings,
        request_payload=request_payload,
        registry=registry,
        markdown_safety_boundary=_CUSTOM_TLE_MARKDOWN_SAFETY_BOUNDARY,
    )


def _run_offline_mission(
    *,
    settings: Settings,
    request_payload: dict[str, object],
    registry: SourceRegistry | None = None,
    markdown_safety_boundary: tuple[str, ...],
) -> SampleRunResult:
    """Run an offline mission through the existing app/orchestrator/repository path."""

    container = AppContainer(settings=settings)
    try:
        if registry is not None:
            _use_source_registry(container, registry)
        container.init_storage()
        payload = OrbitPropagationRequest.model_validate(request_payload)
        mission_id = container.orchestrator.run_orbit_mission(
            raw_request=payload.model_dump(mode="json"),
            request=payload.to_domain(),
        )
        with container.database.session() as session:
            repo = SqlAlchemyMissionRepository(session)
            source_repo = SqlAlchemySourceRepository(session)
            mission = repo.get_mission(mission_id)
            if mission is None:  # pragma: no cover - run_orbit_mission just persisted it.
                raise RuntimeError("sample mission was not found after execution")
            detail = _build_detail(mission, repo, source_repo, container.registry)
            manifest = MissionVisualManifestResponse.from_mission(
                mission=mission,
                artifacts=repo.get_artifacts(mission_id),
                findings=repo.get_findings(mission_id),
                source_data=source_repo.get_mission_source_data(mission_id),
            )
            static_report = MissionStaticReportResponse.from_manifest(manifest)
            static_report_path, static_report_checksum = _write_static_report_json(
                static_report=static_report,
                artifacts_root=settings.resolved_artifacts_dir(),
                mission_id=mission_id,
            )
            static_report_markdown_path, static_report_markdown_checksum = (
                _write_static_report_markdown(
                    static_report=static_report,
                    mission=detail,
                    artifacts_root=settings.resolved_artifacts_dir(),
                    mission_id=mission_id,
                    safety_boundary=markdown_safety_boundary,
                )
            )
        return SampleRunResult(
            mission=detail,
            static_report=static_report,
            artifacts_root=settings.resolved_artifacts_dir(),
            static_report_path=static_report_path,
            static_report_checksum=static_report_checksum,
            static_report_markdown_path=static_report_markdown_path,
            static_report_markdown_checksum=static_report_markdown_checksum,
        )
    finally:
        container.database.engine.dispose()


def write_summary(result: SampleRunResult, stream: TextIO = sys.stdout) -> None:
    """Write a concise, reviewer-friendly summary for a sample run."""

    mission = result.mission
    source_test_only = mission.source.test_only if mission.source is not None else None
    source_checksum = mission.source.checksum if mission.source is not None else "unavailable"
    provenance_inputs_hash = (
        mission.provenance[0].inputs_hash if mission.provenance else "unavailable"
    )
    first = mission.samples[0] if mission.samples else None
    last = mission.samples[-1] if mission.samples else None

    print("OrbitMind offline sample completed", file=stream)
    print("", file=stream)
    print("Mission", file=stream)
    print(f"  mission_id: {mission.mission_id}", file=stream)
    print(f"  status: {mission.status.value}", file=stream)
    print(f"  epistemic_status: {mission.epistemic_status.value}", file=stream)
    print(f"  sample_count: {mission.sample_count}", file=stream)
    print(f"  source.test_only: {str(source_test_only).lower()}", file=stream)
    print(f"  source_checksum: {source_checksum}", file=stream)
    print(f"  inputs_hash: {provenance_inputs_hash}", file=stream)
    _write_sample_point("first_sample", first, stream)
    _write_sample_point("last_sample", last, stream)
    print("", file=stream)
    print("Artifacts", file=stream)
    for artifact in mission.artifacts:
        print(f"  - {artifact.type.value}", file=stream)
        print(f"    local image: {result.display_artifact_path(artifact)}", file=stream)
        print(f"    local sidecar: {result.display_sidecar_path(artifact)}", file=stream)
        print(f"    checksum: {artifact.checksum}", file=stream)
    print("", file=stream)
    print("Static report", file=stream)
    print(f"  schema_version: {result.static_report.schema_version}", file=stream)
    print(f"  report_id: {result.static_report.report_id}", file=stream)
    print("  generated_on_demand: true", file=stream)
    print(f"  local file: {result.display_static_report_path()}", file=stream)
    print(f"  checksum: {result.static_report_checksum}", file=stream)
    print(
        f"  local markdown: {result.display_static_report_markdown_path()}",
        file=stream,
    )
    print(f"  markdown_checksum: {result.static_report_markdown_checksum}", file=stream)
    print("", file=stream)
    print("Safety boundary", file=stream)
    print("  bundled stale sample TLE only; not live tracking; no provider fetch", file=stream)
    print("  no command readiness, approval, or certification", file=stream)
    print("  no quantum advantage claim", file=stream)


def write_sample_list(stream: TextIO = sys.stdout) -> None:
    """Write the bundled offline samples available to the CLI."""

    print("Available offline samples:", file=stream)
    for sample_id in sorted(OFFLINE_SAMPLES):
        sample = OFFLINE_SAMPLES[sample_id]
        print(f"  {sample.sample_id:<6} {sample.description}", file=stream)


def main(argv: Sequence[str] | None = None, stdout: TextIO = sys.stdout) -> int:
    """CLI entrypoint for ``python -m orbitmind.sample``."""

    parser = argparse.ArgumentParser(
        description="Run OrbitMind's bundled offline ISS sample mission without starting the API."
    )
    parser.add_argument(
        "--list-samples",
        action="store_true",
        help="List bundled offline sample IDs and exit.",
    )
    parser.add_argument(
        "--sample",
        default=DEFAULT_SAMPLE_ID,
        help="Bundled offline sample ID to run. Currently supported: iss.",
    )
    args = parser.parse_args(argv)
    if args.list_samples:
        write_sample_list(stdout)
        return 0
    sample_id = args.sample.lower()
    if sample_id not in OFFLINE_SAMPLES:
        print(
            "OrbitMind sample failed: unknown_sample: "
            f"unsupported bundled offline sample '{args.sample}'. "
            "Run with --list-samples to see available samples.",
            file=sys.stderr,
        )
        return 2
    settings = _sample_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)
    try:
        write_summary(run_sample(settings, sample_id=sample_id), stdout)
    except OrbitMindError as exc:
        print(f"OrbitMind sample failed: {exc.code}: {exc.message}", file=sys.stderr)
        return 1
    except Exception:
        print(
            "OrbitMind sample failed: unexpected_error: offline sample could not complete",
            file=sys.stderr,
        )
        return 1
    return 0


def _sample_settings() -> Settings:
    return Settings(
        database_url=f"sqlite:///{SAMPLE_DATABASE_PATH.as_posix()}",
        artifacts_dir=PROJECT_ROOT / "artifacts",
        cache_dir=PROJECT_ROOT / "cache",
        env="sample",
        log_level="WARNING",
        network_enabled=False,
        celestrak_enabled=False,
        jpl_sbdb_enabled=False,
        jpl_cad_enabled=False,
        quantum_enabled=False,
    )


def _get_sample_definition(sample_id: str) -> OfflineSampleDefinition:
    try:
        return OFFLINE_SAMPLES[sample_id.lower()]
    except KeyError as exc:
        raise ValueError(f"unsupported bundled offline sample: {sample_id}") from exc


def _normalize_bundled_identifier(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


def _use_source_registry(container: AppContainer, registry: SourceRegistry) -> None:
    container.registry = registry
    container.resolver = SourceResolver(registry, container.catalog, None)
    container.orchestrator = PrimeOrchestrator(
        settings=container.settings,
        database=container.database,
        registry=registry,
        propagation=PropagationService(),
        verification=VerificationService(),
        visualization=VisualizationService(container.settings.resolved_artifacts_dir()),
        resolver=container.resolver,
    )


def _normalize_custom_tle_label(value: str | None) -> str:
    if value is None or not value.strip():
        return "User-provided offline TLE"
    label = value.strip()
    if len(label) > MAX_CUSTOM_TLE_LABEL_LENGTH:
        raise ValueError("satellite label must be 80 characters or fewer")
    if "<" in label or ">" in label:
        raise ValueError("satellite label contains unsupported markup characters")
    return label


def _normalize_custom_tle_line(value: str, *, field_name: str) -> str:
    line = value.strip()
    if not line:
        raise ValueError(f"{field_name} is required")
    if len(line) > MAX_CUSTOM_TLE_LINE_LENGTH:
        raise ValueError(f"{field_name} must be 100 characters or fewer")
    expected_prefix = "1 " if field_name == "TLE line 1" else "2 "
    if not line.startswith(expected_prefix):
        raise ValueError(f"{field_name} must start with '{expected_prefix}'")
    return line


def _parse_tle_epoch(line1: str) -> datetime:
    try:
        year_two_digit = int(line1[18:20])
        day_of_year = float(line1[20:32])
    except (ValueError, IndexError) as exc:
        raise ValueError("TLE line 1 epoch is not parseable") from exc
    year = 2000 + year_two_digit if year_two_digit < 57 else 1900 + year_two_digit
    return (datetime(year, 1, 1, tzinfo=UTC) + timedelta(days=day_of_year - 1.0)).astimezone(UTC)


def _parse_tle_norad_id(line1: str) -> int | None:
    try:
        raw = line1[2:7].strip()
        return int(raw) if raw else None
    except ValueError:
        return None


def _write_sample_point(label: str, sample: OrbitalStateSample | None, stream: TextIO) -> None:
    if sample is None:
        return
    if sample.latitude_deg is None or sample.longitude_deg is None or sample.altitude_km is None:
        print(f"  {label}: {sample.timestamp.isoformat()} geodetic sample unavailable", file=stream)
        return
    print(
        f"  {label}: {sample.timestamp.isoformat()} "
        f"lat={sample.latitude_deg:.6f} deg "
        f"lon={sample.longitude_deg:.6f} deg "
        f"alt={sample.altitude_km:.3f} km",
        file=stream,
    )


def _write_static_report_json(
    *,
    static_report: MissionStaticReportResponse,
    artifacts_root: Path,
    mission_id: str,
) -> tuple[Path, str]:
    report_path = artifacts_root / mission_id / "static_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(
        static_report.model_dump(mode="json"),
        indent=2,
        sort_keys=True,
    )
    report_path.write_text(f"{body}\n", encoding="utf-8")
    return report_path, sha256_file(report_path)


def _write_static_report_markdown(
    *,
    static_report: MissionStaticReportResponse,
    mission: MissionDetailResponse,
    artifacts_root: Path,
    mission_id: str,
    safety_boundary: tuple[str, ...],
) -> tuple[Path, str]:
    report_path = artifacts_root / mission_id / "static_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_static_report_markdown(
            static_report=static_report,
            mission=mission,
            safety_boundary=safety_boundary,
        ),
        encoding="utf-8",
    )
    return report_path, sha256_file(report_path)


def _render_static_report_markdown(
    *,
    static_report: MissionStaticReportResponse,
    mission: MissionDetailResponse,
    safety_boundary: tuple[str, ...],
) -> str:
    source_test_only = mission.source.test_only if mission.source is not None else None
    source_checksum = mission.source.checksum if mission.source is not None else "unavailable"
    provenance_inputs_hash = (
        mission.provenance[0].inputs_hash if mission.provenance else "unavailable"
    )
    lines = [
        "# OrbitMind Offline Sample Static Report",
        "",
        f"- Report ID: {static_report.report_id}",
        f"- Schema version: {static_report.schema_version}",
        f"- Mission ID: {static_report.mission_summary.mission_id}",
        "- Generated on demand: true",
        "",
        "## Mission summary",
        "",
        f"- Status: {mission.status.value}",
        f"- Epistemic status: {mission.epistemic_status.value}",
        f"- Sample count: {mission.sample_count}",
        f"- Source test only: {str(source_test_only).lower()}",
        f"- Source checksum: {source_checksum}",
        f"- Inputs hash: {provenance_inputs_hash}",
        "",
        "## Artifacts",
        "",
        "| Name | Type | Checksum |",
        "| --- | --- | --- |",
    ]
    for artifact in sorted(mission.artifacts, key=lambda item: item.type.value):
        lines.append(f"| {artifact.type.value} | image | {artifact.checksum} |")
    lines.extend(["", "## Safety boundary", ""])
    lines.extend(f"- {item}" for item in safety_boundary)
    lines.append("")
    return "\n".join(lines)


def _display_path(path: Path, artifacts_root: Path) -> Path:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT)
    except ValueError:
        return Path("artifacts") / resolved.relative_to(artifacts_root.resolve())


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
