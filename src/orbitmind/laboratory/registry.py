"""Deterministic in-process Laboratory Registry.

Explicit registration only: no filesystem scanning, no entry-point loading, no
dynamic imports, no network access, no persistence, no background threads and
no module-level mutable singleton. Each ``LaboratoryRegistry`` instance is an
isolated, in-memory catalog of immutable manifests.

Registration is not installation. Installation is not activation. Activation
is not authorization. In v1 the registry exposes catalog metadata only — it
has no execute, activate or grant surface at all.
"""

from __future__ import annotations

from orbitmind.core.errors import NotFoundError, ValidationError
from orbitmind.laboratory.contracts import LaboratoryManifest


class DuplicateLaboratoryError(ValidationError):
    """A laboratory identifier was registered twice."""

    code = "duplicate_laboratory"
    http_status = 409


class UnknownLaboratoryError(NotFoundError):
    """The requested laboratory identifier is not registered."""

    code = "unknown_laboratory"


class LaboratoryRegistry:
    """Isolated, deterministic catalog of registered laboratory manifests."""

    def __init__(self) -> None:
        self._manifests: dict[str, LaboratoryManifest] = {}

    def register(self, manifest: LaboratoryManifest) -> None:
        """Register one validated, immutable manifest. Duplicates are rejected."""
        if not isinstance(manifest, LaboratoryManifest):
            raise ValidationError("only LaboratoryManifest instances can be registered")
        if manifest.laboratory_id in self._manifests:
            raise DuplicateLaboratoryError(
                f"laboratory '{manifest.laboratory_id}' is already registered"
            )
        self._manifests[manifest.laboratory_id] = manifest

    def list_manifests(self) -> tuple[LaboratoryManifest, ...]:
        """All registered manifests in deterministic ``laboratory_id`` order."""
        return tuple(self._manifests[laboratory_id] for laboratory_id in sorted(self._manifests))

    def get(self, laboratory_id: str) -> LaboratoryManifest:
        """Deterministic lookup; unknown identifiers raise a safe not-found error."""
        try:
            return self._manifests[laboratory_id]
        except KeyError:
            raise UnknownLaboratoryError("laboratory not found") from None

    def __len__(self) -> int:
        return len(self._manifests)

    def __contains__(self, laboratory_id: object) -> bool:
        return laboratory_id in self._manifests
