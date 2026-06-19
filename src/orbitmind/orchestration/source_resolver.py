"""Resolves a mission's orbital elements from the selected source.

Unifies the bundled sample fixture path and the CelesTrak connector behind one
return type so the orchestrator stays source-agnostic. Enforces "no silent
fallback": a CelesTrak failure only falls back to the sample when the request
explicitly opts in, and the result is labelled accordingly.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from orbitmind.governance.provenance import EvidenceReference
from orbitmind.mission.models import MissionRequest, MissionSource
from orbitmind.persistence.source_repository import SourceRepository
from orbitmind.sources.celestrak.connector import CelestrakConnector
from orbitmind.sources.errors import SourceError, SourceUnavailableError
from orbitmind.sources.freshness import fixture_freshness
from orbitmind.sources.models import (
    OrbitalElementRecord,
    SourceFetchRecord,
)
from orbitmind.sources.policies import SAMPLE_SOURCE_ID, SourceCatalog
from orbitmind.sources.registry import SourceRegistry
from orbitmind.space.models import OrbitalSourceRecord


class ResolvedOrbit(BaseModel):
    """Everything the orchestrator needs to propagate, regardless of source."""

    source_id: str
    policy_version: str
    tle_line1: str
    tle_line2: str
    source_record: OrbitalSourceRecord
    element_record: OrbitalElementRecord
    fetch: SourceFetchRecord | None = None
    evidence: list[EvidenceReference]
    used_fallback: bool = False
    fallback_from: str | None = None


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


class SourceResolver:
    """Resolves orbital elements for sample or CelesTrak sources."""

    def __init__(
        self,
        registry: SourceRegistry,
        catalog: SourceCatalog,
        celestrak: CelestrakConnector | None,
    ) -> None:
        self._registry = registry
        self._catalog = catalog
        self._celestrak = celestrak

    def sample_satellite_ids(self) -> set[str]:
        return self._registry.supported_satellite_ids()

    def resolve(self, request: MissionRequest, source_repo: SourceRepository) -> ResolvedOrbit:
        if request.source is MissionSource.CELESTRAK:
            return self._resolve_celestrak(request, source_repo)
        return self._resolve_sample(request)

    # ---- sample ------------------------------------------------------------
    def _resolve_sample(self, request: MissionRequest) -> ResolvedOrbit:
        source_record = self._registry.get_source_record(request.satellite_id)
        line1, line2 = self._registry.get_tle(request.satellite_id)
        sample_def = self._catalog.get(SAMPLE_SOURCE_ID)
        policy_version = sample_def.policy.policy_version if sample_def else "1"
        element = OrbitalElementRecord(
            satellite_id=request.satellite_id,
            object_name=source_record.name,
            norad_cat_id=source_record.norad_cat_id,
            epoch=_parse_iso_utc(source_record.epoch_utc),
            tle_line1=line1,
            tle_line2=line2,
            source_id=SAMPLE_SOURCE_ID,
            schema_version="tle-3line",
            checksum=source_record.checksum,
            freshness=fixture_freshness(),
        )
        return ResolvedOrbit(
            source_id=SAMPLE_SOURCE_ID,
            policy_version=policy_version,
            tle_line1=line1,
            tle_line2=line2,
            source_record=source_record,
            element_record=element,
            fetch=None,
            evidence=[self._registry.evidence_reference(request.satellite_id)],
        )

    # ---- celestrak ---------------------------------------------------------
    def _resolve_celestrak(
        self, request: MissionRequest, source_repo: SourceRepository
    ) -> ResolvedOrbit:
        if self._celestrak is None:
            raise SourceUnavailableError("CelesTrak connector is not configured")
        try:
            result = self._celestrak.get_element_record(request.satellite_id, source_repo)
        except SourceError:
            if (
                request.allow_sample_fallback
                and request.satellite_id in self.sample_satellite_ids()
            ):
                fallback = self._resolve_sample(request)
                return fallback.model_copy(
                    update={"used_fallback": True, "fallback_from": MissionSource.CELESTRAK.value}
                )
            raise  # no silent fallback

        element = result.record
        policy = self._celestrak.policy()
        source_record = OrbitalSourceRecord(
            satellite_id=element.satellite_id,
            name=element.object_name,
            norad_cat_id=element.norad_cat_id,
            source_name=policy.official_name,
            source_url=policy.base_url,
            epoch_utc=element.epoch.isoformat(),
            fixture_created="(external fetch — see fetched_at)",
            data_use_note=policy.license.usage_note,
            checksum=element.checksum,
            test_only=False,
        )
        evidence = [
            EvidenceReference(
                kind="celestrak-gp",
                locator=f"celestrak:{request.satellite_id}",
                description=(
                    f"{element.object_name} GP record; epoch {element.epoch.isoformat()}; "
                    f"freshness {element.freshness.state.value}"
                ),
            )
        ]
        return ResolvedOrbit(
            source_id=self._celestrak.source_id,
            policy_version=policy.policy_version,
            tle_line1=element.tle_line1,
            tle_line2=element.tle_line2,
            source_record=source_record,
            element_record=element,
            fetch=result.fetch,
            evidence=evidence,
        )
