"""
formatter.py — Pure formatting functions.

format_value(value: float, spec: str) -> str

Format specs supported:
  £,0          GBP, thousands sep, integer
  £,0.00       GBP, thousands sep, 2dp
  £m           GBP millions, 1dp
  £m2dp        GBP millions, 2dp
  0.00%        Percentage (value × 100), 2dp
  0%           Percentage, 0dp
  #,##0        Plain number, thousands sep, integer
  #,##0.00     Plain number, 2dp
  #,##0 <sfx>  Plain number + literal suffix (e.g. "#,##0 sq ft")
  psf          £/sq ft, integer, £ prefix

All formatting is locale-independent (comma thousands, dot decimal).
Uses Decimal with ROUND_HALF_UP for financial precision.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal


class FormattingError(Exception):
    """Raised when the format spec is not recognised or value is unusable."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_decimal(value: float) -> Decimal:
    """Convert a float to Decimal for precise rounding."""
    return Decimal(str(value))


def _round_half_up(d: Decimal, places: int) -> Decimal:
    """Round a Decimal to *places* decimal places using ROUND_HALF_UP."""
    if places == 0:
        quantize_str = Decimal("1")
    else:
        quantize_str = Decimal("0." + "0" * places)
    return d.quantize(quantize_str, rounding=ROUND_HALF_UP)


def _format_with_commas(value: float, decimal_places: int) -> str:
    """
    Format *value* with thousands separators and *decimal_places* dp.
    Always uses ',' for thousands and '.' for decimal.
    """
    d = _round_half_up(_to_decimal(value), decimal_places)
    if decimal_places == 0:
        integer_part = int(d)
        return f"{integer_part:,}"
    else:
        # Format to fixed decimal places.
        formatted = f"{d:f}"
        # Split on decimal point and reformat integer part with commas.
        if "." in formatted:
            int_part, frac_part = formatted.split(".", 1)
        else:
            int_part, frac_part = formatted, "0" * decimal_places
        frac_part = frac_part[:decimal_places].ljust(decimal_places, "0")
        return f"{int(int_part):,}.{frac_part}"


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

# Compiled regex for specs with a suffix after #,##0, e.g. "#,##0 sq ft"
_COMMA_NUMBER_WITH_SUFFIX_RE = re.compile(r"^#,##0\.?(0*)(?:\s+(.+))?$")

# Compiled regex for percentage specs, e.g. "0.00%" or "0%"
_PERCENT_RE = re.compile(r"^(0)(\.0*)?\%$")


def format_value(value: float, spec: str) -> str:
    """
    Format *value* according to *spec* and return the formatted string.

    Raises FormattingError if the spec is not recognised.
    """
    spec = spec.strip()

    # ---- GBP integer: £,0 -------------------------------------------------
    if spec == "£,0":
        return "£" + _format_with_commas(value, 0)

    # ---- GBP 2dp: £,0.00 --------------------------------------------------
    if spec == "£,0.00":
        return "£" + _format_with_commas(value, 2)

    # ---- GBP millions 1dp: £m ---------------------------------------------
    if spec == "£m":
        millions = float(_to_decimal(str(value))) / 1_000_000
        return "£" + _format_with_commas(millions, 1) + "m"

    # ---- GBP millions 2dp: £m2dp ------------------------------------------
    if spec == "£m2dp":
        millions = float(_to_decimal(str(value))) / 1_000_000
        return "£" + _format_with_commas(millions, 2) + "m"

    # ---- Per sq ft: psf ---------------------------------------------------
    if spec == "psf":
        return "£" + _format_with_commas(value, 0) + " psf"

    # ---- Percentage: 0%, 0.00%, 0.0%, etc. --------------------------------
    pct_m = _PERCENT_RE.match(spec)
    if pct_m:
        frac_part = pct_m.group(2) or ""
        decimal_places = len(frac_part) - 1 if frac_part else 0  # subtract the "."
        pct_value = float(_to_decimal(str(value))) * 100
        return _format_with_commas(pct_value, decimal_places) + "%"

    # ---- Plain number with optional suffix: #,##0, #,##0.00, #,##0 sq ft -
    cn_m = _COMMA_NUMBER_WITH_SUFFIX_RE.match(spec)
    if cn_m:
        frac_zeros = cn_m.group(1) or ""
        suffix = cn_m.group(2) or ""
        decimal_places = len(frac_zeros)
        formatted = _format_with_commas(value, decimal_places)
        if suffix:
            return formatted + " " + suffix
        return formatted

    raise FormattingError(
        f"Unknown format spec: {spec!r}. "
        "Supported: £,0  £,0.00  £m  £m2dp  0.00%  0%  #,##0  #,##0.00  "
        "#,##0 <suffix>  psf"
    )
