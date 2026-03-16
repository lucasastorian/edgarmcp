"""read_document tool — read a filing, attachment, section, or note as markdown."""

from typing import Optional

from mcp.server.fastmcp import FastMCP

from ..cache import ParsedFiling, cache
from ..citations import registry as citation_registry
from ..filing_loader import load_filing, load_attachment_pages, get_section_pages, get_note_pages
from ..types import SectionType

MAX_PAGES_PER_REQUEST = 20


def _render_page_content(page, parsed: ParsedFiling, source_type: str = "main", **cite_extra) -> str:
    """Render page content with serial XML citation tags per element.

    If citations are enabled and the page has elements, each element gets
    a <N> tag appended. Otherwise, falls back to page.content.
    """
    if not citation_registry.enabled or not hasattr(page, 'elements') or not page.elements:
        return page.content or ""

    parts = []
    for element in page.elements:
        eid = getattr(element, 'id', None)
        content = element.content or ""
        if not content.strip():
            continue
        if eid:
            cid = citation_registry.add(
                accession_number=parsed.accession_number,
                element_ids=[eid],
                source_type=source_type,
                form=parsed.form,
                filing_date=parsed.filing_date,
                company_name=parsed.company_name,
                company_symbol=parsed.company_symbol,
                page=page.number,
                **cite_extra,
            )
            parts.append(content + citation_registry.format_tag(cid))
        else:
            parts.append(content)
    return "\n\n".join(parts)


def _filing_metadata_line(parsed: ParsedFiling) -> str:
    """Build a metadata line: Form 10-K | Filed: 2025-10-31 | Period Ending: 2025-09-27 | Accession: ..."""
    parts = [f"Form {parsed.form}", f"Filed: {parsed.filing_date}"]
    if parsed.report_date:
        parts.append(f"Period Ending: {parsed.report_date}")
    parts.append(f"Accession: {parsed.accession_number}")
    return " | ".join(parts)


def register(mcp: FastMCP):
    @mcp.tool(
        name="read_document",
        description=(
            "Read a filing, attachment, section, or note as structured markdown.\n\n"
            "Unified reader — one tool for main filings, sections, press releases, exhibits, notes. "
            "Route by parameter:\n"
            "- No optional params → read main filing (first read includes sections/notes/attachments navigation)\n"
            "- section → read just that section (e.g. risk_factors, mda, business, financial)\n"
            "- exhibit_number → read that attachment (e.g. 99.1 for press releases, 10.1 for contracts)\n"
            "- note_name → read that specific note (e.g. note_2 for Revenue Recognition)\n\n"
            "Max 20 pages per request. Use start_page/end_page to paginate larger documents.\n\n"
            "Section types: business, risk_factors, properties, legal_proceedings, market, mda, "
            "market_risk, financial, controls, directors, executive_compensation, security_ownership, "
            "relationships, principal_accountant, exhibits, other_information, unregistered_sales, cybersecurity\n\n"
            "Caching: parsed filings are cached in LRU. Re-reads, page-throughs, and switching between "
            "main filing / attachments / notes are instant.\n\n"
            "Examples:\n"
            '- read_document(accession_number="0000320193-24-000081") — read filing with nav header\n'
            '- read_document(accession_number="...", section="risk_factors") — just risk factors\n'
            '- read_document(accession_number="...", exhibit_number="99.1") — press release\n'
            '- read_document(accession_number="...", note_name="note_2") — revenue recognition note\n'
            '- read_document(accession_number="...", start_page=21, end_page=40) — pages 21-40\n'
        ),
    )
    async def read_document(
        accession_number: str,
        section: Optional[SectionType] = None,
        exhibit_number: Optional[str] = None,
        note_name: Optional[str] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None,
    ) -> str:
        """Read a filing, attachment, section, or note as structured markdown.

        Args:
            accession_number: Filing accession number
            section: Read a specific section (e.g. "risk_factors", "mda")
            exhibit_number: Exhibit to read (e.g. "99.1", "10.1")
            note_name: Note to read (e.g. "note_2")
            start_page: First page to return (default: 1)
            end_page: Last page to return (default: start_page + 19)
        """
        # Validate mutual exclusivity
        params_set = sum(1 for p in [section, exhibit_number, note_name] if p is not None)
        if params_set > 1:
            return "Error: section, exhibit_number, and note_name are mutually exclusive. Provide at most one."

        # Pre-fetch SGML async if not already parsed
        if not cache.get(accession_number):
            filing_ref = cache.get_filing_ref(accession_number)
            if filing_ref:
                try:
                    await filing_ref.sgml_async()
                except Exception:
                    pass

        # Load/parse the filing (fast — SGML already cached)
        parsed = load_filing(accession_number)
        if isinstance(parsed, str):
            return parsed

        # Route to appropriate handler
        if exhibit_number is not None:
            return _read_attachment(parsed, exhibit_number, start_page, end_page)
        elif section is not None:
            return _read_section(parsed, section, start_page, end_page)
        elif note_name is not None:
            return _read_note(parsed, note_name, start_page, end_page)
        else:
            return _read_main_filing(parsed, start_page, end_page)


