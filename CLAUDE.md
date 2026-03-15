# edgarmcp

Standalone, zero-infrastructure SEC EDGAR MCP server. 5 tools: `get_filings`, `read_document`, `search_filings`, `view_financials`, `search_edgar`.

## Setup

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e "."
export EDGAR_IDENTITY="Your Name your@email.com"
```

**Package manager: `uv`** — always use `uv pip install`, never bare `pip`.

## Running

```bash
# stdio (default, for Claude Code)
python -m edgarmcp

# streamable HTTP
python -m edgarmcp --http --port 8000

# Add to Claude Code
claude mcp add edgarmcp -- python -m edgarmcp
```

## Architecture

- `src/edgarmcp/server.py` — FastMCP setup, imports + registers all tools
- `src/edgarmcp/types.py` — FormType, AttachmentType, SectionType, StatementType, ReportType
- `src/edgarmcp/company.py` — Ticker/CIK/name → edgartools Company
- `src/edgarmcp/cache.py` — LRU cache for parsed filings + accession→filing map
- `src/edgarmcp/filing_loader.py` — Load HTML → sec2md parse → sections/notes/attachments
- `src/edgarmcp/sections.py` — Section type mappings + extraction via sec2md
- `src/edgarmcp/attachment_types.py` — Exhibit classification (EX-99→press_release, etc.)
- `src/edgarmcp/tools/` — One file per tool
- `src/edgarmcp/financials/` — Statement merger (Q4 inference, YTD, splits, TTM) + formatter

## Key design decisions

1. All tools return `str` (markdown) — no structured_content
2. Standalone — copies logic from intellifin, does not import it
3. `accession_to_filing` mapping lets `read_document` resolve filings without re-querying
4. LRU cache (~20 filings) — repeat reads are instant
5. BM25 via `rank-bm25` — no GPU/API needed
