"""
reporter.py — Collect substitutions/errors and emit the audit report.

AuditReport is a mutable collector.  After the engine finishes, call
write_audit() to emit audit.json and print_table() to display a Rich summary.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

log = logging.getLogger(__name__)
console = Console(stderr=True)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SubstitutionRecord:
    placeholder: str
    asset_id: str
    field: str
    raw_value: float
    formatted_value: str
    location: str


@dataclass
class IssueRecord:
    code: str
    severity: str   # "ERROR" | "WARN"
    placeholder: Optional[str]
    location: str
    message: str


# ---------------------------------------------------------------------------
# AuditReport
# ---------------------------------------------------------------------------

class AuditReport:
    """Mutable collector for substitutions and issues during engine run."""

    def __init__(self) -> None:
        self.substitutions: list[SubstitutionRecord] = []
        self.issues: list[IssueRecord] = []
        self._placeholders_found: int = 0

    # --- Recording helpers --------------------------------------------------

    def record_substitution(
        self,
        placeholder: str,
        asset_id: str,
        field: str,
        raw_value: float,
        formatted_value: str,
        location: str,
    ) -> None:
        self._placeholders_found += 1
        self.substitutions.append(
            SubstitutionRecord(
                placeholder=placeholder,
                asset_id=asset_id,
                field=field,
                raw_value=raw_value,
                formatted_value=formatted_value,
                location=location,
            )
        )

    def _issue(self, code: str, severity: str, msg: str, placeholder: Optional[str], location: str) -> None:
        self._placeholders_found += 1
        self.issues.append(
            IssueRecord(code=code, severity=severity, placeholder=placeholder, location=location, message=msg)
        )
        log.warning("%s at %s: %s", code, location, msg)

    def error_unknown_asset(self, placeholder: str, asset_id: str, location: str) -> None:
        self._issue(
            "ERROR_UNKNOWN_ASSET_ID", "ERROR",
            f"Asset_ID '{asset_id}' not found in schedule",
            placeholder, location,
        )

    def error_unknown_field(self, placeholder: str, field: str, asset_id: str, location: str) -> None:
        self._issue(
            "ERROR_UNKNOWN_FIELD", "ERROR",
            f"Field '{field}' not found for asset '{asset_id}'",
            placeholder, location,
        )

    def error_missing_value(self, placeholder: str, field: str, asset_id: str, location: str) -> None:
        self._issue(
            "ERROR_MISSING_VALUE", "ERROR",
            f"Value for field '{field}' of asset '{asset_id}' is None/empty",
            placeholder, location,
        )

    def error_format(self, placeholder: str, fmt: str, location: str, detail: str) -> None:
        self._issue(
            "ERROR_UNKNOWN_FORMAT_SPEC", "ERROR",
            f"Format spec {fmt!r} not recognised: {detail}",
            placeholder, location,
        )

    def warn_malformed(self, excerpt: str, location: str) -> None:
        # Don't count as a placeholder found.
        self.issues.append(
            IssueRecord(
                code="WARN_MALFORMED_PLACEHOLDER",
                severity="WARN",
                placeholder=None,
                location=location,
                message=f"'{{{{' found but no valid placeholder matched near: {excerpt!r}",
            )
        )

    def warn_unused_asset(self, asset_id: str) -> None:
        self.issues.append(
            IssueRecord(
                code="WARN_UNUSED_ASSET",
                severity="WARN",
                placeholder=None,
                location="schedule",
                message=f"Asset '{asset_id}' has no placeholders in the document",
            )
        )

    # --- Computed properties ------------------------------------------------

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    @property
    def warn_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARN")

    @property
    def placeholders_found(self) -> int:
        return self._placeholders_found

    @property
    def substitutions_ok(self) -> int:
        return len(self.substitutions)

    # --- Output methods -----------------------------------------------------

    def as_dict(
        self,
        schedule_file: str,
        report_file: str,
        output_file: str,
    ) -> dict:
        return {
            "run_timestamp": datetime.now().isoformat(timespec="seconds"),
            "schedule_file": schedule_file,
            "report_file": report_file,
            "output_file": output_file,
            "summary": {
                "placeholders_found": self.placeholders_found,
                "substitutions_ok": self.substitutions_ok,
                "errors": self.error_count,
                "warnings": self.warn_count,
            },
            "substitutions": [
                {
                    "placeholder": s.placeholder,
                    "asset_id": s.asset_id,
                    "field": s.field,
                    "raw_value": s.raw_value,
                    "formatted_value": s.formatted_value,
                    "location": s.location,
                }
                for s in self.substitutions
            ],
            "errors": [
                {
                    "code": i.code,
                    "placeholder": i.placeholder,
                    "location": i.location,
                    "message": i.message,
                }
                for i in self.issues
                if i.severity == "ERROR"
            ],
            "warnings": [
                {
                    "code": i.code,
                    "placeholder": i.placeholder,
                    "location": i.location,
                    "message": i.message,
                }
                for i in self.issues
                if i.severity == "WARN"
            ],
        }

    def write_audit(
        self,
        audit_path: Path,
        schedule_file: str,
        report_file: str,
        output_file: str,
    ) -> None:
        data = self.as_dict(schedule_file, report_file, output_file)
        audit_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Audit report written to %s", audit_path)

    def print_table(self) -> None:
        """Print a Rich summary table to stderr."""
        ok = self.substitutions_ok
        errors = self.error_count
        warns = self.warn_count

        # Summary row
        summary = Table(box=box.ROUNDED, show_header=True, title="RNSE Audit Summary")
        summary.add_column("Placeholders Found", justify="right")
        summary.add_column("Substitutions OK", justify="right")
        summary.add_column("Errors", justify="right")
        summary.add_column("Warnings", justify="right")

        err_style = "bold red" if errors else "green"
        warn_style = "yellow" if warns else "green"

        summary.add_row(
            str(self.placeholders_found),
            f"[green]{ok}[/green]",
            f"[{err_style}]{errors}[/{err_style}]",
            f"[{warn_style}]{warns}[/{warn_style}]",
        )
        console.print(summary)

        if self.issues:
            issue_table = Table(box=box.SIMPLE, show_header=True, title="Issues")
            issue_table.add_column("Severity", style="bold")
            issue_table.add_column("Code")
            issue_table.add_column("Location")
            issue_table.add_column("Message")

            for issue in self.issues:
                sev_style = "red" if issue.severity == "ERROR" else "yellow"
                issue_table.add_row(
                    f"[{sev_style}]{issue.severity}[/{sev_style}]",
                    issue.code,
                    issue.location or "",
                    issue.message,
                )
            console.print(issue_table)
