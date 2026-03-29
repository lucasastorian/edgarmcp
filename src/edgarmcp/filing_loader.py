"""Load filing HTML, parse via sec2md, extract sections/notes/attachments."""

import asyncio
import dataclasses
import gzip
import json
import logging

from sec2md import Parser, merge_text_blocks

from .attachment_types import SKIP_EXHIBITS, infer_attachment_type
from .cache import AttachmentMeta, NoteMeta, ParsedFiling, cache
from .citations import registry as citation_registry
from .company import CompanyInfo
from .html_server import cache_annotated_html
from .sections import SectionInfo, extract_sections
from .storage import backend as l2_backend
from .types import EdgarError

logger = logging.getLogger(__name__)


def _get_accession(filing) -> str:
    """Extract accession number from an edgartools filing object."""
    try:
        return filing.accession_number
    except AttributeError:
        return str(filing.accession_no)


def load_filing(
    accession_number: str,
    filing=None,
    company_info: CompanyInfo | None = None,
) -> ParsedFiling:
    """Load and parse a filing. Raises EdgarError on failure."""
    cached = cache.get(accession_number)
    if cached is not None:
        return cached

    if filing is None:
        filing = cache.get_filing_ref(accession_number)
    if filing is None:
        try:
            from edgar import find
            filing = find(accession_number)
            if filing is None:
                raise EdgarError(f"Filing not found: {accession_number}")
        except EdgarError:
            raise
        except Exception as e:
            raise EdgarError(f"Failed to resolve filing {accession_number}: {e}") from e

    html = _load_html(filing)
    if not html:
        raise EdgarError(f"Could not load HTML for filing {accession_number}")

    try:
        parser = Parser(html)
        pages = parser.get_pages(include_elements=True)
    except Exception as e:
        raise EdgarError(f"Failed to parse filing {accession_number}: {e}") from e

    if not pages:
        raise EdgarError(f"No pages parsed from filing {accession_number}")

    if citation_registry.enabled:
        try:
            cache_annotated_html(accession_number, parser.html())
        except Exception as e:
            logger.warning(f"Failed to cache annotated HTML for {accession_number}: {e}")

    form = filing.form or ""
    filing_date = str(filing.filing_date or "")
    report_date = str(filing.report_date) if filing.report_date else None

    if company_info is None:
        cik = str(filing.cik or "")
        company_name = filing.company or ""
        symbol = filing.ticker if hasattr(filing, "ticker") and filing.ticker else cik
        company_info = CompanyInfo(symbol=symbol, name=company_name, cik=cik, edgar_company=None)

    sections = extract_sections(pages, form)

    notes = []
    note_blocks = []
    form_normalized = form.replace("/A", "")
    if form_normalized in ("10-K", "10-Q", "20-F"):
        try:
            blocks = merge_text_blocks(pages)
            if blocks:
                note_blocks = blocks
                for i, block in enumerate(blocks, 1):
                    notes.append(NoteMeta(
                        name=f"note_{i}",
                        title=block.title or f"Note {i}",
                        start_page=block.start_page,
                        end_page=getattr(block, "end_page", block.start_page),
                    ))
        except Exception as e:
            logger.warning(f"Note extraction failed for {accession_number}: {e}")

    attachments = _list_attachments(filing)

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


async def load_filing_cached(
    accession_number: str,
    filing=None,
    company_info: CompanyInfo | None = None,
) -> ParsedFiling:
    """Async wrapper with L2 persistent cache.

    Check order: L1 (in-memory LRU) -> L2 (filesystem/S3) -> SEC EDGAR fetch+parse.
    Raises EdgarError on failure.
    """
    cached = cache.get(accession_number)
    if cached is not None:
        return cached

    parsed = await _load_from_l2(accession_number)
    if parsed is not None:
        cache.put(parsed)
        return parsed

    parsed = load_filing(accession_number, filing, company_info)

    try:
        asyncio.create_task(_save_to_l2(parsed))
    except RuntimeError:
        pass

    return parsed


async def _load_from_l2(accession_number: str) -> ParsedFiling | None:
    key = f"parsed/{accession_number}.json.gz"
    data = await l2_backend.get(key)
    if data is None:
        return None

    try:
        raw = json.loads(gzip.decompress(data))
        parsed = _deserialize_parsed(raw)

        filing_ref = cache.get_filing_ref(accession_number)
        if filing_ref:
            parsed.filing = filing_ref
            try:
                parsed.sgml = filing_ref.obj()
            except Exception:
                pass

        return parsed
    except Exception as e:
        logger.warning(f"L2 cache deserialization failed for {accession_number}: {e}")
        return None


