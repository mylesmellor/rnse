"""
test_reporter.py — Tests for audit report structure and output.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rnse.reporter import AuditReport


@pytest.fixture
def report():
    r = AuditReport()
    r.record_substitution(
        placeholder="{{MV:ASSET_001:£,0}}",
        asset_id="ASSET_001",
        field="MV",
        raw_value=1_250_000.0,
        formatted_value="£1,250,000",
        location="paragraph:0",
    )
    r.error_unknown_asset("{{MV:ASSET_999:£,0}}", "ASSET_999", "paragraph:1")
    r.warn_malformed("{{ broken", "paragraph:2")
    return r


class TestAuditReportCounts:
    def test_placeholders_found(self, report):
        # 1 success + 1 error = 2 placeholders found; warn_malformed doesn't count
        assert report.placeholders_found == 2

    def test_substitutions_ok(self, report):
        assert report.substitutions_ok == 1

    def test_error_count(self, report):
        assert report.error_count == 1

    def test_warn_count(self, report):
        assert report.warn_count == 1


class TestAuditReportAsDict:
    def test_structure(self, report):
        d = report.as_dict("schedule.xlsx", "report.docx", "output.docx")
        assert "run_timestamp" in d
        assert d["schedule_file"] == "schedule.xlsx"
        assert d["report_file"] == "report.docx"
        assert d["output_file"] == "output.docx"
        assert "summary" in d
        assert "substitutions" in d
        assert "errors" in d
        assert "warnings" in d

    def test_summary_counts(self, report):
        d = report.as_dict("s.xlsx", "r.docx", "o.docx")
        assert d["summary"]["placeholders_found"] == 2
        assert d["summary"]["substitutions_ok"] == 1
        assert d["summary"]["errors"] == 1
        assert d["summary"]["warnings"] == 1

    def test_substitution_record(self, report):
        d = report.as_dict("s.xlsx", "r.docx", "o.docx")
        sub = d["substitutions"][0]
        assert sub["placeholder"] == "{{MV:ASSET_001:£,0}}"
        assert sub["asset_id"] == "ASSET_001"
        assert sub["field"] == "MV"
        assert sub["raw_value"] == 1_250_000.0
        assert sub["formatted_value"] == "£1,250,000"
        assert sub["location"] == "paragraph:0"

    def test_error_record(self, report):
        d = report.as_dict("s.xlsx", "r.docx", "o.docx")
        err = d["errors"][0]
        assert err["code"] == "ERROR_UNKNOWN_ASSET_ID"
        assert "ASSET_999" in err["message"]

    def test_warning_record(self, report):
        d = report.as_dict("s.xlsx", "r.docx", "o.docx")
        warn = d["warnings"][0]
        assert warn["code"] == "WARN_MALFORMED_PLACEHOLDER"

    def test_json_serialisable(self, report):
        d = report.as_dict("s.xlsx", "r.docx", "o.docx")
        # Should not raise.
        json.dumps(d)


class TestWriteAudit:
    def test_writes_valid_json(self, report, tmp_path):
        audit_path = tmp_path / "audit.json"
        report.write_audit(audit_path, "s.xlsx", "r.docx", "o.docx")
        assert audit_path.exists()
        with open(audit_path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["summary"]["substitutions_ok"] == 1


class TestEmptyReport:
    def test_zero_everything(self):
        r = AuditReport()
        assert r.placeholders_found == 0
        assert r.substitutions_ok == 0
        assert r.error_count == 0
        assert r.warn_count == 0

    def test_dict_has_empty_lists(self):
        r = AuditReport()
        d = r.as_dict("s", "r", "o")
        assert d["substitutions"] == []
        assert d["errors"] == []
        assert d["warnings"] == []


class TestAllErrorTypes:
    def test_unknown_field(self):
        r = AuditReport()
        r.error_unknown_field("{{BAD:A:£,0}}", "BAD", "ASSET_001", "loc")
        assert r.error_count == 1
        assert r.issues[0].code == "ERROR_UNKNOWN_FIELD"

    def test_missing_value(self):
        r = AuditReport()
        r.error_missing_value("{{MV:A:£,0}}", "MV", "A", "loc")
        assert r.error_count == 1
        assert r.issues[0].code == "ERROR_MISSING_VALUE"

    def test_format_error(self):
        r = AuditReport()
        r.error_format("{{MV:A:bad}}", "bad", "loc", "detail msg")
        assert r.error_count == 1
        assert r.issues[0].code == "ERROR_UNKNOWN_FORMAT_SPEC"

    def test_unused_asset_warn(self):
        r = AuditReport()
        r.warn_unused_asset("ASSET_001")
        assert r.warn_count == 1
        assert r.issues[0].code == "WARN_UNUSED_ASSET"
