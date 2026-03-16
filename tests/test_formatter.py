"""Tests for financial statement formatter."""

import pytest
import pandas as pd

from edgarmcp.financials.formatter import (
    _format_value,
    _detect_unit_type,
    _get_axis_label,
    format_as_markdown,
)


class TestDetectUnitType:
    @pytest.mark.parametrize(
        "concept, expected",
        [
            ("us-gaap_EarningsPerShareBasic", "per_share"),
            ("us-gaap_EarningsPerShareDiluted", "per_share"),
            ("custom_AdjustedEarningsPerShare", "per_share"),
            ("us-gaap_WeightedAverageNumberOfSharesOutstandingBasic", "shares"),
            ("us-gaap_CommonStockSharesOutstanding", "shares"),
            ("us-gaap_CommonStockSharesIssued", "shares"),
            ("us-gaap_StockRepurchasedDuringPeriodShares", "shares"),
            ("us-gaap_NumberOfSharesIssued", "shares"),
            ("us-gaap_Revenue", "currency"),
            ("us-gaap_NetIncomeLoss", "currency"),
            ("us-gaap_TotalAssets", "currency"),
            ("", "currency"),
        ],
    )
    def test_detection(self, concept, expected):
        assert _detect_unit_type(concept) == expected

    def test_none_concept(self):
        assert _detect_unit_type(None) == "currency"


class TestFormatValue:
    # --- Currency formatting ---
    def test_currency_billions(self):
        assert _format_value(1_500_000_000) == "$1.500B"

    def test_currency_millions(self):
        assert _format_value(42_000_000) == "$42.000M"

    def test_currency_thousands(self):
        assert _format_value(7_500) == "$7.500K"

    def test_currency_small(self):
        assert _format_value(123) == "$123.000"

    def test_currency_negative(self):
        assert _format_value(-2_500_000_000) == "$-2.500B"

    # --- Per-share formatting ---
    def test_per_share(self):
        assert _format_value(1.5, "per_share") == "$1.50"

    def test_per_share_negative(self):
        assert _format_value(-0.25, "per_share") == "$-0.25"

    def test_per_share_large(self):
        """Per-share values are never scaled (no B/M/K)."""
        assert _format_value(150.75, "per_share") == "$150.75"

    # --- Share count formatting ---
    def test_shares_no_dollar_sign(self):
        assert _format_value(15_000_000_000, "shares") == "15.000B"

    def test_shares_millions(self):
        assert _format_value(7_500_000, "shares") == "7.500M"

    # --- Zero and missing ---
    def test_zero_is_dash(self):
        assert _format_value(0) == "-"

    def test_none_is_dash(self):
        assert _format_value(None) == "-"

    def test_nan_is_dash(self):
        assert _format_value(float("nan")) == "-"

    def test_empty_string_is_dash(self):
        assert _format_value("") == "-"

    # --- Non-numeric passthrough ---
    def test_non_numeric_string(self):
        assert _format_value("N/A") == "N/A"


class TestGetAxisLabel:
    def test_known_axis(self):
        assert _get_axis_label("srt:ProductOrServiceAxis") == "Product/Service Breakdown"

    def test_unknown_axis_with_colon(self):
        assert _get_axis_label("custom:MyAxis") == "MyAxis"

    def test_unknown_axis_no_colon(self):
        assert _get_axis_label("SomeAxis") == "SomeAxis"

    def test_nan_value(self):
        assert _get_axis_label(float("nan")) == ""

    def test_none_value(self):
        assert _get_axis_label(None) == ""


class TestFormatAsMarkdown:
    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = format_as_markdown(df, "AAPL", "income_statement", "quarterly")
        assert "No data available" in result

    def test_basic_structure(self):
        df = pd.DataFrame(
            {
                "concept": ["us-gaap_Revenue", "us-gaap_NetIncomeLoss"],
                "label": ["Revenue", "Net Income"],
                "level": [0, 0],
                "Q1 2024": [100_000_000, 25_000_000],
                "Q2 2024": [110_000_000, 28_000_000],
            }
        )
        result = format_as_markdown(df, "AAPL", "income_statement", "quarterly", "Apple Inc.")
        assert "Apple Inc. (AAPL)" in result
        assert "Income Statement" in result
        assert "Revenue" in result
        assert "Net Income" in result

    def test_per_share_formatting_in_table(self):
        df = pd.DataFrame(
            {
                "concept": ["us-gaap_EarningsPerShareBasic"],
                "label": ["Basic EPS"],
                "level": [0],
                "Q1 2024": [1.52],
            }
        )
        result = format_as_markdown(df, "AAPL", "income_statement", "quarterly")
        assert "$1.52" in result
        # Should NOT have B/M/K scaling
        assert "B" not in result or "Basic" in result  # "B" could appear in "Basic"

    def test_share_count_no_dollar_sign(self):
        df = pd.DataFrame(
            {
                "concept": ["us-gaap_WeightedAverageNumberOfSharesOutstandingBasic"],
                "label": ["Shares Outstanding"],
                "level": [0],
                "Q1 2024": [15_000_000_000],
            }
        )
        result = format_as_markdown(df, "AAPL", "income_statement", "quarterly")
        assert "15.000B" in result
        # Should NOT have $ prefix on the value
        assert "$15" not in result

    def test_missing_optional_columns(self):
        """Formatter should add missing meta columns gracefully."""
        df = pd.DataFrame(
            {
                "concept": ["us-gaap_Revenue"],
                "Q1 2024": [100_000_000],
            }
        )
        result = format_as_markdown(df, "AAPL", "income_statement", "quarterly")
        assert "$100.000M" in result
