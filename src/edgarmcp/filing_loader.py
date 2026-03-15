"""Load filing HTML, parse via sec2md, extract sections/notes/attachments."""

import logging
import re
from typing import Optional

from sec2md import Parser, merge_text_blocks

from .attachment_types import SKIP_EXHIBITS, infer_attachment_type
from .cache import AttachmentMeta, NoteMeta, ParsedFiling, cache
from .citations import registry as citation_registry
from .company import CompanyInfo, resolve_company
from .html_server import cache_annotated_html
from .sections import extract_sections

logger = logging.getLogger(__name__)


def load_filing(
    accession_number: str,
    filing=None,
    company_info: Optional[CompanyInfo] = None,
) -> ParsedFiling | str:
    """Load and parse a filing, returning cached result if available.

    Returns ParsedFiling on success, or error message string on failure.
    """
    # Check cache
    cached = cache.get(accession_number)
    if cached is not None:
        return cached

    # Resolve EntityFiling
    if filing is None:
        filing = cache.get_filing_ref(accession_number)
    if filing is None:
        # Try to look up via edgartools
        try:
            from edgar import find
            filing = find(accession_number)
            if filing is None:
                return f"Filing not found: {accession_number}"
        except Exception as e:
            return f"Failed to resolve filing {accession_number}: {e}"

    # Load HTML
    html = _load_html(filing)
    if not html:
        return f"Could not load HTML for filing {accession_number}"

    # Parse pages
    try:
        parser = Parser(html)
        pages = parser.get_pages(include_elements=True)
    except Exception as e:
        return f"Failed to parse filing {accession_number}: {e}"

    if not pages:
        return f"No pages parsed from filing {accession_number}"

    # Cache annotated HTML for citation highlighting
    if citation_registry.enabled:
        try:
            cache_annotated_html(accession_number, parser.html())
        except Exception as e:
            logger.warning(f"Failed to cache annotated HTML for {accession_number}: {e}")

    # Get filing metadata
    form = getattr(filing, 'form', '') or ''
    filing_date = str(getattr(filing, 'filing_date', '') or '')
    report_date = str(getattr(filing, 'report_date', '') or '') if getattr(filing, 'report_date', None) else None

    # Resolve company info if not provided
    if company_info is None:
        cik = str(getattr(filing, 'cik', '') or '')
        company_name = getattr(filing, 'company', '') or ''
        symbol = cik  # fallback
        # Try to get ticker from filing
        if hasattr(filing, 'ticker') and filing.ticker:
            symbol = filing.ticker
        company_info = CompanyInfo(symbol=symbol, name=company_name, cik=cik, edgar_company=None)

    # Extract sections
    sections = extract_sections(pages, form)

    # Extract notes (10-K/10-Q/20-F only)
    notes = []
    note_blocks = []
    form_normalized = form.replace("/A", "")
    if form_normalized in ("10-K", "10-Q", "20-F"):
        try:
            blocks = merge_text_blocks(pages)
            if blocks:
                note_blocks = blocks
                for i, block in enumerate(blocks, 1):
                    title = getattr(block, 'title', '') or f"Note {i}"
                    start_page = getattr(block, 'start_page', 1)
                    end_page = getattr(block, 'end_page', start_page)
                    notes.append(NoteMeta(
                        name=f"note_{i}",
                        title=title,
                        start_page=start_page,
                        end_page=end_page,
                    ))
        except Exception as e:
            logger.warning(f"Note extraction failed for {accession_number}: {e}")

    # List attachment metadata
    attachments = _list_attachments(filing)

    # Get SGML for lazy attachment loading
    sgml = None
    try:
        sgml = filing.obj()
    except Exception:
        pass

    parsed = ParsedFiling(
        accession_number=accession_number,
        form=form,
        filing_date=filing_date,
        report_date=report_date,
        company_symbol=company_info.symbol,
        company_name=company_info.name,
        cik=company_info.cik,
        pages=pages,
        sections=sections,
        notes=notes,
        note_blocks=note_blocks,
        attachments=attachments,
        sgml=sgml,
        filing=filing,
    )
    cache.put(parsed)
    return parsed


def load_attachment_pages(parsed: ParsedFiling, exhibit_number: str) -> list | str:
    """Load and parse attachment HTML on demand. Returns pages or error string."""
    filing = parsed.filing
    if filing is None:
        return f"No filing reference available for {parsed.accession_number}"

    try:
        documents = filing.attachments.documents if hasattr(filing, 'attachments') else []
    except Exception:
        documents = []

    target_doc_type = f"EX-{exhibit_number}"
    for doc in documents:
        if not doc.document_type:
            continue
        if doc.document_type == target_doc_type:
            try:
                html = doc.content
                if not html:
                    return f"Exhibit {exhibit_number} has no content"
                att_parser = Parser(html)
                pages = att_parser.get_pages(include_elements=True)
                if not pages:
                    return f"No pages parsed from exhibit {exhibit_number}"
                return pages
            except Exception as e:
                return f"Failed to parse exhibit {exhibit_number}: {e}"

    return f"Exhibit {exhibit_number} not found in filing {parsed.accession_number}"


def get_section_pages(parsed: ParsedFiling, section_type: str) -> list | str:
    """Get pages for a specific section. Returns pages or error string."""
    for section in parsed.sections:
        if section.type == section_type:
            return section.pages
    return f"Section '{section_type}' not found in filing {parsed.accession_number}"


def get_note_pages(parsed: ParsedFiling, note_name: str) -> tuple[list, str] | str:
    """Get pages for a specific note. Returns (pages, title) or error string."""
    for note in parsed.notes:
        if note.name == note_name:
            # Return pages from the main filing within the note's page range
            note_pages = [
                p for p in parsed.pages
                if note.start_page <= p.number <= note.end_page
            ]
            if note_pages:
                return note_pages, note.title
            return f"No pages found for {note_name} (pages {note.start_page}-{note.end_page})"
    return f"Note '{note_name}' not found. Available: {', '.join(n.name for n in parsed.notes)}"


def _load_html(filing) -> Optional[str]:
    """Load filing HTML using the same strategy as intellifin."""
    try:
        html = None
        try:
            sgml = filing.obj()
            if sgml and hasattr(sgml, 'html'):
                html = sgml.html()
        except Exception:
            pass
        if not html:
            try:
                html = filing.html()
            except Exception:
                pass
        return html
    except Exception as e:
        logger.warning(f"HTML load failed: {e}")
        return None


def _list_attachments(filing) -> list[AttachmentMeta]:
    """List attachment metadata from filing without loading content."""
    attachments = []
    try:
        documents = filing.attachments.documents if hasattr(filing, 'attachments') else []
    except Exception:
        return attachments

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
        attachment_type = infer_attachment_type(exhibit_num, description)

        attachments.append(AttachmentMeta(
            exhibit_number=exhibit_num,
            document_type=doc.document_type,
            description=description,
            attachment_type=attachment_type,
            filename=doc.document or f"ex-{exhibit_num}",
        ))
    return attachments
