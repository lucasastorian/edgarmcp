"""view_financials tool — XBRL financial statements with full period merging."""

import asyncio
import gzip
import json
import logging
from typing import Optional

from edgar._filings import load_sgmls_concurrently
from mcp.server.fastmcp import FastMCP

from ..cache import cache
from ..company import CompanyInfo, resolve_company_cached
from ..filing_loader import _get_accession, load_filing_cached
from ..financials.merger import FinancialStatementMerger
from ..financials.formatter import format_as_markdown
from ..storage import backend as l2_backend
from ..types import EdgarError, StatementType, ReportType

logger = logging.getLogger(__name__)

STATEMENT_METHODS = {
    "income_statement": "income_statement",
    "balance_sheet": "balance_sheet",
    "cash_flow": "cashflow_statement",
}


def register(mcp: FastMCP):
    @mcp.tool(
        name="view_financials",
        description=(
            "Pull financial statements from XBRL with full period merging — no database required.\n\n"
            "Loads XBRL from 10-K/10-Q filings, extracts statement DataFrames, then runs the full "
            "FinancialStatementMerger: Q4 inference (FY - Q1 - Q2 - Q3), YTD normalization "
            "(6M→Q2, 9M→Q3), stock split detection + adjustment, and TTM computation.\n\n"
            "Statement types: income_statement, balance_sheet, cash_flow\n"
            "Report types:\n"
            "- annual: 10-K / 20-F periods\n"
            "- quarterly: individual quarters (Q4 inferred from annual - Q1 - Q2 - Q3)\n"
            "- ttm: trailing twelve months (sum of 4 most recent quarters)\n\n"
            "Also surfaces the notes index from the most recent 10-K for follow-up — "
            "use read_document(note_name=...) to dig into the accounting details.\n\n"
            "First call for a company takes ~5-15s (XBRL download). Cached after that.\n\n"
            "Examples:\n"
            '- view_financials(symbol="AAPL", statement_type="income_statement", report_type="quarterly")\n'
            '- view_financials(symbol="NVDA", statement_type="balance_sheet", report_type="annual", periods=3)\n'
            '- view_financials(symbol="AAPL", statement_type="cash_flow", report_type="ttm")\n'
            '- view_financials(symbol="AAPL", statement_type="income_statement", report_type="quarterly", include_segments=true)\n'
        ),
    )
    async def view_financials(
        symbol: str,
        statement_type: StatementType,
        report_type: ReportType,
        periods: int = 4,
        include_segments: bool = False,
    ) -> str:
        """Pull financial statements from XBRL with full period merging.

        Args:
            symbol: Ticker symbol
            statement_type: income_statement, balance_sheet, or cash_flow
            report_type: annual, quarterly, or ttm
            periods: Number of periods to show (default: 4, max: 8)
            include_segments: Include XBRL dimension breakdowns (default: false)
        """
        periods = min(periods, 8)

        try:
            info = await resolve_company_cached(symbol)
        except EdgarError as e:
            return str(e)

        try:
            filings_to_load = _get_filings_for_financials(info, report_type, periods)
        except Exception as e:
            return f"Failed to fetch filings for {info.symbol}: {e}"

        if not filings_to_load:
            return f"No 10-K/10-Q filings found for {info.symbol}."

        await load_sgmls_concurrently(
            [f for _, f in filings_to_load],
            max_in_flight=16,
            return_exceptions=True,
        )

        statements = []
        latest_10k_accession = None

        for accession, filing in filings_to_load:
            cache.store_filing_ref(accession, filing)

            form = filing.form or ""
            report_date = str(filing.report_date or "")

            if form.replace("/A", "") == "10-K" and latest_10k_accession is None:
                latest_10k_accession = accession

            xbrl_cache_key = f"xbrl/{accession}/{statement_type}.json.gz"
            cached_xbrl = await l2_backend.get(xbrl_cache_key)
            if cached_xbrl:
                try:
                    stmt_data = json.loads(gzip.decompress(cached_xbrl))
                    statements.append(stmt_data)
                    continue
                except Exception:
                    pass

            xbrl = _load_xbrl(filing)
            if xbrl is None:
                continue

            method_name = STATEMENT_METHODS.get(statement_type)
            if not method_name:
                continue

            try:
                stmt_obj = getattr(xbrl.statements, method_name)()
                if stmt_obj is None:
                    continue
                data = stmt_obj.to_dataframe().to_dict(orient="records")
            except Exception as e:
                logger.warning(f"Statement extraction failed for {accession}: {e}")
                continue

            entity_info = xbrl.entity_info if hasattr(xbrl, "entity_info") else {}
            stmt_data = {
                "data": data,
                "report_date": report_date,
                "fiscal_year": entity_info.get("fiscal_year") if entity_info else None,
                "fiscal_period": entity_info.get("fiscal_period") if entity_info else None,
                "form": form,
            }
            statements.append(stmt_data)

            try:
                compressed = gzip.compress(json.dumps(stmt_data).encode())
                asyncio.create_task(l2_backend.put(xbrl_cache_key, compressed))
            except (RuntimeError, Exception):
                pass

        if not statements:
            return f"No XBRL data available for {info.symbol} {statement_type}."

        try:
            merger = FinancialStatementMerger(
                statements=statements,
                report_type=report_type,
                include_segments=include_segments,
            )
            merged_df = merger.merge()
        except Exception as e:
            return f"Financial statement merging failed: {e}"

        if merged_df.empty:
            return f"No merged data available for {info.symbol} {statement_type} ({report_type})."

        meta_cols = ["concept", "label", "level", "dimension", "axis", "member", "abstract", "period"]
        period_cols = [c for c in merged_df.columns if c not in meta_cols]
        if len(period_cols) > periods:
            period_cols = period_cols[-periods:]
            merged_df = merged_df[
                [c for c in merged_df.columns if c in meta_cols or c in period_cols]
            ]

        output = format_as_markdown(merged_df, info.symbol, statement_type, report_type, company_name=info.name)

        if latest_10k_accession:
            notes_section = await _format_notes_index(latest_10k_accession, info)
            if notes_section:
                output += "\n\n" + notes_section

        return output


