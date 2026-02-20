"""
test_demo.py — Tests that the demo generator produces valid, processable files.
"""

from __future__ import annotations

import pytest

from rnse.demo import generate_demo_schedule, generate_demo_report, DEMO_ASSETS
from rnse.loader import load_schedule, load_document
from rnse.validator import validate_schedule, has_fatal, has_errors
from rnse.engine import substitute_document
from rnse.reporter import AuditReport


@pytest.fixture
def demo_dir(tmp_path):
    return tmp_path / "demo"


@pytest.fixture
def schedule_path(demo_dir):
    demo_dir.mkdir(parents=True, exist_ok=True)
    return generate_demo_schedule(demo_dir)


@pytest.fixture
def report_path(demo_dir):
    demo_dir.mkdir(parents=True, exist_ok=True)
    return generate_demo_report(demo_dir)


class TestDemoSchedule:
    def test_file_created(self, schedule_path):
        assert schedule_path.exists()
        assert schedule_path.suffix == ".xlsx"

    def test_loads_without_error(self, schedule_path):
        raw, fields = load_schedule(schedule_path)
        assert raw
        assert fields

    def test_has_expected_assets(self, schedule_path):
        raw, _ = load_schedule(schedule_path)
        for asset in DEMO_ASSETS:
            assert asset["Asset_ID"] in raw

    def test_has_expected_fields(self, schedule_path):
        _, fields = load_schedule(schedule_path)
        for expected_field in ["MV", "NIY", "RENT", "ERV", "AREA", "CAPITAL_VALUE"]:
            assert expected_field in fields

    def test_validates_cleanly(self, schedule_path):
        raw, fields = load_schedule(schedule_path)
        schedule, issues = validate_schedule(raw, fields, schedule_path)
        fatal_or_error = [i for i in issues if i.severity.value in ("FATAL", "ERROR")]
        assert fatal_or_error == []

    def test_schedule_values_are_floats(self, schedule_path):
        raw, fields = load_schedule(schedule_path)
        schedule, _ = validate_schedule(raw, fields, schedule_path)
        for asset_id, asset_data in schedule.items():
            for field, value in asset_data.items():
                if value is not None:
                    assert isinstance(value, float), (
                        f"Expected float for {asset_id}.{field}, got {type(value)}"
                    )


class TestDemoReport:
    def test_file_created(self, report_path):
        assert report_path.exists()
        assert report_path.suffix == ".docx"

    def test_loads_without_error(self, report_path):
        doc = load_document(report_path)
        assert doc is not None

    def test_contains_placeholders(self, report_path):
        doc = load_document(report_path)
        all_text = "\n".join(p.text for p in doc.paragraphs)
        # The report should contain some {{ tokens (possibly split across runs).
        from rnse.parser import build_run_spans, parse_placeholders
        found_tokens = []
        for para in doc.paragraphs:
            combined, _ = build_run_spans(para.runs)
            found_tokens.extend(parse_placeholders(combined))
        # Also check tables and footers.
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        combined, _ = build_run_spans(para.runs)
                        found_tokens.extend(parse_placeholders(combined))
        assert len(found_tokens) > 0, "Demo report should contain placeholders"


class TestEndToEnd:
    def test_full_sync_produces_no_errors(self, schedule_path, report_path):
        raw, fields = load_schedule(schedule_path)
        schedule, val_issues = validate_schedule(raw, fields, schedule_path)
        assert not has_fatal(val_issues)

        doc = load_document(report_path)
        reporter = AuditReport()
        substitute_document(doc, schedule, reporter)

        assert reporter.error_count == 0, (
            f"Expected 0 errors, got {reporter.error_count}: "
            + str([i for i in reporter.issues if i.severity == "ERROR"])
        )
        assert reporter.substitutions_ok > 0, "Expected at least one substitution"

    def test_full_sync_output_contains_values(self, schedule_path, report_path, tmp_path):
        raw, fields = load_schedule(schedule_path)
        schedule, _ = validate_schedule(raw, fields, schedule_path)
        doc = load_document(report_path)

        reporter = AuditReport()
        substitute_document(doc, schedule, reporter)

        output_path = tmp_path / "output.docx"
        doc.save(str(output_path))

        # Reload and verify no placeholders remain.
        from rnse.parser import build_run_spans, parse_placeholders
        doc2 = load_document(output_path)
        remaining_tokens = []
        for para in doc2.paragraphs:
            combined, _ = build_run_spans(para.runs)
            remaining_tokens.extend(parse_placeholders(combined))
        for table in doc2.tables:
            for row in table.rows:
                for cell in row.cells:
                    for para in cell.paragraphs:
                        combined, _ = build_run_spans(para.runs)
                        remaining_tokens.extend(parse_placeholders(combined))

        assert remaining_tokens == [], (
            f"Expected all placeholders replaced, but {len(remaining_tokens)} remain: "
            + str([t.raw for t in remaining_tokens])
        )

    def test_audit_report_structure(self, schedule_path, report_path, tmp_path):
        raw, fields = load_schedule(schedule_path)
        schedule, _ = validate_schedule(raw, fields, schedule_path)
        doc = load_document(report_path)

        reporter = AuditReport()
        substitute_document(doc, schedule, reporter)

        audit_path = tmp_path / "audit.json"
        reporter.write_audit(audit_path, str(schedule_path), str(report_path), "output.docx")

        import json
        data = json.loads(audit_path.read_text(encoding="utf-8"))
        assert data["summary"]["errors"] == 0
        assert data["summary"]["substitutions_ok"] > 0
        assert len(data["substitutions"]) > 0

    def test_custom_asset_count(self, tmp_path):
        """Demo generator respects the assets count parameter."""
        out = tmp_path / "demo"
        out.mkdir()
        assets = DEMO_ASSETS[:2]
        schedule_path = generate_demo_schedule(out, assets)
        raw, fields = load_schedule(schedule_path)
        schedule, _ = validate_schedule(raw, fields, schedule_path)
        assert len(schedule) == 2
