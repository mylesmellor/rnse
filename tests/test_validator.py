"""
test_validator.py — Tests for schema checks and error collection.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rnse.validator import validate_schedule, Severity


DUMMY_PATH = Path("schedule.xlsx")


def _make_raw(rows: list[dict], fields: list[str] | None = None):
    """Helper to build (raw_schedule, field_names) as the loader would return."""
    if not rows:
        return {}, []

    if fields is None:
        sample = rows[0]
        fields = [k.upper() for k in sample if k.lower() not in ("asset_id", "asset_name")]

    raw: dict = {}
    for row in rows:
        aid_raw = row.get("asset_id") or row.get("Asset_ID") or ""
        aid = str(aid_raw).strip().upper() if aid_raw else "__EMPTY__"
        if aid in raw:
            raw[f"{aid}__DUP__"] = {
                f.upper(): row.get(f.lower(), row.get(f)) for f in fields
            }
        else:
            raw[aid] = {f.upper(): row.get(f.lower(), row.get(f)) for f in fields}
    return raw, fields


class TestMissingSheet:
    def test_empty_raw_returns_fatal(self):
        _, issues = validate_schedule({}, [], DUMMY_PATH)
        codes = [i.code for i in issues]
        assert "ERROR_MISSING_SHEET" in codes
        assert any(i.severity == Severity.FATAL for i in issues)


class TestMissingColumns:
    def test_missing_asset_id_returns_fatal(self):
        _, issues = validate_schedule({}, [], DUMMY_PATH)
        assert any(i.severity == Severity.FATAL for i in issues)


class TestDuplicateAssetID:
    def test_duplicate_is_fatal(self):
        raw = {
            "ASSET_001": {"MV": 1_000_000},
            "ASSET_001__DUP__": {"MV": 2_000_000},
        }
        _, issues = validate_schedule(raw, ["MV"], DUMMY_PATH)
        codes = [i.code for i in issues]
        assert "ERROR_DUPLICATE_ASSET_ID" in codes
        assert any(i.severity == Severity.FATAL for i in issues)


class TestEmptyAssetID:
    def test_empty_asset_id_is_fatal(self):
        raw = {"__EMPTY__": {"MV": 100}}
        _, issues = validate_schedule(raw, ["MV"], DUMMY_PATH)
        assert any(i.severity == Severity.FATAL for i in issues)


class TestNoDataRows:
    def test_only_empty_ids_is_fatal(self):
        raw = {"__EMPTY__": {"MV": 100}}
        _, issues = validate_schedule(raw, ["MV"], DUMMY_PATH)
        # Expect FATAL for empty Asset_ID.
        assert any(i.severity == Severity.FATAL for i in issues)


class TestNonNumericValues:
    def test_text_in_numeric_field_is_error(self):
        raw = {"ASSET_001": {"MV": "not_a_number"}}
        _, issues = validate_schedule(raw, ["MV"], DUMMY_PATH)
        codes = [i.code for i in issues]
        assert "ERROR_NON_NUMERIC_VALUE" in codes

    def test_na_value_is_warn(self):
        raw = {"ASSET_001": {"MV": "N/A"}}
        _, issues = validate_schedule(raw, ["MV"], DUMMY_PATH)
        codes = [i.code for i in issues]
        assert "WARN_EMPTY_FIELD_VALUE" in codes
        assert "ERROR_NON_NUMERIC_VALUE" not in codes

    def test_none_value_is_warn(self):
        raw = {"ASSET_001": {"MV": None}}
        _, issues = validate_schedule(raw, ["MV"], DUMMY_PATH)
        codes = [i.code for i in issues]
        assert "WARN_EMPTY_FIELD_VALUE" in codes


class TestCleanSchedule:
    def test_clean_data_zero_errors(self):
        raw = {
            "ASSET_001": {"MV": 1_250_000, "NIY": 0.0525},
            "ASSET_002": {"MV": 875_000, "NIY": 0.0550},
        }
        schedule, issues = validate_schedule(raw, ["MV", "NIY"], DUMMY_PATH)

        error_issues = [i for i in issues if i.severity in (Severity.FATAL, Severity.ERROR)]
        assert error_issues == []
        assert "ASSET_001" in schedule
        assert "ASSET_002" in schedule

    def test_values_converted_to_float(self):
        raw = {"ASSET_001": {"MV": 1_250_000}}
        schedule, _ = validate_schedule(raw, ["MV"], DUMMY_PATH)
        assert isinstance(schedule["ASSET_001"]["MV"], float)

    def test_integer_coerced(self):
        raw = {"ASSET_001": {"MV": 1_000_000}}
        schedule, _ = validate_schedule(raw, ["MV"], DUMMY_PATH)
        assert schedule["ASSET_001"]["MV"] == 1_000_000.0

    def test_numeric_string_coerced(self):
        raw = {"ASSET_001": {"MV": "1250000"}}
        schedule, _ = validate_schedule(raw, ["MV"], DUMMY_PATH)
        assert schedule["ASSET_001"]["MV"] == 1_250_000.0

    def test_comma_numeric_string_coerced(self):
        raw = {"ASSET_001": {"MV": "1,250,000"}}
        schedule, _ = validate_schedule(raw, ["MV"], DUMMY_PATH)
        assert schedule["ASSET_001"]["MV"] == 1_250_000.0


class TestCollectAll:
    def test_multiple_errors_all_reported(self):
        raw = {
            "ASSET_001": {"MV": "bad", "NIY": "also_bad"},
        }
        _, issues = validate_schedule(raw, ["MV", "NIY"], DUMMY_PATH)
        error_codes = [i.code for i in issues if i.severity == Severity.ERROR]
        # Both MV and NIY errors should appear.
        assert error_codes.count("ERROR_NON_NUMERIC_VALUE") == 2
