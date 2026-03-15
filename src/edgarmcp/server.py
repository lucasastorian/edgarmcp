"""FastMCP server setup and tool registration."""

from mcp.server.fastmcp import FastMCP

from .tools import get_filings, read_document, search_filings, view_financials, search_edgar

mcp = FastMCP(name="edgarmcp")

get_filings.register(mcp)
read_document.register(mcp)
search_filings.register(mcp)
view_financials.register(mcp)
search_edgar.register(mcp)


GUIDE = """\
# edgarmcp — SEC EDGAR MCP Server Guide

## Quick Reference

5 tools, no database required. All data comes directly from SEC EDGAR.

## Workflows

### 1. Financial Analysis
```
view_financials(symbol, statement_type, report_type)
```
- statement_type: income_statement, balance_sheet, cash_flow
- report_type: annual, quarterly, ttm
- Handles Q4 inference, YTD normalization, stock splits, TTM computation
- Returns merged multi-period table + notes index from the latest 10-K
- Follow up with read_document(note_name="note_N") for accounting details

### 2. Filing Discovery → Reading
```
get_filings(company) → read_document(accession_number)
```
- Start with get_filings to list filings, attachments, or notes
- Then read_document to read the filing, a section, an exhibit, or a note
- Sections: risk_factors, mda, business, financial, controls, directors, etc.
- Exhibits: "99.1" for press releases, "10.1" for contracts, "3.1" for charters
- Notes: "note_2" for revenue recognition, etc. (index shown in get_filings with include_notes=true)

### 3. Keyword Search
```
search_filings(query, company, forms)
```
- BM25 search across parsed filing content
- Scope with: sections=["risk_factors"], attachment_types=["press_release"], xbrl_tags=["us-gaap:Revenue"]
- Or search by accession_numbers directly

### 4. Cross-EDGAR Discovery
```
search_edgar(query)
```
- Full-text search across the entire EDGAR corpus (SEC EFTS API)
- No company required — find any filing mentioning a topic
- Pipe accession numbers from results into read_document or search_filings

## Tips

### Foreign Filers (20-F / 6-K)
- 20-F sections are less standardized than 10-K. Section filtering (e.g. risk_factors) \
may not work for 20-F filers. search_filings automatically falls back to searching the \
full document for 20-F/6-K filings.
- Financial statements work normally — XBRL is standardized regardless of filing type.
- 20-F filers report in local currency (e.g. TSM in NT$, ASML in EUR).

### Attachment Types
- press_release, investor_presentation, cfo_commentary, shareholder_letter — from EX-99.x
- material_contract (EX-10.x), merger_agreement (EX-2.1), debt_instrument (EX-4.x)
- charter (EX-3.x), bylaws (EX-3.2), certificate_of_designations (EX-3.1)
- When filtering by press_release, exhibits with ambiguous descriptions are included \
(since most EX-99.x are press releases).

### Performance
- First call for a company downloads filing data from SEC (~5-15s). Subsequent calls \
use cached data.
- Multi-filing tools (view_financials, search_filings) download all filings in parallel.
- Parsed filings are cached in an LRU cache (20 slots). Re-reads, section switches, \
and pagination are instant.

### Pagination
- read_document returns max 20 pages per request.
- Use start_page/end_page to paginate: read_document(accession_number="...", start_page=21, end_page=40)

### Financial Statement Notes
- The notes index from the most recent 10-K is appended to every view_financials response.
- Use read_document(accession_number, note_name="note_N") to read a specific note.
- Notes contain critical accounting policies, revenue recognition details, debt terms, \
segment breakdowns, etc.

### Section Extraction
- Section filtering (e.g. risk_factors, mda) only works reliably for 10-K and 10-Q filings.
- For all other filing types (DEF 14A, 8-K, 20-F, 6-K, S-1, etc.), use search_filings \
to search the full document, or read_document without a section parameter.

### Citations
- Search results include citation links (e.g. [1](url), [2](url)) that map to specific \
elements in the original SEC filing HTML.
- When referencing search results in your response, include the citation link so the user \
can click through to view the highlighted source in the original filing.
- Citation links open the filing HTML in a browser and automatically scroll to and highlight \
the relevant table, paragraph, or section in yellow.
- Citations are numbered sequentially across all tool calls in the session.
"""


@mcp.resource(
    "edgarmcp://guide",
    name="edgarmcp_guide",
    title="edgarmcp Usage Guide",
    description="How to use edgarmcp tools effectively — workflows, tips, and gotchas for SEC EDGAR analysis",
    mime_type="text/markdown",
)
def get_guide() -> str:
    return GUIDE