def _read_main_filing(
    parsed: ParsedFiling, start_page: Optional[int], end_page: Optional[int]
) -> str:
    """Read the main filing with navigation header on first read."""
    pages = parsed.pages
    total = len(pages)

    # Pagination
    start = start_page or 1
    end = end_page or min(start + MAX_PAGES_PER_REQUEST - 1, total)
    end = min(end, start + MAX_PAGES_PER_REQUEST - 1, total)

    lines = []

    # Navigation header on first read (or when starting from page 1)
    if not parsed.navigated or start == 1:
        symbol = parsed.company_symbol
        company_str = f"{parsed.company_name} ({symbol})" if symbol and symbol != parsed.company_name else parsed.company_name
        lines.append(f"# {company_str}")
        lines.append(f"{_filing_metadata_line(parsed)} | {total} pages\n")

        # Sections table
        if parsed.sections:
            lines.append("## Sections")
            lines.append("| Section | Label | Pages |")
            lines.append("|---------|-------|-------|")
            for s in parsed.sections:
                lines.append(f"| {s.type} | {s.label} | {s.start_page}-{s.end_page} |")
            lines.append("")

        # Notes table
        if parsed.notes:
            lines.append("## Notes to Financial Statements")
            lines.append("| Note | Title | Pages |")
            lines.append("|------|-------|-------|")
            for n in parsed.notes:
                lines.append(f"| {n.name} | {n.title} | {n.start_page}-{n.end_page} |")
            lines.append("")

        # Attachments table
        if parsed.attachments:
            lines.append("## Attachments")
            lines.append("| Exhibit | Type | Description |")
            lines.append("|---------|------|-------------|")
            for a in parsed.attachments:
                lines.append(f"| {a.exhibit_number} | {a.attachment_type} | {a.description} |")
            lines.append("")

        lines.append("---\n")
        parsed.navigated = True

    # Render pages
    selected = [p for p in pages if start <= p.number <= end]
    for page in selected:
        lines.append(f"**Page {page.number} of {total}**\n")
        content = _render_page_content(page, parsed, source_type="main")
        if content:
            lines.append(content)
        lines.append("")

    lines.append(citation_registry.format_instructions())
    lines.append(f"(pages {start}-{end} of {total})")
    return "\n".join(lines)


