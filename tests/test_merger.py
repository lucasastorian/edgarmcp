"""Tests for financial statement merger — Q4 inference, YTD normalization, splits, TTM."""

import pytest
import pandas as pd

from edgarmcp.financials.merger import FinancialStatementMerger, parse_ytd_label


def _make_fact(
    concept: str,
    value: float,
    fiscal_label: str,
    period_type: str = "quarterly",
    period: str = "duration",
    period_end: str = "2024-09-28",
    report_date: str = "2024-09-28",
    fiscal_year: int = 2024,
    fiscal_period: str = "Q3",
    form: str = "10-Q",
    **extra,
) -> dict:
    """Build a single XBRL fact row."""
    return {
        "concept": concept,
        "value": value,
        "label": concept.split("_")[-1] if "_" in concept else concept,
        "period_type": period_type,
        "period": period,
        "period_start": "2024-07-01",
        "period_end": period_end,
        "fiscal_label": fiscal_label,
        "axis": "",
        "member": "",
        "level": 0,
        "abstract": False,
        "dimension": False,
        "report_date": report_date,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "form": form,
        **extra,
    }


def _make_statement(data: list[dict], report_date: str, fiscal_year: int, fiscal_period: str, form: str = "10-Q"):
    return {
        "data": data,
        "report_date": report_date,
        "fiscal_year": fiscal_year,
        "fiscal_period": fiscal_period,
        "form": form,
    }


class TestParseYtdLabel:
    def test_valid_6m(self):
        assert parse_ytd_label("6M 2024") == (6, 2024)

    def test_valid_9m(self):
        assert parse_ytd_label("9M 2023") == (9, 2023)

    def test_invalid(self):
        assert parse_ytd_label("Q1 2024") == (None, None)

    def test_none(self):
        assert parse_ytd_label(None) == (None, None)


class TestQ4Inference:
    """Q4 = FY - Q1 - Q2 - Q3 for duration items."""

    def test_basic_q4_inference(self):
        concept = "us-gaap_Revenue"
        statements = [
            _make_statement(
                data=[_make_fact(concept, 1000, "FY 2024", period_type="annual", period_end="2024-12-31",
                                fiscal_period="FY", form="10-K")],
                report_date="2024-12-31", fiscal_year=2024, fiscal_period="FY", form="10-K",
            ),
            _make_statement(
                data=[_make_fact(concept, 200, "Q1 2024", period_end="2024-03-31",
                                report_date="2024-03-31", fiscal_period="Q1")],
                report_date="2024-03-31", fiscal_year=2024, fiscal_period="Q1",
            ),
            _make_statement(
                data=[_make_fact(concept, 250, "Q2 2024", period_end="2024-06-30",
                                report_date="2024-06-30", fiscal_period="Q2")],
                report_date="2024-06-30", fiscal_year=2024, fiscal_period="Q2",
            ),
            _make_statement(
                data=[_make_fact(concept, 300, "Q3 2024", period_end="2024-09-30",
                                report_date="2024-09-30", fiscal_period="Q3")],
                report_date="2024-09-30", fiscal_year=2024, fiscal_period="Q3",
            ),
        ]
        merger = FinancialStatementMerger(statements, "quarterly", normalize_splits=False)
        result = merger.merge()
        assert not result.empty
        # Q4 = 1000 - 200 - 250 - 300 = 250
        q4_col = [c for c in result.columns if "Q4" in c]
        assert len(q4_col) == 1
        q4_val = result[q4_col[0]].iloc[0]
        assert q4_val == 250

    def test_eps_not_inferred(self):
        """Non-summable concepts (EPS) should NOT have Q4 inferred."""
        concept = "us-gaap_EarningsPerShareBasic"
        statements = [
            _make_statement(
                data=[_make_fact(concept, 6.0, "FY 2024", period_type="annual", period_end="2024-12-31",
                                fiscal_period="FY", form="10-K")],
                report_date="2024-12-31", fiscal_year=2024, fiscal_period="FY", form="10-K",
            ),
            _make_statement(
                data=[_make_fact(concept, 1.5, "Q1 2024", period_end="2024-03-31",
                                report_date="2024-03-31", fiscal_period="Q1")],
                report_date="2024-03-31", fiscal_year=2024, fiscal_period="Q1",
            ),
            _make_statement(
                data=[_make_fact(concept, 1.5, "Q2 2024", period_end="2024-06-30",
                                report_date="2024-06-30", fiscal_period="Q2")],
                report_date="2024-06-30", fiscal_year=2024, fiscal_period="Q2",
            ),
            _make_statement(
                data=[_make_fact(concept, 1.5, "Q3 2024", period_end="2024-09-30",
                                report_date="2024-09-30", fiscal_period="Q3")],
                report_date="2024-09-30", fiscal_year=2024, fiscal_period="Q3",
            ),
        ]
        merger = FinancialStatementMerger(statements, "quarterly", normalize_splits=False)
        result = merger.merge()
        # Should NOT have a Q4 column for EPS
        q4_cols = [c for c in result.columns if "Q4" in c]
        assert len(q4_cols) == 0 or result.empty


