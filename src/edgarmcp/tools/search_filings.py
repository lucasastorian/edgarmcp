"""search_filings tool — BM25 search across a company's filings."""

from datetime import date, timedelta
from typing import Optional

from edgar._filings import load_sgmls_concurrently
from mcp.server.fastmcp import FastMCP
from rank_bm25 import BM25Okapi
from sec2md import chunk_pages

from ..cache import ParsedFiling, cache
from ..citations import registry as citation_registry
from ..company import CompanyInfo, resolve_company_cached
from ..attachment_types import matches_attachment_type
from ..filing_loader import _get_accession, load_filing_cached, load_attachment_pages, get_section_pages
from ..types import AttachmentType, EdgarError, FormType, SectionType, SEARCHABLE_ATTACHMENT_TYPES


def register(mcp: FastMCP):
    @mcp.tool(
        name="search_filings",
        description=(
            "BM25 keyword search across a company's SEC filings, attachments, and notes.\n\n"
            "Resolves filings internally from filters, loads + parses them, chunks all content, "
            "and ranks by BM25. No need to list filings first.\n\n"
            "Two modes:\n"
            "- By company (requires company + forms): resolves filings, loads, searches\n"
            "- By accession (requires accession_numbers): searches explicit filings directly\n\n"
            "What gets searched:\n"
            "- When attachment_types set: only those attachment types (e.g. just press releases)\n"
            "- When sections set: only those sections (e.g. just risk_factors + mda)\n"
            "- When xbrl_tags set: only chunks containing those XBRL concept tags\n"
            "- Otherwise: main filing pages + notes + high-value attachments\n\n"
            "Examples:\n"
            '- search_filings(query="revenue recognition", company="AAPL", forms=["10-Q"], limit=5)\n'
            '- search_filings(query="AI risk", company="AAPL", forms=["10-K"], sections=["risk_factors"])\n'
            '- search_filings(query="revenue guidance", company="AAPL", forms=["8-K"], attachment_types=["press_release"])\n'
            '- search_filings(query="supply chain", accession_numbers=["0001193125-24-123456"])\n'
            '- search_filings(query="revenue", company="AAPL", forms=["10-K"], xbrl_tags=["us-gaap:Revenue"])\n'
        ),
    )
    async def search_filings(
        query: str,
        company: Optional[str] = None,
        forms: Optional[list[FormType]] = None,
        attachment_types: Optional[list[AttachmentType]] = None,
        sections: Optional[list[SectionType]] = None,
        xbrl_tags: Optional[list[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 5,
        accession_numbers: Optional[list[str]] = None,
        top_k: int = 10,
    ) -> str:
        """BM25 keyword search across a company's SEC filings, attachments, and notes.

        Args:
            query: Search query
            company: Ticker/name/CIK (required with forms)
            forms: Form types to search (required with company)
            attachment_types: Search only these attachment types
            sections: Scope search to specific sections (e.g. ["mda", "risk_factors"])
            xbrl_tags: Filter to chunks containing these XBRL concept tags (e.g. ["us-gaap:Revenue"])
            start_date: YYYY-MM-DD (default: 2 years ago)
            end_date: YYYY-MM-DD (default: today)
            limit: Max filings to load and search (default: 5, max: 100)
            accession_numbers: Explicit filings to search (skips company/form lookup)
            top_k: Results to return (default: 10, max: 50)
        """
        limit = min(limit, 100)
        top_k = min(top_k, 50)

        try:
            if accession_numbers:
                parsed_filings = await _load_by_accession(accession_numbers)
            elif company and forms:
                parsed_filings = await _load_by_company(company, forms, start_date, end_date, limit)
            else:
                return "Error: provide either (company + forms) or accession_numbers."
        except EdgarError as e:
            return str(e)

        if not parsed_filings:
            return "No filings could be loaded for searching."

        all_chunks = []
        for parsed in parsed_filings:
            chunks = _build_chunks(parsed, attachment_types, sections)
            all_chunks.extend(chunks)

        if not all_chunks:
            return "No searchable content found in the loaded filings."

        if xbrl_tags:
            tag_set = set(xbrl_tags)
            filtered = []
            for c in all_chunks:
                chunk_tags = c.get("tags", [])
                if chunk_tags and any(
                    any(xt in ct for xt in tag_set) for ct in chunk_tags
                ):
                    filtered.append(c)
            if not filtered:
                return f"No chunks matched XBRL tags: {', '.join(xbrl_tags)}"
            all_chunks = filtered

        tokenized_corpus = [c["text"].lower().split() for c in all_chunks]
        bm25 = BM25Okapi(tokenized_corpus)
        tokenized_query = query.lower().split()
        scores = bm25.get_scores(tokenized_query)

        ranked = sorted(
            zip(range(len(all_chunks)), scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]

        scope = _describe_scope(company, forms, accession_numbers, attachment_types, sections)
        lines = [f"# Search: \"{query}\" in {scope}\n"]
        lines.append(f"Searched {len(parsed_filings)} filings, {len(all_chunks)} chunks.\n")
        lines.append("## Results\n")

        for rank, (idx, score) in enumerate(ranked, 1):
            if score <= 0:
                break
            chunk = all_chunks[idx]
            header = _format_result_header(chunk)
            text = chunk["text"][:500]
            if len(chunk["text"]) > 500:
                text += "..."

            cid = citation_registry.add(
                accession_number=chunk["accession"],
                element_ids=chunk.get("element_ids", []),
                source_type=chunk["source_type"],
                form=chunk["form"],
                filing_date=chunk["filing_date"],
                company_name=chunk.get("company_name", ""),
                company_symbol=chunk.get("company_symbol", ""),
                section=chunk.get("section"),
                exhibit_number=chunk.get("exhibit_number"),
                note_name=chunk.get("note_name"),
                page=chunk.get("page"),
            )
            cite_tag = citation_registry.format_tag(cid)

            tags = chunk.get("tags", [])
            tag_str = f"**XBRL:** {', '.join(tags[:5])}" if tags else ""

            lines.append(f"### Result {rank} [{score:.2f}]")
            lines.append(header)
            lines.append("")
            lines.append(text + cite_tag)
            if tag_str:
                lines.append(tag_str)
            lines.append("\n---\n")

        if parsed_filings:
            best = all_chunks[ranked[0][0]] if ranked and ranked[0][1] > 0 else None
            if best:
                acc = best["accession"]
                if best["source_type"] == "note":
                    lines.append(f'To read more: read_document(accession_number="{acc}", note_name="{best["note_name"]}")')
                elif best["source_type"] == "attachment":
                    lines.append(f'To read more: read_document(accession_number="{acc}", exhibit_number="{best["exhibit_number"]}")')
                elif best["source_type"] == "section":
                    lines.append(f'To read more: read_document(accession_number="{acc}", section="{best["section"]}")')
                else:
                    lines.append(f'To read more: read_document(accession_number="{acc}")')

        lines.append(citation_registry.format_instructions())

        return "\n".join(lines)


async def _load_by_company(
    company: str, forms: list[str], start_date: Optional[str], end_date: Optional[str], limit: int
) -> list[ParsedFiling]:
    """Resolve company and load filings with parallel SGML pre-fetch. Raises EdgarError."""
    info = await resolve_company_cached(company)

    if not start_date:
        start_date = (date.today() - timedelta(days=730)).isoformat()
    if not end_date:
        end_date = date.today().isoformat()

    try:
        date_range = f"{start_date}:{end_date}"
        filings = info.edgar_company.get_filings(form=forms, date=date_range)
    except Exception as e:
        raise EdgarError(f"Failed to fetch filings: {e}") from e

    to_load = []
    for f in filings:
        if len(to_load) >= limit:
            break
        accession = _get_accession(f)
        cache.store_filing_ref(accession, f)
        to_load.append((accession, f))

    await load_sgmls_concurrently(
        [f for _, f in to_load],
        max_in_flight=16,
        return_exceptions=True,
    )

    parsed_filings = []
    for accession, f in to_load:
        try:
            parsed = await load_filing_cached(accession, filing=f, company_info=info)
            parsed_filings.append(parsed)
        except EdgarError:
            continue

    return parsed_filings


async def _load_by_accession(accession_numbers: list[str]) -> list[ParsedFiling]:
    to_prefetch = []
    for acc in accession_numbers:
        ref = cache.get_filing_ref(acc)
        if ref and not cache.get(acc):
            to_prefetch.append(ref)

    if to_prefetch:
        await load_sgmls_concurrently(to_prefetch, max_in_flight=16, return_exceptions=True)

    parsed_filings = []
    for acc in accession_numbers:
        try:
            parsed = await load_filing_cached(acc)
            parsed_filings.append(parsed)
        except EdgarError:
            continue
    return parsed_filings


def _chunk_to_dict(c, source_type: str, parsed: ParsedFiling, **extra) -> dict:
    return {
        "text": c.content,
        "tags": list(c.tags) if c.tags else [],
        "element_ids": list(c.element_ids) if c.element_ids else [],
        "source_type": source_type,
        "accession": parsed.accession_number,
        "company_name": parsed.company_name,
        "company_symbol": parsed.company_symbol,
        "form": parsed.form,
        "filing_date": parsed.filing_date,
        "report_date": parsed.report_date,
        "page": c.start_page,
        **extra,
    }


def _build_chunks(
    parsed: ParsedFiling,
    attachment_types: Optional[list[str]],
    section_types: Optional[list[str]],
) -> list[dict]:
    chunks = []
    defaults = {"exhibit_number": None, "attachment_type": None, "section": None, "note_name": None}

    if attachment_types:
        for att in parsed.attachments:
            if not matches_attachment_type(att.attachment_type, attachment_types):
                continue
            try:
                att_pages = load_attachment_pages(parsed, att.exhibit_number)
            except EdgarError:
                continue
            for c in chunk_pages(att_pages, chunk_size=500, chunk_overlap=100):
                chunks.append(_chunk_to_dict(
                    c, "attachment", parsed,
                    exhibit_number=att.exhibit_number,
                    attachment_type=att.attachment_type,
                    section=None, note_name=None,
                ))
    elif section_types:
        if parsed.form.replace("/A", "") not in ("10-K", "10-Q", "8-K", "20-F"):
            for c in chunk_pages(parsed.pages, chunk_size=500, chunk_overlap=100):
                chunks.append(_chunk_to_dict(c, "main", parsed, **defaults))
        else:
            for st in section_types:
                try:
                    sec_pages = get_section_pages(parsed, st)
                except EdgarError:
                    continue
                for c in chunk_pages(sec_pages, chunk_size=500, chunk_overlap=100):
                    chunks.append(_chunk_to_dict(
                        c, "section", parsed,
                        section=st,
                        exhibit_number=None, attachment_type=None, note_name=None,
                    ))
    else:
        for c in chunk_pages(parsed.pages, chunk_size=500, chunk_overlap=100):
            chunks.append(_chunk_to_dict(c, "main", parsed, **defaults))

        for att in parsed.attachments:
            if att.attachment_type not in SEARCHABLE_ATTACHMENT_TYPES:
                continue
            try:
                att_pages = load_attachment_pages(parsed, att.exhibit_number)
            except EdgarError:
                continue
            for c in chunk_pages(att_pages, chunk_size=500, chunk_overlap=100):
                chunks.append(_chunk_to_dict(
                    c, "attachment", parsed,
                    exhibit_number=att.exhibit_number,
                    attachment_type=att.attachment_type,
                    section=None, note_name=None,
                ))

        for note in parsed.notes:
            note_pages = [p for p in parsed.pages if note.start_page <= p.number <= note.end_page]
            if not note_pages:
                continue
            for c in chunk_pages(note_pages, chunk_size=500, chunk_overlap=100):
                chunks.append(_chunk_to_dict(
                    c, "note", parsed,
                    note_name=note.name,
                    exhibit_number=None, attachment_type=None, section=None,
                ))

    return chunks


def _format_result_header(chunk: dict) -> str:
    company = chunk.get("company_name", "")
    symbol = chunk.get("company_symbol", "")
    form = chunk["form"]
    filing_date = chunk["filing_date"]
    report_date = chunk.get("report_date")
    page = chunk.get("page")
    source_type = chunk["source_type"]

    company_str = f"{company} ({symbol})" if symbol and symbol != company else company
    if source_type == "attachment":
        att_type = (chunk.get("attachment_type") or "exhibit").replace("_", " ").title()
        label = f"**{att_type}** (EX-{chunk['exhibit_number']})"
    elif source_type == "section":
        section_label = (chunk.get("section") or "").replace("_", " ").title()
        label = f"**{section_label}**"
    elif source_type == "note":
        label = f"**{chunk.get('note_name', 'Note')}**"
    else:
        label = f"**{form}**"

    line1 = f"{label} | {company_str}"

    parts = [f"Form {form}", f"Filed: {filing_date}"]
    if report_date:
        parts.append(f"Period Ending: {report_date}")
    if page:
        parts.append(f"Page {page}")
    line2 = " | ".join(parts)

    return f"{line1}\n{line2}"


def _describe_scope(company, forms, accession_numbers, attachment_types, sections) -> str:
    parts = []
    if company:
        parts.append(company.upper())
    if forms:
        parts.append(", ".join(forms))
    if accession_numbers:
        parts.append(f"{len(accession_numbers)} filings")
    if attachment_types:
        parts.append(f"[{', '.join(attachment_types)}]")
    if sections:
        parts.append(f"[{', '.join(sections)}]")
    return " ".join(parts) if parts else "filings"