def _read_section(
    parsed: ParsedFiling, section_type: str, start_page: Optional[int], end_page: Optional[int]
) -> str:
    """Read a specific section."""
    # Section extraction requires a supported form type
    form_normalized = parsed.form.replace("/A", "")
    if form_normalized not in ("10-K", "10-Q", "8-K", "20-F"):
        return (
            f"Section extraction is only supported for 10-K, 10-Q, 8-K, and 20-F filings. "
            f"This filing is a {parsed.form}. Use read_document without a section parameter "
            f"to read the full filing, or use search_filings to search its content."
        )

    result = get_section_pages(parsed, section_type)
    if isinstance(result, str):
        return result

    pages = result
    total = len(pages)

    # Find section info for label
    label = section_type
    for s in parsed.sections:
        if s.type == section_type:
            label = s.label
            break

    # Pagination (relative to section pages)
    start = start_page or 1
    end = end_page or min(start + MAX_PAGES_PER_REQUEST - 1, total)
    end = min(end, start + MAX_PAGES_PER_REQUEST - 1, total)

    symbol = parsed.company_symbol
    company_str = f"{parsed.company_name} ({symbol})" if symbol and symbol != parsed.company_name else parsed.company_name
    lines = [
        f"# {company_str}",
        f"## {label}",
        f"{_filing_metadata_line(parsed)} | {total} pages\n",
    ]

    # Select pages by position within section (1-indexed)
    for i, page in enumerate(pages, 1):
        if start <= i <= end:
            lines.append(f"**Page {i} of {total}**\n")
            content = _render_page_content(page, parsed, source_type="section", section=section_type)
            if content:
                lines.append(content)
            lines.append("")

    lines.append(citation_registry.format_instructions())
    lines.append(f"(pages {start}-{end} of {total})")
    return "\n".join(lines)


def _read_attachment(
    parsed: ParsedFiling, exhibit_number: str, start_page: Optional[int], end_page: Optional[int]
) -> str:
    """Read an attachment/exhibit."""
    result = load_attachment_pages(parsed, exhibit_number)
    if isinstance(result, str):
        return result

    pages = result
    total = len(pages)

    # Find attachment info
    att_type = "exhibit"
    description = ""
    for a in parsed.attachments:
        if a.exhibit_number == exhibit_number:
            att_type = a.attachment_type
            description = a.description
            break

    # Pagination
    start = start_page or 1
    end = end_page or min(start + MAX_PAGES_PER_REQUEST - 1, total)
    end = min(end, start + MAX_PAGES_PER_REQUEST - 1, total)

    symbol = parsed.company_symbol
    company_str = f"{parsed.company_name} ({symbol})" if symbol and symbol != parsed.company_name else parsed.company_name
    att_type_display = att_type.replace("_", " ").title()
    desc_part = f": {description}" if description else ""
    lines = [
        f"# {company_str}",
        f"## {att_type_display} (EX-{exhibit_number}){desc_part}",
        f"{_filing_metadata_line(parsed)} | {total} pages\n",
    ]

    for i, page in enumerate(pages, 1):
        if start <= i <= end:
            lines.append(f"**Page {i} of {total}**\n")
            content = _render_page_content(page, parsed, source_type="attachment", exhibit_number=exhibit_number)
            if content:
                lines.append(content)
            lines.append("")

    lines.append(citation_registry.format_instructions())
    lines.append(f"(pages {start}-{end} of {total})")
    return "\n".join(lines)


def _read_note(
    parsed: ParsedFiling, note_name: str, start_page: Optional[int], end_page: Optional[int]
) -> str:
    """Read a specific note to financial statements."""
    result = get_note_pages(parsed, note_name)
    if isinstance(result, str):
        return result

    pages, title = result
    total = len(pages)

    # Pagination
    start = start_page or 1
    end = end_page or min(start + MAX_PAGES_PER_REQUEST - 1, total)
    end = min(end, start + MAX_PAGES_PER_REQUEST - 1, total)

    symbol = parsed.company_symbol
    company_str = f"{parsed.company_name} ({symbol})" if symbol and symbol != parsed.company_name else parsed.company_name
    lines = [
        f"# {company_str}",
        f"## Note: {title}",
        f"{_filing_metadata_line(parsed)} | {total} pages\n",
    ]

    for i, page in enumerate(pages, 1):
        if start <= i <= end:
            lines.append(f"**Page {i} of {total}**\n")
            content = _render_page_content(page, parsed, source_type="note", note_name=note_name)
            if content:
                lines.append(content)
            lines.append("")

    lines.append(citation_registry.format_instructions())
    lines.append(f"(pages {start}-{end} of {total})")
    return "\n".join(lines)