def _get_filings_for_financials(
    info: CompanyInfo, report_type: str, periods: int
) -> list[tuple[str, object]]:
    filings = []

    if report_type == "annual":
        raw = info.edgar_company.get_filings(form=["10-K", "20-F"])
        count = 0
        for f in raw:
            if count >= periods:
                break
            filings.append((_get_accession(f), f))
            count += 1
    else:
        num_10q = periods + 2
        num_10k = (periods // 4) + 2

        raw_q = info.edgar_company.get_filings(form=["10-Q"])
        count = 0
        for f in raw_q:
            if count >= num_10q:
                break
            filings.append((_get_accession(f), f))
            count += 1

        raw_k = info.edgar_company.get_filings(form=["10-K", "20-F"])
        count = 0
        for f in raw_k:
            if count >= num_10k:
                break
            filings.append((_get_accession(f), f))
            count += 1

    return filings


def _load_xbrl(filing):
    try:
        return filing.xbrl()
    except Exception as e:
        logger.warning(f"XBRL load failed: {e}")
        return None


async def _format_notes_index(accession: str, info: CompanyInfo) -> Optional[str]:
    try:
        parsed = await load_filing_cached(accession, company_info=info)
    except EdgarError:
        return None

    if not parsed.notes:
        return None

    lines = [f"## Related Notes ({parsed.form} — {accession})"]
    for note in parsed.notes:
        lines.append(f"- {note.name}: {note.title}")
    lines.append(f'\nTo read a note: read_document(accession_number="{accession}", note_name="...")')
    return "\n".join(lines)
