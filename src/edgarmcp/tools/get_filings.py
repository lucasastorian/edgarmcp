"""get_filings tool — discover a company's SEC filings, attachments, and notes."""

from datetime import date, timedelta
from typing import Optional

from edgar._filings import load_sgmls_concurrently
from mcp.server.fastmcp import FastMCP

from ..attachment_types import SKIP_EXHIBITS, infer_attachment_type, matches_attachment_type
from ..cache import cache
from ..citations import registry as citation_registry
from ..company import CompanyInfo, resolve_company
from ..filing_loader import load_filing
from ..types import AttachmentType, FormType, DEFAULT_FORMS


def register(mcp: FastMCP):
    @mcp.tool(
        name="get_filings",
        description=(
            "Discover a company's SEC filings, attachments, and notes — all as a flat document list.\n\n"
            "Combines company lookup + filing listing + attachment listing + notes listing in a single tool. "
            "Supports filtering by form type, attachment type, and date range.\n\n"
            "Response modes:\n"
            "- Default: filing list table with attachment summaries\n"
            "- With attachment_types: flat list of matching attachments across filings\n"
            "- With include_notes=true: filings with notes to financial statements listed (slower — requires parsing)\n\n"
            "Attachment types:\n"
            "- press_release, investor_presentation, cfo_commentary, shareholder_letter — from EX-99.x\n"
            "- material_contract (EX-10.x), merger_agreement (EX-2.1), debt_instrument (EX-4.x)\n"
            "- charter (EX-3.x), bylaws (EX-3.2), indenture (EX-4.1)\n\n"
            "Examples:\n"
            '- get_filings(company="AAPL") — list recent filings\n'
            '- get_filings(company="AAPL", attachment_types=["press_release"], limit=4) — last 4 press releases\n'
            '- get_filings(company="AAPL", forms=["10-K"], include_notes=true, limit=1) — 10-K with notes index\n'
            '- get_filings(company="TSLA", attachment_types=["material_contract"], limit=10) — Tesla contracts\n'
        ),
    )
    async def get_filings(
        company: str,
        forms: Optional[list[FormType]] = None,
        attachment_types: Optional[list[AttachmentType]] = None,
        include_notes: bool = False,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """Discover a company's SEC filings, attachments, and notes.

        Args:
            company: Ticker symbol, company name, or CIK number
            forms: Filter by form type (default: 10-K, 10-Q, 8-K, 20-F, DEF 14A)
            attachment_types: Filter to filings with these attachment types (flat output)
            include_notes: Include notes to financial statements (default: false)
            start_date: YYYY-MM-DD (default: 2 years ago)
            end_date: YYYY-MM-DD (default: today)
            limit: Max documents returned (default: 20, max: 100)
        """
        # Resolve company
        result = resolve_company(company)
        if isinstance(result, str):
            return result
        info: CompanyInfo = result

        # Defaults
        if forms is None:
            forms = list(DEFAULT_FORMS)
        limit = min(limit, 100)
        if not start_date:
            start_date = (date.today() - timedelta(days=730)).isoformat()
        if not end_date:
            end_date = date.today().isoformat()

        # Fetch filings from edgartools
        try:
            date_range = f"{start_date}:{end_date}"
            filings = info.edgar_company.get_filings(form=forms, date=date_range)
        except Exception as e:
            return f"Failed to fetch filings for {info.symbol}: {e}"

        if not filings or len(filings) == 0:
            return f"No filings found for {info.symbol} ({', '.join(forms)}) in {start_date} to {end_date}."

        # Store EntityFiling refs for read_document
        filing_list = []
        for f in filings:
            accession = f.accession_number if hasattr(f, 'accession_number') else str(f.accession_no)
            cache.store_filing_ref(accession, f)
            filing_list.append((accession, f))

        # Pre-fetch SGMLs in parallel (needed for attachment listing in all modes)
        prefetch = filing_list if attachment_types else filing_list[:limit]
        await load_sgmls_concurrently(
            [f for _, f in prefetch],
            max_in_flight=16,
            return_exceptions=True,
        )

        # Route to appropriate output mode
        if attachment_types:
            return _format_attachment_list(info, filing_list, attachment_types, limit)
        elif include_notes:
            return _format_with_notes(info, filing_list, limit)
        else:
            return _format_filing_list(info, filing_list, limit)


def _format_filing_list(info: CompanyInfo, filing_list: list, limit: int) -> str:
    """Default mode — filing list with attachment summary."""
    lines = [f"# {info.symbol} — {info.name} (CIK: {info.cik})\n"]
    lines.append("| # | Form | Date | Report Date | Description | Accession | Attachments |")
    lines.append("|---|------|------|-------------|-------------|-----------|-------------|")

    count = 0
    for accession, f in filing_list:
        if count >= limit:
            break
        form = getattr(f, 'form', '')
        filing_date = str(getattr(f, 'filing_date', ''))
        report_date = str(getattr(f, 'report_date', '') or '')
        description = getattr(f, 'description', '') or form

        # Get attachment summary
        att_parts = _get_attachment_summary(f)
        att_str = ", ".join(att_parts[:3])
        if len(att_parts) > 3:
            att_str += f" +{len(att_parts) - 3} more"

        # Citation for filing row — links to the filing HTML
        cite = ""
        if citation_registry.enabled:
            cid = citation_registry.add(
                accession_number=accession,
                element_ids=["sec2md-p1"],  # first element as landing point
                source_type="main",
                form=form,
                filing_date=filing_date,
                company_name=info.name,
                company_symbol=info.symbol,
            )
            cite = citation_registry.format_tag(cid)

        count += 1
        lines.append(
            f"| {count} | {form} | {filing_date} | {report_date} | "
            f"{description}{cite} | {accession} | {att_str} |"
        )

    total = len(filing_list)
    lines.append(f"\nShowing {count} of {total} filings.")
    return "\n".join(lines)


def _format_attachment_list(
    info: CompanyInfo, filing_list: list, attachment_types: list[str], limit: int
) -> str:
    """Flat attachment list filtered by type."""
    type_label = ", ".join(t.replace("_", " ").title() for t in attachment_types)
    lines = [f"# {info.symbol} — {info.name} — {type_label}\n"]
    lines.append("| # | Date | Form | Exhibit | Description | Accession |")
    lines.append("|---|------|------|---------|-------------|-----------|")

    count = 0
    total = 0
    for accession, f in filing_list:
        try:
            documents = f.attachments.documents if hasattr(f, 'attachments') else []
        except Exception:
            continue

        filing_date = str(getattr(f, 'filing_date', ''))
        form = getattr(f, 'form', '')

        for doc in documents:
            if not doc.document_type or not doc.document_type.startswith("EX-"):
                continue
            if doc.document_type in SKIP_EXHIBITS:
                continue

            exhibit_num = doc.document_type.replace("EX-", "")
            description = doc.description or ""
            att_type = infer_attachment_type(exhibit_num, description)

            if not matches_attachment_type(att_type, attachment_types):
                continue

            total += 1
            if count >= limit:
                continue

            # Citation for attachment row
            cite = ""
            if citation_registry.enabled:
                cid = citation_registry.add(
                    accession_number=accession,
                    element_ids=["sec2md-p1"],
                    source_type="attachment",
                    form=form,
                    filing_date=filing_date,
                    company_name=info.name,
                    company_symbol=info.symbol,
                    exhibit_number=exhibit_num,
                )
                cite = citation_registry.format_tag(cid)

            count += 1
            lines.append(
                f"| {count} | {filing_date} | {form} | {exhibit_num} | "
                f"{description}{cite} | {accession} |"
            )

    lines.append(f"\nShowing {count} of {total} {type_label.lower()}.")
    lines.append(f'\nTo read: read_document(accession_number="...", exhibit_number="...")')
    return "\n".join(lines)


def _format_with_notes(info: CompanyInfo, filing_list: list, limit: int) -> str:
    """Filings with notes listed (requires full parse)."""
    forms_str = set()
    for _, f in filing_list:
        forms_str.add(getattr(f, 'form', ''))

    form_label = ", ".join(sorted(forms_str))
    lines = [f"# {info.symbol} — {info.name} — {form_label} Filings\n"]

    count = 0
    for accession, f in filing_list:
        if count >= limit:
            break
        count += 1

        form = getattr(f, 'form', '')
        filing_date = str(getattr(f, 'filing_date', ''))
        report_date = str(getattr(f, 'report_date', '') or '')

        lines.append(f"## {form} — {filing_date} ({report_date}) — {accession}\n")

        # List attachments
        att_parts = _get_attachment_summary(f)
        if att_parts:
            lines.append("**Attachments:**")
            for att in att_parts:
                lines.append(f"- {att}")
            lines.append("")

        # Load and list notes (triggers full parse)
        parsed = load_filing(accession, filing=f, company_info=info)
        if isinstance(parsed, str):
            lines.append(f"*Could not parse: {parsed}*\n")
            continue

        if parsed.notes:
            lines.append("**Notes to Financial Statements:**")
            for note in parsed.notes:
                lines.append(f"- {note.name}: {note.title}")
            lines.append("")
            lines.append(f'To read a note: read_document(accession_number="{accession}", note_name="...")\n')
        else:
            lines.append("*No notes extracted.*\n")

    return "\n".join(lines)


def _get_attachment_summary(filing) -> list[str]:
    """Get attachment type summaries for a filing."""
    parts = []
    try:
        documents = filing.attachments.documents if hasattr(filing, 'attachments') else []
    except Exception:
        return parts

    seen = set()
    for doc in documents:
        if not doc.document_type or not doc.document_type.startswith("EX-"):
            continue
        if doc.document_type in SKIP_EXHIBITS:
            continue

        exhibit_num = doc.document_type.replace("EX-", "")
        if exhibit_num in seen:
            continue
        seen.add(exhibit_num)

        description = doc.description or ""
        att_type = infer_attachment_type(exhibit_num, description)
        parts.append(f"EX-{exhibit_num} {att_type}")
    return parts
