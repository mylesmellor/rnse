"""
validator.py — Validate the Excel schedule and (optionally) the Word document.

Collect-all strategy: all errors are gathered before returning, so the user
sees the complete picture in one run rather than one error at a time.

Error codes follow the taxonomy in the architecture plan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    WARN  = "WARN"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    location: Optional[str] = None

    def __str__(self) -> str:
        loc = f" [{self.location}]" if self.location else ""
        return f"[{self.severity.value}] {self.code}{loc}: {self.message}"


# Validated schedule type: Asset_ID → {FIELD → float | None}
Schedule = dict[str, dict[str, Optional[float]]]


# ---------------------------------------------------------------------------
# Main validators
# ---------------------------------------------------------------------------

def validate_schedule(
    raw_schedule: dict,
    field_names: list[str],
    source_path: Path,
) -> tuple[Schedule, list[ValidationIssue]]:
    """
    Validate *raw_schedule* (as returned by loader.load_schedule).

    Returns (schedule, issues).
    *schedule* is a clean {Asset_ID: {field: float|None}} dict.
    FATAL issues mean the caller should abort; non-fatal issues are informational.

    Checks performed (collected, not fail-fast):
    1. Sheet exists (raw_schedule non-empty signals sheet was found)
    2. Asset_ID and Asset_Name columns present (field_names / raw_schedule populated)
    3. No duplicate Asset_IDs
    4. No empty Asset_ID cells
    5. All field values numeric or None
    6. At least one data row
    """
    issues: list[ValidationIssue] = []
    schedule: Schedule = {}

    # Check 1: sheet exists (loader returns empty dict/list if missing).
    if raw_schedule == {} and field_names == []:
        # Could be missing sheet or missing required columns.
        issues.append(ValidationIssue(
            code="ERROR_MISSING_SHEET",
            severity=Severity.FATAL,
            message=f"Sheet 'Schedule' not found in {source_path.name}",
        ))
        return schedule, issues

    # Check 2: required columns present.
    # loader returns ({}, []) if Asset_ID or Asset_Name is missing.
    if not raw_schedule and not field_names:
        issues.append(ValidationIssue(
            code="ERROR_MISSING_COLUMN",
            severity=Severity.FATAL,
            message="Column 'Asset_ID' or 'Asset_Name' is absent from the Schedule sheet",
        ))
        return schedule, issues

    # Check 3 & 4: duplicate and empty Asset_IDs.
    seen_ids: set[str] = set()
    empty_count = 0
    dup_ids: set[str] = set()

    for raw_key in raw_schedule:
        if raw_key == "__EMPTY__":
            empty_count += 1
            continue
        if "__DUP__" in raw_key:
            original = raw_key.split("__DUP__")[0]
            dup_ids.add(original)
            continue
        seen_ids.add(raw_key)

    if empty_count:
        issues.append(ValidationIssue(
            code="ERROR_MISSING_COLUMN",
            severity=Severity.FATAL,
            message=f"{empty_count} row(s) have an empty Asset_ID",
        ))

    for dup in sorted(dup_ids):
        issues.append(ValidationIssue(
            code="ERROR_DUPLICATE_ASSET_ID",
            severity=Severity.FATAL,
            message=f"Asset_ID '{dup}' appears more than once in the schedule",
        ))

    # Check 5: No data rows (only empties/dups found).
    valid_asset_ids = {k for k in raw_schedule if k != "__EMPTY__" and "__DUP__" not in k}
    if not valid_asset_ids and not dup_ids:
        issues.append(ValidationIssue(
            code="ERROR_NO_DATA_ROWS",
            severity=Severity.FATAL,
            message="The Schedule sheet contains no asset data rows",
        ))
        return schedule, issues

    # Build clean schedule, converting values.
    for asset_id in sorted(valid_asset_ids):
        raw_fields = raw_schedule[asset_id]
        clean_fields: dict[str, Optional[float]] = {}

        for fn in field_names:
            raw_val = raw_fields.get(fn)

            if raw_val is None or raw_val == "":
                clean_fields[fn] = None
                issues.append(ValidationIssue(
                    code="WARN_EMPTY_FIELD_VALUE",
                    severity=Severity.WARN,
                    message=f"Field '{fn}' for asset '{asset_id}' is blank",
                    location=f"asset:{asset_id}:field:{fn}",
                ))
                continue

            # openpyxl may return int, float, or str.
            if isinstance(raw_val, (int, float)):
                clean_fields[fn] = float(raw_val)
            elif isinstance(raw_val, str):
                stripped = raw_val.strip()
                if stripped.upper() == "N/A":
                    clean_fields[fn] = None
                    issues.append(ValidationIssue(
                        code="WARN_EMPTY_FIELD_VALUE",
                        severity=Severity.WARN,
                        message=f"Field '{fn}' for asset '{asset_id}' is 'N/A'",
                        location=f"asset:{asset_id}:field:{fn}",
                    ))
                else:
                    # Try to coerce.
                    try:
                        clean_fields[fn] = float(stripped.replace(",", ""))
                    except ValueError:
                        clean_fields[fn] = None
                        issues.append(ValidationIssue(
                            code="ERROR_NON_NUMERIC_VALUE",
                            severity=Severity.ERROR,
                            message=(
                                f"Field '{fn}' for asset '{asset_id}' contains "
                                f"non-numeric text: {raw_val!r}"
                            ),
                            location=f"asset:{asset_id}:field:{fn}",
                        ))
            else:
                # Unexpected type (e.g. datetime).
                clean_fields[fn] = None
                issues.append(ValidationIssue(
                    code="ERROR_NON_NUMERIC_VALUE",
                    severity=Severity.ERROR,
                    message=(
                        f"Field '{fn}' for asset '{asset_id}' has unexpected type "
                        f"{type(raw_val).__name__}: {raw_val!r}"
                    ),
                    location=f"asset:{asset_id}:field:{fn}",
                ))

        schedule[asset_id] = clean_fields

    log.debug("Validation complete: %d assets, %d issues", len(schedule), len(issues))
    return schedule, issues


def validate_document_placeholders(document, schedule: Schedule) -> list[ValidationIssue]:
    """
    Pre-flight check on the Word document's placeholder syntax.
    Does NOT perform substitution.

    Checks:
    - All Asset_IDs referenced in placeholders exist in schedule
    - All fields referenced exist in schedule columns
    - Malformed {{ tokens

    Returns a list of issues (WARN and ERROR level only; no FATAL here).
    """
    from rnse.parser import parse_placeholders, has_malformed_placeholder, build_run_spans
    from rnse.engine import iter_paragraph_groups

    issues: list[ValidationIssue] = []
    seen_asset_ids: set[str] = set()
    all_fields: set[str] = set()
    if schedule:
        first_asset = next(iter(schedule.values()))
        all_fields = set(first_asset.keys())

    for para, location in iter_paragraph_groups(document):
        runs = para.runs
        if not runs:
            continue
        combined, _ = build_run_spans(runs)
        if "{{" not in combined:
            continue

        tokens = parse_placeholders(combined)
        if has_malformed_placeholder(combined, tokens):
            issues.append(ValidationIssue(
                code="WARN_MALFORMED_PLACEHOLDER",
                severity=Severity.WARN,
                message=f"Malformed placeholder token near: {combined[:80]!r}",
                location=location,
            ))

        for token in tokens:
            if token.asset_id not in schedule:
                issues.append(ValidationIssue(
                    code="ERROR_UNKNOWN_ASSET_ID",
                    severity=Severity.ERROR,
                    message=f"Asset_ID '{token.asset_id}' not found in schedule",
                    location=location,
                ))
            elif token.field not in all_fields:
                issues.append(ValidationIssue(
                    code="ERROR_UNKNOWN_FIELD",
                    severity=Severity.ERROR,
                    message=f"Field '{token.field}' not found in schedule columns",
                    location=location,
                ))

        seen_asset_ids.update(t.asset_id for t in tokens)

    # Warn about assets in schedule that never appear in the document.
    for asset_id in schedule:
        if asset_id not in seen_asset_ids:
            issues.append(ValidationIssue(
                code="WARN_UNUSED_ASSET",
                severity=Severity.WARN,
                message=f"Asset '{asset_id}' in schedule has no placeholders in the document",
            ))

    return issues


def has_fatal(issues: list[ValidationIssue]) -> bool:
    return any(i.severity == Severity.FATAL for i in issues)


def has_errors(issues: list[ValidationIssue]) -> bool:
    return any(i.severity in (Severity.FATAL, Severity.ERROR) for i in issues)
