"""Offline source registry for bundled TLE fixtures.

Loads ``data/samples/catalog.json``, verifies each fixture's SHA-256 (SR-16), and
exposes provenance (:class:`OrbitalSourceRecord`) plus the raw TLE lines. No
network access (SR-12).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from orbitmind.core.checksums import sha256_file
from orbitmind.core.config import PROJECT_ROOT
from orbitmind.core.errors import NotFoundError, StorageError
from orbitmind.governance.provenance import EvidenceReference
from orbitmind.space.models import OrbitalSourceRecord

DEFAULT_SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"


def _default_samples_dir() -> Path:
    if not getattr(sys, "frozen", False):
        return DEFAULT_SAMPLES_DIR

    bundle_root = getattr(sys, "_MEIPASS", None)
    if not isinstance(bundle_root, str) or not Path(bundle_root).is_dir():
        raise StorageError("sample catalog is missing")
    return Path(bundle_root) / "data" / "samples"


class SourceRegistry:
    """Reads and validates bundled orbital fixtures."""

    def __init__(self, samples_dir: Path | None = None) -> None:
        self._dir = _default_samples_dir() if samples_dir is None else samples_dir
        self._records: dict[str, OrbitalSourceRecord] = {}
        self._files: dict[str, Path] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:
        catalog_path = self._dir / "catalog.json"
        if not catalog_path.is_file():
            raise StorageError("sample catalog is missing")
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for entry in catalog.get("fixtures", []):
            record = OrbitalSourceRecord(
                satellite_id=entry["satellite_id"],
                name=entry["name"],
                norad_cat_id=entry.get("norad_cat_id"),
                source_name=entry["source_name"],
                source_url=entry["source_url"],
                epoch_utc=entry["epoch_utc"],
                fixture_created=entry["fixture_created"],
                data_use_note=entry["data_use_note"],
                checksum=entry["sha256"],
                test_only=bool(entry.get("test_only", True)),
            )
            path = self._dir / entry["file"]
            # Index by the friendly id and, as an alias, the NORAD catalog number,
            # so an external (NORAD-numbered) request can resolve to a sample fixture
            # for an explicit, opt-in fallback.
            for key in {record.satellite_id, str(record.norad_cat_id)} - {"None"}:
                self._records[key] = record
                self._files[key] = path

    def supported_satellite_ids(self) -> set[str]:
        """Identifiers available in the registry."""
        return set(self._records)

    def get_source_record(self, satellite_id: str) -> OrbitalSourceRecord:
        """Return provenance for a satellite or raise ``NotFoundError``."""
        record = self._records.get(satellite_id)
        if record is None:
            raise NotFoundError("unknown satellite identifier")
        return record

    def get_tle(self, satellite_id: str) -> tuple[str, str]:
        """Return the two TLE data lines, verifying the fixture checksum first."""
        record = self.get_source_record(satellite_id)
        path = self._files[satellite_id]
        if not path.is_file():
            raise StorageError("fixture file is missing")

        actual = sha256_file(path)
        if actual != record.checksum:
            raise StorageError("fixture checksum mismatch; refusing to use altered data")

        line1 = line2 = None
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("1 "):
                line1 = stripped
            elif stripped.startswith("2 "):
                line2 = stripped
        if line1 is None or line2 is None:
            raise StorageError("fixture does not contain a valid two-line element set")
        return (line1, line2)

    def evidence_reference(self, satellite_id: str) -> EvidenceReference:
        """An evidence pointer for provenance records."""
        record = self.get_source_record(satellite_id)
        return EvidenceReference(
            kind="tle-fixture",
            locator=f"data/samples/{self._files[satellite_id].name}",
            description=f"{record.name} (test-only sample, sha256={record.checksum[:12]}…)",
        )
