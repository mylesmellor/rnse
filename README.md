# RNSE — Report Number Synchronisation Engine

Deterministic placeholder substitution for Word valuation reports.

Reads a structured Excel schedule, scans a Word document for explicit tokens, replaces each token with a formatted value, and emits a full audit trail. No AI, no magic — just reliable, repeatable document automation.

---

## The Problem

Commercial real estate valuation reports repeat the same numbers across multiple sections — market value, yield, rent, ERV, area — all maintained manually from Excel schedules. Every revision cycle means finding and updating each figure by hand, creating inconsistency risk and unnecessary rework.

## The Solution

Place explicit tokens in the Word template:

```
The property has been assessed at a market value of {{MV:LON_001:£,0}},
reflecting a net initial yield of {{NIY:LON_001:0.00%}}.
```

Run one command:

```
rnse sync --schedule schedule.xlsx --report report.docx
```

Every token is replaced with the correct, formatted value from the schedule. An audit log records every substitution and every error.

---

## Installation

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
```

---

## Quick Start

Generate demo files and run a full sync in two commands:

```bash
rnse demo --output-dir ./demo
rnse sync --schedule demo/schedule.xlsx --report demo/report.docx --output demo/output.docx
```

---

## Placeholder Grammar

```
{{FIELD:ASSET_ID:FORMAT_SPEC}}
```

| Component | Rules | Examples |
|-----------|-------|---------|
| `FIELD` | Uppercase letters and underscores | `MV`, `NIY`, `TOPPED_UP_NIY` |
| `ASSET_ID` | Uppercase letters, digits, underscores | `LON_001`, `ASSET_001` |
| `FORMAT_SPEC` | Printable chars except `{` and `}` | `£,0`, `0.00%`, `#,##0 sq ft` |

### Format Specs

| Spec | Input | Output |
|------|-------|--------|
| `£,0` | `1250000` | `£1,250,000` |
| `£,0.00` | `1250000` | `£1,250,000.00` |
| `£m` | `1250000` | `£1.3m` |
| `£m2dp` | `1250000` | `£1.25m` |
| `0.00%` | `0.0525` | `5.25%` |
| `0%` | `0.05` | `5%` |
| `#,##0` | `10500` | `10,500` |
| `#,##0 sq ft` | `10500` | `10,500 sq ft` |
| `psf` | `119.05` | `£119 psf` |

---

## Excel Schedule Format

Sheet named `Schedule`, wide format (one row per asset):

| Asset_ID | Asset_Name | MV | NIY | RENT | ERV | AREA |
|----------|------------|----|-----|------|-----|------|
| LON_001 | 100 Bishopsgate, EC2 | 2500000 | 0.0475 | 112500 | 125000 | 22000 |

- `Asset_ID` and `Asset_Name` columns are required
- All other columns are available as field codes in placeholders
- Values must be numeric; percentages stored as decimals (5.25% → `0.0525`)

---

## CLI Reference

### `rnse demo`

Generate demo `schedule.xlsx` and `report.docx` for immediate testing.

```
rnse demo [--output-dir PATH] [--assets N]
```

### `rnse sync`

Core command. Reads schedule, processes report, writes output.

```
rnse sync --schedule PATH --report PATH [OPTIONS]

Options:
  --output PATH    Output .docx path (default: <report>_synced.docx)
  --audit PATH     Audit JSON path (default: audit.json)
  --no-audit       Skip writing audit file
  --strict         Abort on any ERROR, not just FATAL
  --quiet          Suppress output except errors
  --verbose        Debug logging
```

### `rnse validate`

Validate schedule and report without producing output. Safe dry-run.

```
rnse validate --schedule PATH [--report PATH]
```

Exit codes: `0` = clean, `1` = warnings only, `2` = errors present.

### `rnse info`

Summarise the schedule: assets, fields, values.

```
rnse info --schedule PATH
```

---

## Audit Report

Every run writes `audit.json`:

```json
{
  "summary": {
    "placeholders_found": 24,
    "substitutions_ok": 24,
    "errors": 0,
    "warnings": 0
  },
  "substitutions": [
    {
      "placeholder": "{{MV:LON_001:£,0}}",
      "asset_id": "LON_001",
      "field": "MV",
      "raw_value": 2500000.0,
      "formatted_value": "£2,500,000",
      "location": "paragraph:12"
    }
  ],
  "errors": [],
  "warnings": []
}
```

Errors are collected across the entire document (not fail-fast), so you see the complete picture in one run. Failed placeholders are left unchanged in the output document.

---

## Error Codes

| Code | Severity | Meaning |
|------|----------|---------|
| `ERROR_MISSING_SHEET` | FATAL | `Schedule` sheet not found |
| `ERROR_MISSING_COLUMN` | FATAL | `Asset_ID` or `Asset_Name` absent |
| `ERROR_DUPLICATE_ASSET_ID` | FATAL | Same Asset_ID appears more than once |
| `ERROR_NO_DATA_ROWS` | FATAL | Schedule has no asset rows |
| `ERROR_NON_NUMERIC_VALUE` | ERROR | Field cell contains non-numeric text |
| `ERROR_UNKNOWN_ASSET_ID` | ERROR | Placeholder references unknown asset |
| `ERROR_UNKNOWN_FIELD` | ERROR | Placeholder references unknown field |
| `ERROR_MISSING_VALUE` | ERROR | Field value is None/empty |
| `ERROR_UNKNOWN_FORMAT_SPEC` | ERROR | Format spec not recognised |
| `WARN_MALFORMED_PLACEHOLDER` | WARN | `{{` found but regex did not match |
| `WARN_UNUSED_ASSET` | WARN | Asset in schedule has no placeholders |
| `WARN_EMPTY_FIELD_VALUE` | WARN | Field cell is blank |

---

## Architecture

```
schedule.xlsx  →  Loader  →  Validator  →  Schedule dict
report.docx    →  Loader  →  Engine (paragraph/table/header/footer walk)
                                 →  Parser (run-merge + placeholder regex)
                                 →  Formatter (format spec dispatch)
                                 →  Reporter (audit trail)
                             →  output.docx + audit.json
```

Word splits runs arbitrarily when formatting is applied mid-token. The parser concatenates all run texts, matches placeholders in the combined string, maps character positions back to individual runs, and performs in-place replacement — no XML manipulation required.

---

## Tests

```bash
pytest tests/ -v
```

148 tests covering: placeholder regex, run-merging, all format specs, schema validation, table cells, headers/footers, error collection, and full end-to-end demo generation.

---

## MVP Scope

**Included:** body paragraphs, table cells, section headers and footers, all standard format specs, collect-all validation, JSON audit report, demo generator.

**Out of scope (Phase 2):** footnotes, text boxes, Word content controls, multiple schedules, GUI.