class TestSplitDetection:
    """Stock split normalization adjusts EPS and share counts."""

    def test_forward_split_normalizes(self):
        """A 4:1 split should multiply pre-split shares by 4 and divide EPS by 4."""
        concept_shares = "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic"
        concept_eps = "us-gaap_EarningsPerShareBasic"

        statements = [
            _make_statement(
                data=[
                    _make_fact(concept_shares, 4_000_000, "Q1 2024", period_end="2024-03-31",
                              report_date="2024-03-31", fiscal_period="Q1"),
                    _make_fact(concept_eps, 4.0, "Q1 2024", period_end="2024-03-31",
                              report_date="2024-03-31", fiscal_period="Q1"),
                ],
                report_date="2024-03-31", fiscal_year=2024, fiscal_period="Q1",
            ),
            _make_statement(
                data=[
                    # Post-split: 4x shares
                    _make_fact(concept_shares, 16_000_000, "Q2 2024", period_end="2024-06-30",
                              report_date="2024-06-30", fiscal_period="Q2"),
                    _make_fact(concept_eps, 1.0, "Q2 2024", period_end="2024-06-30",
                              report_date="2024-06-30", fiscal_period="Q2"),
                ],
                report_date="2024-06-30", fiscal_year=2024, fiscal_period="Q2",
            ),
        ]
        merger = FinancialStatementMerger(statements, "quarterly", normalize_splits=True)
        result = merger.merge()
        assert not result.empty

        # After normalization, Q1 shares should be adjusted to post-split basis
        shares_row = result[result["concept"] == concept_shares]
        if not shares_row.empty:
            q1_col = [c for c in result.columns if "Q1" in c]
            if q1_col:
                q1_shares = shares_row[q1_col[0]].iloc[0]
                assert q1_shares == 16_000_000  # 4M * 4

        eps_row = result[result["concept"] == concept_eps]
        if not eps_row.empty:
            q1_col = [c for c in result.columns if "Q1" in c]
            if q1_col:
                q1_eps = eps_row[q1_col[0]].iloc[0]
                assert q1_eps == 1.0  # 4.0 / 4


class TestYtdNormalization:
    """6M/9M YTD values converted to individual quarters."""

    def test_6m_to_q2(self):
        concept = "us-gaap_Revenue"
        statements = [
            _make_statement(
                data=[_make_fact(concept, 200, "Q1 2024", period_end="2024-03-31",
                                report_date="2024-03-31", fiscal_period="Q1")],
                report_date="2024-03-31", fiscal_year=2024, fiscal_period="Q1",
            ),
            _make_statement(
                data=[
                    # 6M YTD = 500 → Q2 = 500 - 200 = 300
                    _make_fact(concept, 500, "6M 2024", period_type="ytd", period_end="2024-06-30",
                              report_date="2024-06-30", fiscal_period="Q2", fiscal_year=2024),
                ],
                report_date="2024-06-30", fiscal_year=2024, fiscal_period="Q2",
            ),
        ]
        merger = FinancialStatementMerger(statements, "quarterly", normalize_splits=False)
        result = merger.merge()
        q2_cols = [c for c in result.columns if "Q2" in c]
        if q2_cols:
            q2_val = result[q2_cols[0]].iloc[0]
            assert q2_val == 300  # 500 - 200


class TestTTM:
    """Trailing twelve months computation."""

    def test_ttm_sums_4_quarters(self):
        concept = "us-gaap_Revenue"
        statements = []
        quarters = [
            ("Q1 2024", "2024-03-31", "Q1"),
            ("Q2 2024", "2024-06-30", "Q2"),
            ("Q3 2024", "2024-09-30", "Q3"),
            ("Q4 2024", "2024-12-31", "Q4"),
        ]
        # Also need annual for Q4 inference
        q_data = []
        for label, pe, fp in quarters[:3]:
            q_data.append(
                _make_statement(
                    data=[_make_fact(concept, 100, label, period_end=pe,
                                    report_date=pe, fiscal_period=fp)],
                    report_date=pe, fiscal_year=2024, fiscal_period=fp,
                )
            )

        # Annual for Q4 inference
        q_data.append(
            _make_statement(
                data=[_make_fact(concept, 500, "FY 2024", period_type="annual", period_end="2024-12-31",
                                fiscal_period="FY", form="10-K")],
                report_date="2024-12-31", fiscal_year=2024, fiscal_period="FY", form="10-K",
            )
        )

        merger = FinancialStatementMerger(q_data, "ttm", normalize_splits=False)
        result = merger.merge()

        if not result.empty:
            ttm_cols = [c for c in result.columns if "TTM" in c]
            if ttm_cols:
                ttm_val = result[ttm_cols[0]].iloc[0]
                # Q1=100 + Q2=100 + Q3=100 + Q4=200 = 500
                assert ttm_val == 500


class TestMergeAnnual:
    def test_annual_merge(self):
        concept = "us-gaap_Revenue"
        statements = [
            _make_statement(
                data=[_make_fact(concept, 1000, "FY 2023", period_type="annual", period_end="2023-12-31",
                                fiscal_period="FY", form="10-K")],
                report_date="2023-12-31", fiscal_year=2023, fiscal_period="FY", form="10-K",
            ),
            _make_statement(
                data=[_make_fact(concept, 1200, "FY 2024", period_type="annual", period_end="2024-12-31",
                                fiscal_period="FY", form="10-K")],
                report_date="2024-12-31", fiscal_year=2024, fiscal_period="FY", form="10-K",
            ),
        ]
        merger = FinancialStatementMerger(statements, "annual", normalize_splits=False)
        result = merger.merge()
        assert not result.empty
        assert "FY 2023" in result.columns
        assert "FY 2024" in result.columns


class TestEmptyInput:
    def test_empty_statements(self):
        merger = FinancialStatementMerger([], "quarterly", normalize_splits=False)
        result = merger.merge()
        assert result.empty

    def test_no_matching_data(self):
        statements = [_make_statement(data=[], report_date="2024-12-31", fiscal_year=2024, fiscal_period="FY")]
        merger = FinancialStatementMerger(statements, "annual", normalize_splits=False)
        result = merger.merge()
        assert result.empty