async def _save_to_l2(parsed: ParsedFiling) -> None:
    try:
        data = _serialize_parsed(parsed)
        compressed = gzip.compress(json.dumps(data).encode())
        key = f"parsed/{parsed.accession_number}.json.gz"
        await l2_backend.put(key, compressed)
    except Exception as e:
        logger.warning(f"L2 cache write failed for {parsed.accession_number}: {e}")


def _serialize_parsed(parsed: ParsedFiling) -> dict:
    return {
        "accession_number": parsed.accession_number,
        "form": parsed.form,
        "filing_date": parsed.filing_date,
        "report_date": parsed.report_date,
        "company_symbol": parsed.company_symbol,
        "company_name": parsed.company_name,
        "cik": parsed.cik,
        "pages": [p.model_dump() for p in parsed.pages],
        "sections": [
            {"type": s.type, "label": s.label, "start_page": s.start_page, "end_page": s.end_page}
            for s in parsed.sections
        ],
        "notes": [dataclasses.asdict(n) for n in parsed.notes],
        "note_blocks": [b.model_dump() for b in parsed.note_blocks],
        "attachments": [dataclasses.asdict(a) for a in parsed.attachments],
    }


def _deserialize_parsed(data: dict) -> ParsedFiling:
    from sec2md import Page, TextBlock

    pages = [Page.model_validate(d) for d in data["pages"]]

    sections = []
    for sd in data["sections"]:
        sec_pages = [p for p in pages if sd["start_page"] <= p.number <= sd["end_page"]]
        sections.append(SectionInfo(
            type=sd["type"],
            label=sd["label"],
            start_page=sd["start_page"],
            end_page=sd["end_page"],
            pages=sec_pages,
        ))

    return ParsedFiling(
        accession_number=data["accession_number"],
        form=data["form"],
        filing_date=data["filing_date"],
        report_date=data.get("report_date"),
        company_symbol=data["company_symbol"],
        company_name=data["company_name"],
        cik=data["cik"],
        pages=pages,
        sections=sections,
        notes=[NoteMeta(**n) for n in data["notes"]],
        note_blocks=[TextBlock.model_validate(b) for b in data["note_blocks"]],
        attachments=[AttachmentMeta(**a) for a in data["attachments"]],
        sgml=None,
        filing=None,
    )


def load_attachment_pages(parsed: ParsedFiling, exhibit_number: str) -> list:
    """Load and parse attachment HTML on demand. Raises EdgarError on failure."""
    if parsed.filing is None:
        raise EdgarError(f"No filing reference available for {parsed.accession_number}")

    try:
        documents = parsed.filing.attachments.documents
    except Exception:
        documents = []

    target_doc_type = f"EX-{exhibit_number}"
    for doc in documents:
        if not doc.document_type or doc.document_type != target_doc_type:
            continue
        try:
            html = doc.content
            if not html:
                raise EdgarError(f"Exhibit {exhibit_number} has no content")
            att_parser = Parser(html)
            pages = att_parser.get_pages(include_elements=True)
            if not pages:
                raise EdgarError(f"No pages parsed from exhibit {exhibit_number}")
            if citation_registry.enabled:
                try:
                    cache_key = f"{parsed.accession_number}_ex_{exhibit_number}"
                    cache_annotated_html(cache_key, att_parser.html())
                except Exception:
                    pass
            return pages
        except EdgarError:
            raise
        except Exception as e:
            raise EdgarError(f"Failed to parse exhibit {exhibit_number}: {e}") from e

    raise EdgarError(f"Exhibit {exhibit_number} not found in filing {parsed.accession_number}")


def get_section_pages(parsed: ParsedFiling, section_type: str) -> list:
    """Get pages for a specific section. Raises EdgarError if not found."""
    for section in parsed.sections:
        if section.type == section_type:
            return section.pages
    raise EdgarError(f"Section '{section_type}' not found in filing {parsed.accession_number}")


def get_note_pages(parsed: ParsedFiling, note_name: str) -> tuple[list, str]:
    """Get pages for a specific note. Returns (pages, title). Raises EdgarError if not found."""
    for note in parsed.notes:
        if note.name == note_name:
            note_pages = [
                p for p in parsed.pages
                if note.start_page <= p.number <= note.end_page
            ]
            if note_pages:
                return note_pages, note.title
            raise EdgarError(f"No pages found for {note_name} (pages {note.start_page}-{note.end_page})")
    raise EdgarError(f"Note '{note_name}' not found. Available: {', '.join(n.name for n in parsed.notes)}")


def _load_html(filing) -> str | None:
    try:
        sgml = filing.obj()
        if sgml and hasattr(sgml, "html"):
            html = sgml.html()
            if html:
                return html
    except Exception:
        pass
    try:
        return filing.html()
    except Exception as e:
        logger.warning(f"HTML load failed: {e}")
        return None


def _list_attachments(filing) -> list[AttachmentMeta]:
    attachments = []
    try:
        documents = filing.attachments.documents
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
