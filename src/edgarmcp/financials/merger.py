"""Financial statement merger — Q4 inference, YTD normalization, stock splits, TTM."""

import re
import logging
from typing import Literal, Optional, List, Dict, Any

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

FISCAL_LABEL_RE = re.compile(r"(FY|Q[1-4])\s+(\d{4})")
YTD_LABEL_RE = re.compile(r"(\d+)M\s+(\d{4})")


def parse_ytd_label(label: str) -> tuple:
    """Parse YTD fiscal label like '6M 2023' -> (6, 2023) or (None, None)."""
    if not isinstance(label, str):
        return None, None
    m = YTD_LABEL_RE.search(label)
    if not m:
        return None, None
    try:
        return int(m.group(1)), int(m.group(2))
    except (ValueError, TypeError):
        return None, None


NON_SUMMABLE_CONCEPTS = {
    "us-gaap_EarningsPerShareBasic",
    "us-gaap_EarningsPerShareDiluted",
    "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic",
    "us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding",
    "us-gaap_CommonStockSharesOutstanding",
    "us-gaap_CommonStockSharesIssued",
}

SHARES_CONCEPT = "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic"

EPS_CONCEPTS = {
    "us-gaap_EarningsPerShareBasic",
    "us-gaap_EarningsPerShareDiluted",
}

SHARE_CONCEPTS = {
    "us-gaap_WeightedAverageNumberOfSharesOutstandingBasic",
    "us-gaap_WeightedAverageNumberOfDilutedSharesOutstanding",
    "us-gaap_CommonStockSharesOutstanding",
    "us-gaap_CommonStockSharesIssued",
}


