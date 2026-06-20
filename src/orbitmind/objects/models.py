"""Unified space-object identity model (kind-agnostic)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from orbitmind.core.ids import new_id
from orbitmind.core.timeutils import utcnow
from orbitmind.governance.epistemic import EpistemicStatus
from orbitmind.sources.models import SourceFreshnessAssessment


class SpaceObjectKind(StrEnum):
    """The scientific class of a space object. Only ASTEROID/COMET are implemented now."""

    ARTIFICIAL_SATELLITE = "artificial-satellite"  # implemented via SGP4 (Phase 1/2)
    ROCKET_BODY = "rocket-body"
    SPACE_DEBRIS = "space-debris"
    ASTEROID = "asteroid"  # implemented (Phase 3A, JPL SBDB)
    COMET = "comet"  # implemented (Phase 3A, JPL SBDB)
    METEOROID = "meteoroid"
    DWARF_PLANET = "dwarf-planet"
    PLANET = "planet"
    MOON = "moon"
    STAR = "star"
    EXOPLANET = "exoplanet"
    GALAXY = "galaxy"
    RADIO_SOURCE = "radio-source"
    TRANSIENT_EVENT = "transient-event"
    UNKNOWN_CANDIDATE = "unknown-candidate"


# Kinds with implemented data/normalization in this phase.
IMPLEMENTED_KINDS: frozenset[SpaceObjectKind] = frozenset(
    {SpaceObjectKind.ASTEROID, SpaceObjectKind.COMET}
)


class ObjectVerificationStatus(StrEnum):
    """Outcome of OrbitMind's deterministic validation of an object record."""

    NOT_VERIFIED = "not-verified"
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed-with-warnings"
    FAILED = "failed"


class CatalogIdentifier(BaseModel):
    """An identifier from a specific catalogue (e.g. SPK-ID, designation, number)."""

    model_config = ConfigDict(frozen=True)

    catalog: str  # e.g. "jpl-sbdb", "spk", "designation", "number"
    identifier: str


class ObjectAlias(BaseModel):
    """An alternative name/designation for an object."""

    model_config = ConfigDict(frozen=True)

    alias: str
    kind: str = "name"  # name | designation | number | shortname


class ObjectClassification(BaseModel):
    """A classification under a named scheme (e.g. orbit class AMO/Amor)."""

    model_config = ConfigDict(frozen=True)

    scheme: str  # e.g. "jpl-orbit-class"
    code: str | None = None
    name: str | None = None


class DiscoveryRecord(BaseModel):
    """Discovery metadata when the source provides it."""

    model_config = ConfigDict(frozen=True)

    date: str | None = None
    discoverer: str | None = None
    site: str | None = None


class SourceReference(BaseModel):
    """Where an object record came from (provenance, no internal paths/secrets)."""

    model_config = ConfigDict(frozen=True)

    source_id: str
    source_record_id: str  # the upstream record id (e.g. SPK-ID)
    requested_identifier: str
    fetched_at: datetime | None = None
    data_epoch: str | None = None  # source-provided epoch (e.g. orbit epoch JD)
    checksum: str
    schema_version: str
    policy_version: str


class SpaceObjectIdentity(BaseModel):
    """Canonical identity of a space object, independent of orbit representation."""

    model_config = ConfigDict(frozen=True)

    kind: SpaceObjectKind
    canonical_name: str
    primary_identifier: CatalogIdentifier
    designation: str | None = None
    number: str | None = None
    aliases: list[ObjectAlias] = Field(default_factory=list)
    classifications: list[ObjectClassification] = Field(default_factory=list)
    discovery: DiscoveryRecord | None = None


class SpaceObject(BaseModel):
    """A unified, kind-agnostic space object with provenance and epistemic labels.

    Note: there is deliberately **no** single ``satellite_id`` field — identity is
    carried by ``identity.primary_identifier`` and ``aliases``.
    """

    id: str = Field(default_factory=new_id)
    identity: SpaceObjectIdentity
    source: SourceReference
    freshness: SourceFreshnessAssessment
    epistemic_status: EpistemicStatus = EpistemicStatus.DETERMINISTIC_CALCULATION
    verification_status: ObjectVerificationStatus = ObjectVerificationStatus.NOT_VERIFIED
    limitations: str = ""
    created_at: datetime = Field(default_factory=utcnow)
