"""search_edgar tool — full-text search across all EDGAR filings via SEC EFTS API."""

from typing import Optional

import httpx
from mcp.server.fastmcp import FastMCP

from ..types import FormType


EFTS_URL = "https://efts.sec.gov/LATEST/search-index"


def register(mcp: FastMCP):
    @mcp.tool(
        name="search_edgar",
        description=(
            "Full-text search across ALL EDGAR filings using SEC's EFTS (EDGAR Full-Text Search) API.\n\n"
            "The discovery tool. Searches the entire EDGAR corpus without specifying companies or "
            "accession numbers. Returns matching filings with excerpts.\n\n"
            "Query syntax: quoted phrases, AND/OR/NOT, wildcards — SEC EFTS operators.\n\n"
            "Use case: discovery → then pipe accession numbers into read_document or search_filings.\n\n"
            "Examples:\n"
            '- search_edgar(query=\'"material weakness" AND "internal controls"\')\n'
            '- search_edgar(query="semiconductor supply chain risk", forms=["10-K"], start_date="2024-01-01")\n'
            '- search_edgar(query="artificial intelligence", entity="Apple", forms=["10-K"])\n'
        ),
    )
    async def search_edgar(
        query: str,
        entity: Optional[str] = None,
        forms: Optional[list[FormType]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Full-text search across ALL EDGAR filings using SEC's EFTS API.

        Args:
            query: Full-text search query (supports boolean operators)
            entity: Company name or CIK to scope the search
            forms: Filter by form type
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD
            limit: Max results (default: 10, max: 50)
        """
        import os
        limit = min(limit, 50)

        params = {
            "q": query,
            "from": 0,
            "size": limit,
        }

        if entity:
            params["entity"] = entity
        if forms:
            params["forms"] = ",".join(forms)
        if start_date:
            params["startdt"] = start_date
        if end_date:
            params["enddt"] = end_date

        identity = os.environ.get("EDGAR_IDENTITY", "edgarmcp user@example.com")
        headers = {
            "User-Agent": identity,
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(EFTS_URL, params=params, headers=headers, timeout=30)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            return f"EFTS API error: {e.response.status_code} — {e.response.text[:200]}"
        except Exception as e:
            return f"EFTS search failed: {e}"

        total_hits = data.get("hits", {}).get("total", {}).get("value", 0)
        hits = data.get("hits", {}).get("hits", [])[:limit]

        if not hits:
            return f'# EDGAR Search: "{query}"\n\n0 results found.'

        # Format results table
        lines = [f'# EDGAR Search: "{query}"\n']
        lines.append(f"{total_hits} total hits. Showing top {len(hits)}.\n")
        lines.append("| # | Company | Form | Date | Accession | Description |")
        lines.append("|---|---------|------|------|-----------|-------------|")

        excerpts = []
        for i, hit in enumerate(hits, 1):
            source = hit.get("_source", {})
            company = source.get("display_names", [""])[0] if source.get("display_names") else source.get("entity_name", "")
            form = source.get("form_type", "")
            filed = source.get("file_date", "")
            accession = source.get("file_num", "")
            # Try to get accession number
            acc_raw = hit.get("_id", "")
            description = source.get("display_description", "") or source.get("file_description", form)

            lines.append(f"| {i} | {company} | {form} | {filed} | {acc_raw} | {description} |")

            # Collect highlights/excerpts
            highlight = hit.get("highlight", {})
            snippets = highlight.get("full_submission", []) or highlight.get("content", [])
            if snippets:
                # Clean HTML tags from highlights
                import re
                cleaned = re.sub(r'<[^>]+>', '', snippets[0])
                excerpts.append((i, company, form, cleaned))

        # Add excerpts
        if excerpts:
            lines.append("\n**Excerpts:**\n")
            for num, company, form, text in excerpts:
                lines.append(f"**{num}. {company} ({form})**")
                lines.append(f"> {text[:300]}")
                lines.append("")

        lines.append('To read: read_document(accession_number="...")')
        return "\n".join(lines)