class FinancialStatementMerger:
    """Merges financial statements across periods with Q4 inference, YTD normalization,
    stock split detection, and TTM computation."""

    def __init__(
        self,
        statements: List[Dict[str, Any]],
        report_type: Literal["annual", "quarterly", "ttm"],
        include_segments: bool = False,
        normalize_splits: bool = True,
    ):
        self.statements = statements
        self.report_type = report_type
        self.include_segments = include_segments
        self.normalize_splits = normalize_splits

        self.facts = self._build_fact_frame()
        self.line_order = self._build_line_order()

    def _build_fact_frame(self) -> pd.DataFrame:
        rows: List[Dict[str, Any]] = []

        for stmt in self.statements:
            report_date = stmt.get("report_date")
            fiscal_year = stmt.get("fiscal_year")
            fiscal_period = stmt.get("fiscal_period")
            form = stmt.get("form")

            if fiscal_period == "FY":
                target_period_types = {"annual", "instant"}
            elif fiscal_period is None:
                target_period_types = {"annual", "quarterly", "ytd", "instant"}
            else:
                target_period_types = {"quarterly", "ytd", "instant"}

            data_rows = stmt.get("data") or []
            filtered = [
                r for r in data_rows
                if r.get("period_end") == report_date
                and r.get("period_type") in target_period_types
            ]

            for r in filtered:
                rec = dict(r)
                rec.update({
                    "report_date": report_date,
                    "fiscal_year": fiscal_year,
                    "fiscal_period": fiscal_period,
                    "form": form,
                })
                rows.append(rec)

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)

        defaults = {
            "label": "", "axis": "", "member": "", "level": 0,
            "abstract": False, "dimension": False, "fiscal_label": "",
            "period_start": "", "period_end": "",
        }
        for col, default in defaults.items():
            if col not in df.columns:
                df[col] = default
            else:
                df[col] = df[col].fillna(default)

        df["abstract"] = df["abstract"].astype(bool)
        df["dimension"] = df["dimension"].astype(bool)
        df["axis"] = df["axis"].astype(str)
        df["member"] = df["member"].astype(str)
        df["concept"] = df["concept"].astype(str)
        df["merge_key"] = df.apply(self._build_merge_key, axis=1)

        parsed = df["fiscal_label"].apply(self._parse_fiscal_label)
        df["fiscal_period_code"] = parsed.apply(lambda x: x[0])
        df["fiscal_year_num"] = parsed.apply(lambda x: x[1])
        df["period_end"] = df["period_end"].astype(str)
        df["value"] = pd.to_numeric(df["value"], errors="coerce")

        # Derive fiscal_label for instant (balance sheet) items that lack one
        instant_no_label = (
            (df["period_type"] == "instant")
            & (df["fiscal_label"].isin(["", None]))
        )
        if instant_no_label.any():
            def _derive_label(row):
                fp, fy = row.get("fiscal_period"), row.get("fiscal_year")
                if fp and fy:
                    return f"FY {fy}" if fp == "FY" else f"{fp} {fy}"
                return ""
            df.loc[instant_no_label, "fiscal_label"] = (
                df.loc[instant_no_label].apply(_derive_label, axis=1)
            )
            # Re-parse fiscal labels for the updated rows
            reparsed = df.loc[instant_no_label, "fiscal_label"].apply(self._parse_fiscal_label)
            df.loc[instant_no_label, "fiscal_period_code"] = reparsed.apply(lambda x: x[0])
            df.loc[instant_no_label, "fiscal_year_num"] = reparsed.apply(lambda x: x[1])

        if self.report_type in ("quarterly", "ttm"):
            df = self._normalize_ytd_to_quarterly(df)

        if self.normalize_splits:
            df = self._detect_and_normalize_splits(df)

        return df

    def _detect_and_normalize_splits(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        shares = df[
            (df["concept"] == SHARES_CONCEPT) & (df["dimension"] == False)
        ].copy()

        if shares.empty or len(shares) < 2:
            return df

        shares = shares.drop_duplicates(subset=["period_end"], keep="first")
        shares = shares.sort_values("period_end").reset_index(drop=True)
        shares["prev_value"] = shares["value"].shift(1)
        shares["ratio"] = shares["value"] / shares["prev_value"]

        splits = shares[
            (shares["ratio"] > 1.5) | (shares["ratio"] < 0.67)
        ][["period_end", "ratio"]].copy()

        if splits.empty:
            return df

        for _, split in splits.iterrows():
            split_date = split["period_end"]
            raw_ratio = split["ratio"]

            if raw_ratio > 1:
                ratio = round(raw_ratio)
                mask = df["period_end"] < split_date
                eps_mask = mask & df["concept"].isin(EPS_CONCEPTS) & (df["dimension"] == False)
                df.loc[eps_mask, "value"] = df.loc[eps_mask, "value"] / ratio
                share_mask = mask & df["concept"].isin(SHARE_CONCEPTS) & (df["dimension"] == False)
                df.loc[share_mask, "value"] = df.loc[share_mask, "value"] * ratio
            else:
                ratio = round(1 / raw_ratio)
                mask = df["period_end"] < split_date
                eps_mask = mask & df["concept"].isin(EPS_CONCEPTS) & (df["dimension"] == False)
                df.loc[eps_mask, "value"] = df.loc[eps_mask, "value"] * ratio
                share_mask = mask & df["concept"].isin(SHARE_CONCEPTS) & (df["dimension"] == False)
                df.loc[share_mask, "value"] = df.loc[share_mask, "value"] / ratio

        return df

    def _normalize_ytd_to_quarterly(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        ytd_data = df[df["period_type"] == "ytd"].copy()
        quarterly_data = df[df["period_type"] == "quarterly"].copy()
        other_data = df[~df["period_type"].isin(["ytd", "quarterly"])].copy()

        if ytd_data.empty:
            return df

        ytd_parsed = ytd_data["fiscal_label"].apply(parse_ytd_label)
        ytd_data["ytd_months"] = ytd_parsed.apply(lambda x: x[0])
        ytd_data = ytd_data[ytd_data["ytd_months"].notna()].copy()

        if ytd_data.empty:
            return pd.concat([quarterly_data, other_data], ignore_index=True)

        ytd_duration = ytd_data[ytd_data["period"] == "duration"].copy()
        ytd_instant = ytd_data[ytd_data["period"] != "duration"].copy()

        if ytd_duration.empty:
            return pd.concat([quarterly_data, ytd_instant, other_data], ignore_index=True)

        ytd_duration = ytd_duration[ytd_duration["fiscal_year"].notna()]
        if ytd_duration.empty:
            return pd.concat([quarterly_data, ytd_instant, other_data], ignore_index=True)

        converted_quarters = []

        for year in ytd_duration["fiscal_year"].unique():
            year_ytd = ytd_duration[ytd_duration["fiscal_year"] == year]
            try:
                year_int = int(year)
            except (ValueError, TypeError):
                continue
            year_quarterly = quarterly_data[quarterly_data["fiscal_year_num"] == year_int]

            ytd_6m = year_ytd[year_ytd["ytd_months"] == 6]
            ytd_9m = year_ytd[year_ytd["ytd_months"] == 9]

            if not ytd_6m.empty:
                q1_data = year_quarterly[year_quarterly["fiscal_period_code"] == "Q1"]
                q2_exists = not year_quarterly[year_quarterly["fiscal_period_code"] == "Q2"].empty
                if not q2_exists and not q1_data.empty:
                    q2 = self._compute_quarter_from_ytd(ytd_6m, q1_data, "Q2", int(year))
                    if not q2.empty:
                        converted_quarters.append(q2)

            if not ytd_9m.empty:
                q3_exists = not year_quarterly[year_quarterly["fiscal_period_code"] == "Q3"].empty
                if not q3_exists and not ytd_6m.empty:
                    q3 = self._compute_quarter_from_ytd(ytd_9m, ytd_6m, "Q3", int(year), is_ytd_diff=True)
                    if not q3.empty:
                        converted_quarters.append(q3)

        result_parts = [quarterly_data, other_data]
        if converted_quarters:
            result_parts.extend(converted_quarters)

        return pd.concat(result_parts, ignore_index=True)

    def _compute_quarter_from_ytd(
        self, ytd_df, subtract_df, quarter_code, year, is_ytd_diff=False
    ) -> pd.DataFrame:
        if ytd_df.empty or subtract_df.empty:
            return pd.DataFrame()

        subtract_values = subtract_df.set_index("merge_key")["value"].to_dict()
        result_rows = []

        for _, row in ytd_df.iterrows():
            merge_key = row["merge_key"]
            ytd_value = row["value"]
            if merge_key in subtract_values and pd.notna(ytd_value):
                subtract_value = subtract_values[merge_key]
                if pd.notna(subtract_value):
                    new_row = row.to_dict()
                    new_row["value"] = ytd_value - subtract_value
                    new_row["period_type"] = "quarterly"
                    new_row["fiscal_period_code"] = quarter_code
                    new_row["fiscal_label"] = f"{quarter_code} {int(year)}"
                    new_row["fiscal_year_num"] = int(year)
                    new_row.pop("ytd_months", None)
                    result_rows.append(new_row)

        return pd.DataFrame(result_rows) if result_rows else pd.DataFrame()

    @staticmethod
    def _build_merge_key(row: pd.Series) -> str:
        if row.get("dimension", False):
            return f"{row['concept']}||{row['axis']}||{row['member']}"
        return f"{row['concept']}||||"

    @staticmethod
    def _parse_fiscal_label(label):
        if not isinstance(label, str):
            return None, None
        m = FISCAL_LABEL_RE.search(label)
        if not m:
            return None, None
        p, y = m.groups()
        try:
            return p, int(y)
        except Exception:
            return None, None

    def _build_line_order(self) -> Dict[str, int]:
        if self.facts.empty:
            return {}

        sorted_statements = sorted(self.statements, key=lambda s: s.get("report_date", ""))
        position_groups = {}
        seen_keys = set()

        for stmt in sorted_statements:
            report_date = stmt.get("report_date")
            stmt_facts = self.facts[self.facts["report_date"] == report_date]
            stmt_keys = stmt_facts["merge_key"].drop_duplicates().tolist()

            for position, key in enumerate(stmt_keys):
                if key not in seen_keys:
                    if position not in position_groups:
                        position_groups[position] = []
                    position_groups[position].append(key)
                    seen_keys.add(key)

        ordered_keys = []
        for position in sorted(position_groups.keys()):
            ordered_keys.extend(position_groups[position])

        return {k: i for i, k in enumerate(ordered_keys)}

    def merge(self) -> pd.DataFrame:
        if self.report_type == "annual":
            return self._merge_annual()
        elif self.report_type == "ttm":
            return self._merge_ttm()
        return self._merge_quarterly()

    def _merge_annual(self) -> pd.DataFrame:
        df = self.facts.copy()
        if df.empty:
            return pd.DataFrame()
        df = df[df["period_type"].isin(["annual", "instant"])]
        if not self.include_segments:
            df = df[df["dimension"] == False]
        return self._pivot(df)

    def _merge_quarterly(self) -> pd.DataFrame:
        df = self.facts.copy()
        if df.empty:
            return pd.DataFrame()
        if not self.include_segments:
            df = df[df["dimension"] == False]

        annual = df[df["period_type"] == "annual"].copy()
        quarterly = df[df["period_type"] == "quarterly"].copy()
        instant = df[df["period_type"] == "instant"].copy()

        # Q4 inference for duration items (income statement, cash flow)
        q4 = self._infer_q4(annual, quarterly)
        if not q4.empty:
            quarterly = pd.concat([quarterly, q4], ignore_index=True)

        # For instant items (balance sheet), year-end (FY) values ARE Q4 snapshots
        if not instant.empty:
            fy_mask = instant["fiscal_period_code"] == "FY"
            if fy_mask.any():
                instant.loc[fy_mask, "fiscal_period_code"] = "Q4"
                instant.loc[fy_mask, "fiscal_label"] = instant.loc[fy_mask, "fiscal_year_num"].apply(
                    lambda y: f"Q4 {int(y)}" if pd.notna(y) else ""
                )
            quarterly = pd.concat([quarterly, instant], ignore_index=True)

        return self._pivot(quarterly)

    def _merge_ttm(self) -> pd.DataFrame:
        df = self.facts.copy()
        if df.empty:
            return pd.DataFrame()
        if not self.include_segments:
            df = df[df["dimension"] == False]

        annual = df[df["period_type"] == "annual"].copy()
        quarterly = df[df["period_type"] == "quarterly"].copy()
        instant = df[df["period_type"] == "instant"].copy()

        q4 = self._infer_q4(annual, quarterly)
        if not q4.empty:
            quarterly = pd.concat([quarterly, q4], ignore_index=True)

        # For instant items, relabel FY → Q4
        if not instant.empty:
            fy_mask = instant["fiscal_period_code"] == "FY"
            if fy_mask.any():
                instant.loc[fy_mask, "fiscal_period_code"] = "Q4"
                instant.loc[fy_mask, "fiscal_label"] = instant.loc[fy_mask, "fiscal_year_num"].apply(
                    lambda y: f"Q4 {int(y)}" if pd.notna(y) else ""
                )
            quarterly = pd.concat([quarterly, instant], ignore_index=True)

        if quarterly.empty:
            return pd.DataFrame()

        pivot = self._pivot(quarterly, include_period=True)
        if pivot.empty:
            return pd.DataFrame()

        meta_cols = ["concept", "label", "level", "dimension", "axis", "member", "abstract", "period"]
        quarter_cols = [c for c in pivot.columns if c not in meta_cols]

        quarter_num = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3}

        def q_sort_key(col):
            parts = col.split()
            if len(parts) == 2:
                q, year = parts
                return (int(year), quarter_num.get(q, 9))
            return (9999, 9)

        quarter_cols = sorted(quarter_cols, key=q_sort_key)

        ttm_cols = []
        for i in range(3, len(quarter_cols)):
            cols_4 = quarter_cols[i - 3:i + 1]
            orders = [q_sort_key(c) for c in cols_4]
            is_consecutive = all(
                (orders[j + 1][0] - orders[j][0]) * 4 + (orders[j + 1][1] - orders[j][1]) == 1
                for j in range(3)
            )
            if is_consecutive:
                ttm_label = f"TTM {cols_4[-1]}"
                ttm_cols.append((ttm_label, cols_4))

        if not ttm_cols:
            return pd.DataFrame()

        for ttm_label, cols_4 in ttm_cols:
            def compute_ttm(row, _cols=cols_4):
                period_type = row.get("period", "duration")
                values = [row[c] for c in _cols]
                if any(pd.isna(v) for v in values):
                    return None
                if period_type == "duration":
                    return sum(values)
                else:
                    return values[-1]

            pivot[ttm_label] = pivot.apply(compute_ttm, axis=1)

        ttm_col_names = [t[0] for t in ttm_cols]
        result = pivot[["concept", "label", "level", "dimension", "axis", "member", "abstract"] + ttm_col_names]
        return result

    def _infer_q4(self, annual: pd.DataFrame, quarterly: pd.DataFrame) -> pd.DataFrame:
        if annual.empty or quarterly.empty:
            return pd.DataFrame()

        annual_duration = annual[annual["period"] == "duration"].copy()
        if annual_duration.empty:
            return pd.DataFrame()

        annual_duration = annual_duration[~annual_duration["concept"].isin(NON_SUMMABLE_CONCEPTS)]
        if annual_duration.empty:
            return pd.DataFrame()

        annual_base = annual_duration.rename(columns={"value": "annual_value"})
        quarterly_duration = quarterly[quarterly["period"] == "duration"].copy()
        quarterly_duration = quarterly_duration[~quarterly_duration["concept"].isin(NON_SUMMABLE_CONCEPTS)]

        if quarterly_duration.empty:
            return pd.DataFrame()

        annual_base = annual_base[annual_base["fiscal_year_num"].notna()]
        quarterly_duration = quarterly_duration[quarterly_duration["fiscal_year_num"].notna()]

        if annual_base.empty or quarterly_duration.empty:
            return pd.DataFrame()

        q = quarterly_duration[["merge_key", "fiscal_year_num", "fiscal_period_code", "value"]].copy()
        q_pivot = q.pivot_table(
            index=["merge_key", "fiscal_year_num"],
            columns="fiscal_period_code",
            values="value",
            aggfunc="first",
        ).reset_index()

        merged = annual_base.merge(q_pivot, on=["merge_key", "fiscal_year_num"], how="left")

        def compute_q4(row):
            if pd.isna(row.get("annual_value")):
                return None
            if pd.isna(row.get("Q1")) or pd.isna(row.get("Q2")) or pd.isna(row.get("Q3")):
                return None
            return row["annual_value"] - row["Q1"] - row["Q2"] - row["Q3"]

        merged["q4_value"] = merged.apply(compute_q4, axis=1)
        merged = merged[pd.notna(merged["q4_value"])]

        if merged.empty:
            return pd.DataFrame()

        q4 = merged.copy()
        q4["value"] = q4["q4_value"]
        q4["period_type"] = "quarterly"
        q4["fiscal_period_code"] = "Q4"
        q4["fiscal_label"] = q4["fiscal_year_num"].apply(lambda y: f"Q4 {int(y)}")

        cols = [
            "concept", "label", "value", "period", "period_start", "period_end",
            "period_type", "fiscal_label", "axis", "member", "level", "abstract",
            "dimension", "merge_key", "fiscal_year_num", "fiscal_period_code",
            "report_date", "fiscal_year", "fiscal_period", "form",
        ]
        available_cols = [c for c in cols if c in q4.columns]
        return q4[available_cols]

    def _pivot(self, df: pd.DataFrame, include_period: bool = False) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame()

        index_cols = [
            "merge_key", "concept", "label", "level",
            "dimension", "axis", "member", "abstract",
        ]
        if include_period and "period" in df.columns:
            index_cols.append("period")

        pivot = df.pivot_table(
            index=index_cols,
            columns="fiscal_label",
            values="value",
            aggfunc="first",
        ).reset_index()

        if self.line_order:
            pivot["_order"] = pivot["merge_key"].map(self.line_order).fillna(1e9)
        else:
            pivot["_order"] = range(len(pivot))

        pivot = pivot.sort_values(["_order"]).reset_index(drop=True)
        pivot = pivot.drop(columns=["merge_key", "_order"])

        meta_cols = ["concept", "label", "level", "dimension", "axis", "member", "abstract"]
        if include_period and "period" in pivot.columns:
            meta_cols.append("period")
        fiscal_cols = [c for c in pivot.columns if c not in meta_cols]

        def fiscal_sort_key(col: str):
            parts = col.split()
            if len(parts) == 2:
                period, year = parts
                period_order = {"FY": 0, "Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}.get(period, 9)
                try:
                    return (int(year), period_order)
                except ValueError:
                    return (9999, 9)
            elif len(parts) == 3 and parts[0] == "TTM":
                period, year = parts[1], parts[2]
                period_order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4}.get(period, 9)
                try:
                    return (int(year), period_order)
                except ValueError:
                    return (9999, 9)
            return (9999, 9)

        fiscal_cols_sorted = sorted(fiscal_cols, key=fiscal_sort_key)
        pivot = pivot[meta_cols + fiscal_cols_sorted]
        return pivot
