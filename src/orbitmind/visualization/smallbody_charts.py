"""Bounded small-body visual artifacts (NOT high-fidelity ephemeris output).

Charts are labelled ``model-estimate`` and explicitly disclaim that they are not
JPL Horizons output and do not represent perturbations or uncertainty (ADR-0017).
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from orbitmind.core.checksums import sha256_file
from orbitmind.core.paths import mission_artifact_dir
from orbitmind.core.timeutils import utcnow
from orbitmind.smallbody.models import CloseApproachRecord, SmallBodyRecord

_DISCLAIMER = (
    "model-estimate; source-reported JPL data. NOT Horizons ephemeris output. "
    "Perturbations and uncertainty are not represented; not a precision prediction."
)


class SmallBodyArtifactType(StrEnum):
    CLOSE_APPROACH_DISTANCE = "close_approach_distance"
    ORBIT_PARAMETER_SUMMARY = "orbit_parameter_summary"
    KEPLERIAN_ORBIT_2D = "keplerian_orbit_2d"


class SmallBodyArtifact:
    """Metadata for a generated small-body artifact (path relative to the root)."""

    def __init__(
        self,
        scope_id: str,
        artifact_type: str,
        path: str,
        sidecar_path: str,
        checksum: str,
        created_at: datetime,
    ) -> None:
        self.scope_id = scope_id
        self.type = artifact_type
        self.path = path
        self.sidecar_path = sidecar_path
        self.checksum = checksum
        self.created_at = created_at

    def as_dict(self) -> dict[str, str]:
        return {"type": self.type, "path": self.path, "checksum": self.checksum}


class SmallBodyVisualizationService:
    """Renders bounded small-body artifacts under ``artifacts/<scope_id>/``."""

    ALGORITHM_VERSION = "smallbody-viz-1"

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root

    def render_close_approaches(
        self, scope_id: str, records: list[CloseApproachRecord], *, label: str
    ) -> SmallBodyArtifact:
        out_dir = mission_artifact_dir(self._root, scope_id)
        path = out_dir / f"{SmallBodyArtifactType.CLOSE_APPROACH_DISTANCE.value}.png"
        times = [r.time_utc for r in records if r.distance.nominal_au is not None]
        dists = [r.distance.nominal_au for r in records if r.distance.nominal_au is not None]
        fig, ax = plt.subplots(figsize=(9, 4.5))
        ax.scatter(times, dists, s=14, color="#d62728")
        ax.set_title(f"Close-approach distance — {label} ({_DISCLAIMER})", fontsize=8)
        ax.set_xlabel("Close-approach time (UTC)")
        ax.set_ylabel("Nominal distance (au)")
        ax.grid(True, alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return self._finalize(
            scope_id,
            SmallBodyArtifactType.CLOSE_APPROACH_DISTANCE,
            path,
            sidecar_extra={"records": len(records), "label": label},
        )

    def render_orbit_summary(self, record: SmallBodyRecord) -> SmallBodyArtifact:
        out_dir = mission_artifact_dir(self._root, record.id)
        path = out_dir / f"{SmallBodyArtifactType.ORBIT_PARAMETER_SUMMARY.value}.png"
        e = record.orbit.elements
        params = [
            ("semi-major axis a (au)", e.semimajor_axis_au),
            ("perihelion q (au)", e.perihelion_distance_au),
            ("aphelion Q (au)", e.aphelion_distance_au),
            ("eccentricity e", e.eccentricity),
            ("inclination i (deg)", e.inclination_deg),
        ]
        labels = [p[0] for p in params if p[1] is not None]
        values = [p[1] for p in params if p[1] is not None]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.barh(labels, values, color="#1f77b4")
        ax.set_title(
            f"Orbital parameters — {record.identity.canonical_name} ({_DISCLAIMER})", fontsize=8
        )
        ax.grid(True, axis="x", alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return self._finalize(
            record.id,
            SmallBodyArtifactType.ORBIT_PARAMETER_SUMMARY,
            path,
            sidecar_extra={"object": record.identity.canonical_name},
        )

    def render_orbit_illustration(self, record: SmallBodyRecord) -> SmallBodyArtifact | None:
        """A 2-D heliocentric Keplerian ellipse from a, e (illustration only).

        Coordinate assumptions: orbit drawn in its own orbital plane with the Sun at a
        focus; argument of perihelion along +x; no inclination/node rotation; no
        perturbations or uncertainty. This is NOT a precision prediction (ADR-0017).
        """
        e_el = record.orbit.elements
        a, ecc = e_el.semimajor_axis_au, e_el.eccentricity
        if a is None or ecc is None or a <= 0 or ecc < 0 or ecc >= 1:
            return None  # only closed elliptical orbits are illustrated
        b = a * math.sqrt(1.0 - ecc * ecc)
        c = a * ecc  # focus offset
        thetas = [2.0 * math.pi * k / 360 for k in range(361)]
        xs = [a * math.cos(t) - c for t in thetas]
        ys = [b * math.sin(t) for t in thetas]
        out_dir = mission_artifact_dir(self._root, record.id)
        path = out_dir / f"{SmallBodyArtifactType.KEPLERIAN_ORBIT_2D.value}.png"
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot(xs, ys, color="#1f77b4", linewidth=1.2, label="orbit (illustration)")
        ax.scatter([0], [0], color="#ffae42", s=120, marker="*", label="Sun (focus)")
        ax.set_aspect("equal", "box")
        ax.set_title(
            f"2-D Keplerian orbit illustration — {record.identity.canonical_name}\n{_DISCLAIMER}",
            fontsize=7,
        )
        ax.set_xlabel("au")
        ax.set_ylabel("au")
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(path, dpi=110)
        plt.close(fig)
        return self._finalize(
            record.id,
            SmallBodyArtifactType.KEPLERIAN_ORBIT_2D,
            path,
            sidecar_extra={
                "object": record.identity.canonical_name,
                "coordinate_assumptions": (
                    "heliocentric orbital plane; Sun at focus; perihelion along +x; "
                    "no inclination/node rotation; no perturbations/uncertainty"
                ),
            },
        )

    def _finalize(
        self,
        scope_id: str,
        artifact_type: SmallBodyArtifactType,
        image_path: Path,
        *,
        sidecar_extra: dict[str, object],
    ) -> SmallBodyArtifact:
        checksum = sha256_file(image_path)
        sidecar_path = image_path.with_suffix(".json")
        sidecar: dict[str, object] = {
            "artifact_type": artifact_type.value,
            "scope_id": scope_id,
            "created_at": utcnow().isoformat(),
            "algorithm_version": self.ALGORITHM_VERSION,
            "epistemic_status": "model-estimate",
            "checksum": checksum,
            "limitations": _DISCLAIMER,
            **sidecar_extra,
        }
        sidecar_path.write_text(json.dumps(sidecar, indent=2, sort_keys=True), encoding="utf-8")
        return SmallBodyArtifact(
            scope_id=scope_id,
            artifact_type=artifact_type.value,
            path=str(image_path.relative_to(self._root)),
            sidecar_path=str(sidecar_path.relative_to(self._root)),
            checksum=checksum,
            created_at=utcnow(),
        )
