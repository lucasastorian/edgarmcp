"""Markdown formatting for financial statements."""

import pandas as pd


def format_as_markdown(
    df: pd.DataFrame,
    symbol: str,
    statement_type: str,
    report_type: str,
    company_name: str = "",
) -> str:
    """Format merged DataFrame as markdown table with formatted values."""
    company_str = f"{company_name} ({symbol})" if company_name else symbol
    statement_label = statement_type.replace("_", " ").title()
    title = f"# {company_str}\n## {statement_label} ({report_type.capitalize()})\n\n"

    if df.empty:
        return title + "No data available."

    if "axis" not in df.columns:
        df["axis"] = ""
    if "dimension" not in df.columns:
        df["dimension"] = False
    if "level" not in df.columns:
        df["level"] = 0
    if "label" not in df.columns:
        df["label"] = df["concept"]

    df["axis"] = df["axis"].fillna("").astype(str)
    df["label"] = df["label"].fillna("").astype(str)
    df["level"] = df["level"].fillna(0).astype(int)
    df["dimension"] = df["dimension"].apply(lambda x: bool(x) if pd.notna(x) else False)

    meta_cols = ["concept", "label", "level", "axis", "dimension", "member", "abstract", "period"]
    period_cols = [col for col in df.columns if col not in meta_cols]

    display_df = df[["label", "level", "axis", "dimension"] + period_cols].copy()
    for col in period_cols:
        display_df[col] = display_df[col].astype(object)

    for idx in display_df.index:
        concept = df.at[idx, "concept"] if "concept" in df.columns else ""
        fmt = _detect_unit_type(concept)
        for col in period_cols:
            display_df.at[idx, col] = _format_value(display_df.at[idx, col], fmt)

    output_rows = []
    current_axis = None

    for _, row in display_df.iterrows():
        if row["dimension"] == False and row["level"] == 0:
            current_axis = None
            label = "  " * int(row["level"]) + row["label"]
            output_rows.append([label] + [row[col] for col in period_cols])
        elif row["dimension"] == True:
            axis = row.get("axis", "")
            if axis and axis != current_axis:
                current_axis = axis
                axis_label = _get_axis_label(axis)
                output_rows.append(["  " + f"[{axis_label}]"] + ["-"] * len(period_cols))
            indent = "  " * (int(row["level"]) + 1)
            label = indent + row["label"]
            output_rows.append([label] + [row[col] for col in period_cols])
        else:
            current_axis = None
            label = "  " * int(row["level"]) + row["label"]
            output_rows.append([label] + [row[col] for col in period_cols])

    final_df = pd.DataFrame(output_rows, columns=["label"] + period_cols)
    markdown = final_df.to_markdown(index=False)

    return title + markdown


def _get_axis_label(axis: str) -> str:
    if not isinstance(axis, str):
        return str(axis) if axis and str(axis) != "nan" else ""

    axis_map = {
        "srt:ProductOrServiceAxis": "Product/Service Breakdown",
        "us-gaap:StatementBusinessSegmentsAxis": "Business Segment Breakdown",
        "srt:StatementGeographicalAxis": "Geographic Breakdown",
        "us-gaap:StatementGeographicalAxis": "Geographic Breakdown",
        "us-gaap:StatementEquityComponentsAxis": "Equity Components",
        "srt:ConsolidationItemsAxis": "Consolidation Items",
    }
    return axis_map.get(axis, axis.split(":")[-1] if ":" in axis else axis)


def _detect_unit_type(concept: str) -> str:
    """Detect whether a concept is currency, per-share, or share count."""
    if not concept:
        return "currency"
    c = concept.lower()
    if "pershare" in c or "per_share" in c:
        return "per_share"
    if "shares" in c or "numberofshare" in c or "stockrepurchased" in c:
        return "shares"
    return "currency"


def _format_value(val, fmt: str = "currency") -> str:
    """Format numeric values with unit-appropriate prefix and scaling."""
    if pd.isna(val) or val == "" or val == 0:
        return "-"
    try:
        num = float(val)
    except (ValueError, TypeError):
        return str(val)

    if fmt == "per_share":
        return f"${num:.2f}"

    prefix = "$" if fmt == "currency" else ""

    if abs(num) >= 1_000_000_000:
        return f"{prefix}{num / 1_000_000_000:.3f}B"
    elif abs(num) >= 1_000_000:
        return f"{prefix}{num / 1_000_000:.3f}M"
    elif abs(num) >= 1_000:
        return f"{prefix}{num / 1_000:.3f}K"
    else:
        return f"{prefix}{num:.3f}"
