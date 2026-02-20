"""
test_formatter.py — Tests for all format specs, edge cases, and rounding.
"""

from __future__ import annotations

import pytest

from rnse.formatter import format_value, FormattingError


class TestGBPInteger:
    def test_integer_value(self):
        assert format_value(1_250_000, "£,0") == "£1,250,000"

    def test_float_value_rounds(self):
        assert format_value(1_250_000.9, "£,0") == "£1,250,001"

    def test_zero(self):
        assert format_value(0, "£,0") == "£0"

    def test_negative(self):
        assert format_value(-500_000, "£,0") == "£-500,000"

    def test_small_value(self):
        assert format_value(1, "£,0") == "£1"

    def test_large_value(self):
        assert format_value(999_999_999, "£,0") == "£999,999,999"


class TestGBPTwoDp:
    def test_basic(self):
        assert format_value(1_250_000, "£,0.00") == "£1,250,000.00"

    def test_fractional(self):
        assert format_value(1_250_000.5, "£,0.00") == "£1,250,000.50"

    def test_rounds_half_up(self):
        # 0.005 should round to 0.01, not 0.00
        assert format_value(0.005, "£,0.00") == "£0.01"


class TestGBPMillions:
    def test_basic_1dp(self):
        assert format_value(1_250_000, "£m") == "£1.3m"

    def test_rounds_down(self):
        assert format_value(1_249_999, "£m") == "£1.2m"

    def test_rounds_up(self):
        assert format_value(1_250_001, "£m") == "£1.3m"

    def test_exact(self):
        assert format_value(2_500_000, "£m") == "£2.5m"

    def test_2dp(self):
        assert format_value(1_250_000, "£m2dp") == "£1.25m"

    def test_2dp_rounds(self):
        assert format_value(1_255_000, "£m2dp") == "£1.26m"


class TestPSF:
    def test_basic(self):
        assert format_value(119.05, "psf") == "£119 psf"

    def test_rounds(self):
        assert format_value(119.9, "psf") == "£120 psf"

    def test_zero(self):
        assert format_value(0, "psf") == "£0 psf"


class TestPercentage:
    def test_2dp(self):
        assert format_value(0.0525, "0.00%") == "5.25%"

    def test_0dp(self):
        assert format_value(0.05, "0%") == "5%"

    def test_1dp(self):
        assert format_value(0.0475, "0.0%") == "4.8%"

    def test_zero_percent(self):
        assert format_value(0.0, "0.00%") == "0.00%"

    def test_100_percent(self):
        assert format_value(1.0, "0.00%") == "100.00%"

    def test_rounds_half_up(self):
        # 0.04545 * 100 = 4.545, should round to 4.55%
        assert format_value(0.04545, "0.00%") == "4.55%"

    def test_typical_niy(self):
        assert format_value(0.0480, "0.00%") == "4.80%"


class TestPlainNumber:
    def test_integer(self):
        assert format_value(10_500, "#,##0") == "10,500"

    def test_float_rounds(self):
        assert format_value(10_500.9, "#,##0") == "10,501"

    def test_2dp(self):
        assert format_value(10_500.5, "#,##0.00") == "10,500.50"

    def test_zero(self):
        assert format_value(0, "#,##0") == "0"

    def test_large(self):
        assert format_value(1_000_000, "#,##0") == "1,000,000"


class TestNumberWithSuffix:
    def test_sq_ft(self):
        assert format_value(10_500, "#,##0 sq ft") == "10,500 sq ft"

    def test_sq_ft_with_float(self):
        assert format_value(10_500.4, "#,##0 sq ft") == "10,500 sq ft"

    def test_arbitrary_suffix(self):
        assert format_value(5_000, "#,##0 units") == "5,000 units"

    def test_2dp_with_suffix(self):
        assert format_value(10_500.5, "#,##0.00 sq ft") == "10,500.50 sq ft"


class TestUnknownSpec:
    def test_raises_formatting_error(self):
        with pytest.raises(FormattingError):
            format_value(100, "unknown_spec")

    def test_raises_on_typo(self):
        # Common typo: dot instead of comma
        with pytest.raises(FormattingError):
            format_value(100, "£.0")

    def test_error_message_is_descriptive(self):
        with pytest.raises(FormattingError, match="Unknown format spec"):
            format_value(100, "BAD_SPEC")


class TestParametrisedRounding:
    """Parametrised cases to catch rounding drift in financial formatting."""

    @pytest.mark.parametrize("value,expected", [
        (0.0525, "5.25%"),
        (0.0480, "4.80%"),
        (0.0600, "6.00%"),
        (0.0550, "5.50%"),
        (0.0495, "4.95%"),
        (0.0490, "4.90%"),
        (0.0615, "6.15%"),
    ])
    def test_yield_formatting(self, value: float, expected: str):
        assert format_value(value, "0.00%") == expected

    @pytest.mark.parametrize("value,expected", [
        (1_250_000, "£1,250,000"),
        (875_000, "£875,000"),
        (1_100_000, "£1,100,000"),
        (2_500_000, "£2,500,000"),
        (4_750_000, "£4,750,000"),
    ])
    def test_mv_formatting(self, value: float, expected: str):
        assert format_value(value, "£,0") == expected

    @pytest.mark.parametrize("value,expected", [
        (22_000, "22,000 sq ft"),
        (8_500, "8,500 sq ft"),
        (14_000, "14,000 sq ft"),
        (42_000, "42,000 sq ft"),
        (10_500, "10,500 sq ft"),
    ])
    def test_area_formatting(self, value: float, expected: str):
        assert format_value(value, "#,##0 sq ft") == expected
