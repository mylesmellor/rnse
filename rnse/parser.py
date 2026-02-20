"""
parser.py — Placeholder grammar, regex, and run-merging logic.

Grammar: {{FIELD:ASSET_ID:FORMAT_SPEC}}

  FIELD       — UPPERCASE letters and underscores only (starts with letter)
  ASSET_ID    — UPPERCASE letters, digits, underscores (may start with letter or digit)
  FORMAT_SPEC — Printable chars except { and }; trimmed

Run-merging strategy:
  Word may split a single placeholder across multiple runs (e.g. when the
  user applied bold to part of the token text). The parser concatenates all
  run texts, finds placeholders in the combined string, then maps character
  positions back to individual runs so the replacement can be applied without
  creating or deleting run objects.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Placeholder regex
# ---------------------------------------------------------------------------

PLACEHOLDER_RE = re.compile(
    r"\{\{([A-Z][A-Z_]*):([ A-Z0-9_]+):([^{}]+?)\}\}"
)

# Regex to detect *any* {{ opening — used to warn about malformed tokens.
DOUBLE_BRACE_RE = re.compile(r"\{\{")


@dataclass(frozen=True)
class PlaceholderToken:
    """Parsed representation of a single placeholder."""

    raw: str          # e.g. "{{MV:ASSET_001:£,0}}"
    field: str        # e.g. "MV"
    asset_id: str     # e.g. "ASSET_001"
    format_spec: str  # e.g. "£,0"
    start: int        # character index in the combined run string
    end: int          # character index (exclusive)


class RunSpan(NamedTuple):
    """Maps a character range in combined text to a run index."""

    run_index: int
    char_start: int   # inclusive, within the combined string
    char_end: int     # exclusive, within the combined string


def parse_placeholders(text: str) -> list[PlaceholderToken]:
    """
    Find all valid placeholders in *text* and return them in order.
    """
    tokens: list[PlaceholderToken] = []
    for m in PLACEHOLDER_RE.finditer(text):
        field = m.group(1).strip()
        asset_id = m.group(2).strip()
        fmt = m.group(3).strip()
        tokens.append(
            PlaceholderToken(
                raw=m.group(0),
                field=field,
                asset_id=asset_id,
                format_spec=fmt,
                start=m.start(),
                end=m.end(),
            )
        )
    return tokens


def has_malformed_placeholder(text: str, valid_tokens: list[PlaceholderToken]) -> bool:
    """
    Return True if *text* contains '{{' that is NOT part of a valid token.
    Used to emit WARN_MALFORMED_PLACEHOLDER.
    """
    valid_starts = {t.start for t in valid_tokens}
    for m in DOUBLE_BRACE_RE.finditer(text):
        if m.start() not in valid_starts:
            return True
    return False


# ---------------------------------------------------------------------------
# Run span building
# ---------------------------------------------------------------------------

def build_run_spans(runs: list) -> tuple[str, list[RunSpan]]:
    """
    Concatenate run texts and build a list of RunSpan objects that map
    character positions in the combined string back to run indices.

    Returns (combined_text, spans).
    """
    parts: list[str] = []
    spans: list[RunSpan] = []
    pos = 0
    for i, run in enumerate(runs):
        text = run.text or ""
        end = pos + len(text)
        spans.append(RunSpan(run_index=i, char_start=pos, char_end=end))
        parts.append(text)
        pos = end
    return "".join(parts), spans


def apply_replacement(
    runs: list,
    token: PlaceholderToken,
    replacement: str,
    spans: list[RunSpan],
) -> None:
    """
    Replace the placeholder text in *runs* with *replacement*.

    Strategy:
    - Find all runs that overlap [token.start, token.end).
    - Write *replacement* into the .text of the first overlapping run.
    - Set .text = "" on all subsequent overlapping runs.
    - Preserve the formatting (rPr) of the first overlapping run.
    """
    overlapping: list[int] = []
    for span in spans:
        # A run overlaps if it intersects [token.start, token.end).
        if span.char_end > token.start and span.char_start < token.end:
            overlapping.append(span.run_index)

    if not overlapping:
        return

    first_idx = overlapping[0]
    last_idx = overlapping[-1]
    first_span = spans[first_idx]
    last_span = spans[last_idx]

    # Text in the first run *before* the placeholder starts.
    prefix = runs[first_idx].text[: max(0, token.start - first_span.char_start)]
    # Text in the last run *after* the placeholder ends.
    suffix = runs[last_idx].text[max(0, token.end - last_span.char_start):]

    if first_idx == last_idx:
        # Entire placeholder sits within a single run — preserve both sides.
        runs[first_idx].text = prefix + replacement + suffix
    else:
        # Multi-run span:
        #   first run  → prefix + replacement
        #   last run   → suffix (text after placeholder end)
        #   middle runs → zeroed
        runs[first_idx].text = prefix + replacement
        for idx in overlapping[1:-1]:
            runs[idx].text = ""
        runs[last_idx].text = suffix


def merge_and_replace(runs: list, schedule: dict, formatter, reporter, location: str) -> None:
    """
    High-level entry point: given a list of python-docx Run objects,
    find all placeholders (handling run-splitting) and perform replacements.

    *schedule* is a dict[asset_id][field] → float | None.
    *formatter* is the format_value function.
    *reporter* is the AuditReport instance.
    *location* is a human-readable location string for the audit trail.
    """
    if not runs:
        return

    combined, spans = build_run_spans(runs)

    # Fast path: no double-braces at all.
    if "{{" not in combined:
        return

    tokens = parse_placeholders(combined)

    if has_malformed_placeholder(combined, tokens):
        reporter.warn_malformed(combined[:120], location)

    if not tokens:
        return

    # Process tokens in reverse order so character positions remain valid
    # after each replacement (though apply_replacement doesn't shift positions
    # in the combined string — it only mutates run .text).
    # We process in reverse to avoid prefix/suffix overlap issues.
    for token in reversed(tokens):
        asset_id = token.asset_id
        field = token.field
        fmt = token.format_spec

        if asset_id not in schedule:
            reporter.error_unknown_asset(token.raw, asset_id, location)
            continue

        asset_data = schedule[asset_id]

        if field not in asset_data:
            reporter.error_unknown_field(token.raw, field, asset_id, location)
            continue

        raw_value = asset_data[field]

        if raw_value is None:
            reporter.error_missing_value(token.raw, field, asset_id, location)
            continue

        try:
            formatted = formatter(raw_value, fmt)
        except Exception as exc:
            reporter.error_format(token.raw, fmt, location, str(exc))
            continue

        apply_replacement(runs, token, formatted, spans)
        reporter.record_substitution(
            placeholder=token.raw,
            asset_id=asset_id,
            field=field,
            raw_value=raw_value,
            formatted_value=formatted,
            location=location,
        )

        # Rebuild spans for the next token (processed in reverse, so spans
        # before the current token are unaffected; spans after would shift,
        # but we've already processed those).
        # Actually since we process in reverse order and earlier tokens have
        # smaller start indices, rebuilding is unnecessary — earlier tokens'
        # spans are untouched.
