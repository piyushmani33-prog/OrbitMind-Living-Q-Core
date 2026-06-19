"""Unit tests for CelesTrak GP record validation + OMM->TLE normalization."""

from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError
from tests.conftest import build_celestrak_omm

from orbitmind.sources.celestrak.models import CelestrakGpRecord
from orbitmind.space.elements import ElementParseError, omm_fields_to_tle, parse_omm_epoch


def test_valid_record_parses_and_normalizes() -> None:
    omm = build_celestrak_omm("2026-06-19T12:00:00.000000")
    record = CelestrakGpRecord.model_validate(omm)
    assert record.norad_cat_id == 25544
    assert record.object_name.startswith("ISS")
    line1, line2 = omm_fields_to_tle(record.to_omm_fields())
    assert line1.startswith("1 25544")
    assert line2.startswith("2 25544")
    epoch = parse_omm_epoch(record.to_omm_fields())
    assert epoch.tzinfo is not None


def test_missing_required_field_rejected() -> None:
    omm = build_celestrak_omm()
    del omm["MEAN_MOTION"]
    with pytest.raises(PydanticValidationError):
        CelestrakGpRecord.model_validate(omm)


def test_unparseable_elements_raise() -> None:
    with pytest.raises(ElementParseError):
        omm_fields_to_tle({"EPOCH": "not-a-date"})


def test_invalid_epoch_raises() -> None:
    with pytest.raises(ElementParseError):
        parse_omm_epoch({"EPOCH": "garbage"})
