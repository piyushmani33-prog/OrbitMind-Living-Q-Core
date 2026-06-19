"""CelesTrak GP/OMM JSON response model (source-specific, does not leak outward).

CelesTrak ``gp.php?...&FORMAT=json`` returns a JSON array of OMM objects. We
validate each object into a typed record and expose ``to_omm_fields()`` to hand the
standard OMM field names to the SGP4 element helpers.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CelestrakGpRecord(BaseModel):
    """One validated CelesTrak GP/OMM record (strict; unknown keys ignored)."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore", frozen=True)

    object_name: str = Field(alias="OBJECT_NAME")
    object_id: str | None = Field(default=None, alias="OBJECT_ID")
    norad_cat_id: int = Field(alias="NORAD_CAT_ID")
    epoch: str = Field(alias="EPOCH")
    mean_motion: float = Field(alias="MEAN_MOTION")
    eccentricity: float = Field(alias="ECCENTRICITY")
    inclination: float = Field(alias="INCLINATION")
    ra_of_asc_node: float = Field(alias="RA_OF_ASC_NODE")
    arg_of_pericenter: float = Field(alias="ARG_OF_PERICENTER")
    mean_anomaly: float = Field(alias="MEAN_ANOMALY")
    ephemeris_type: int = Field(default=0, alias="EPHEMERIS_TYPE")
    classification_type: str = Field(default="U", alias="CLASSIFICATION_TYPE")
    element_set_no: int | None = Field(default=None, alias="ELEMENT_SET_NO")
    rev_at_epoch: float | None = Field(default=None, alias="REV_AT_EPOCH")
    bstar: float = Field(default=0.0, alias="BSTAR")
    mean_motion_dot: float = Field(default=0.0, alias="MEAN_MOTION_DOT")
    mean_motion_ddot: float = Field(default=0.0, alias="MEAN_MOTION_DDOT")

    def to_omm_fields(self) -> dict[str, Any]:
        """Return the standard OMM field dict consumed by sgp4's ``omm.initialize``."""
        fields: dict[str, Any] = {
            "OBJECT_NAME": self.object_name,
            "EPOCH": self.epoch,
            "MEAN_MOTION": self.mean_motion,
            "ECCENTRICITY": self.eccentricity,
            "INCLINATION": self.inclination,
            "RA_OF_ASC_NODE": self.ra_of_asc_node,
            "ARG_OF_PERICENTER": self.arg_of_pericenter,
            "MEAN_ANOMALY": self.mean_anomaly,
            "EPHEMERIS_TYPE": self.ephemeris_type,
            "CLASSIFICATION_TYPE": self.classification_type,
            "NORAD_CAT_ID": self.norad_cat_id,
            "BSTAR": self.bstar,
            "MEAN_MOTION_DOT": self.mean_motion_dot,
            "MEAN_MOTION_DDOT": self.mean_motion_ddot,
        }
        if self.object_id is not None:
            fields["OBJECT_ID"] = self.object_id
        if self.element_set_no is not None:
            fields["ELEMENT_SET_NO"] = self.element_set_no
        if self.rev_at_epoch is not None:
            fields["REV_AT_EPOCH"] = self.rev_at_epoch
        return fields
