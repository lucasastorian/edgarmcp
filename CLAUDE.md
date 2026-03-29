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

# streamable HTTP (localhost)
python -m edgarmcp --http --port 8000

# public HTTP (auto-generates API key)
python -m edgarmcp --http --host 0.0.0.0 --port 8000

# Add to Claude Code
claude mcp add edgarmcp -- python -m edgarmcp
```

## Architecture

- `src/edgarmcp/server.py` — FastMCP setup, imports + registers all tools
- `src/edgarmcp/types.py` — FormType, AttachmentType, SectionType, StatementType, ReportType
- `src/edgarmcp/company.py` — Ticker/CIK/name → edgartools Company + L2 cached resolution
- `src/edgarmcp/cache.py` — L1 LRU cache for parsed filings + accession→filing map
- `src/edgarmcp/storage.py` — L2 persistent cache backend (FilesystemCache or S3Cache)
- `src/edgarmcp/filing_loader.py` — Load HTML → sec2md parse → sections/notes/attachments + L2 cache
- `src/edgarmcp/sections.py` — Section type mappings + extraction via sec2md
- `src/edgarmcp/attachment_types.py` — Exhibit classification (EX-99→press_release, etc.)
- `src/edgarmcp/auth.py` — API key auth middleware + /health + citation/filing HTML serving
- `src/edgarmcp/tools/` — One file per tool
- `src/edgarmcp/financials/` — Statement merger (Q4 inference, YTD, splits, TTM) + formatter
- `Dockerfile` + `railway.json` — Remote deployment to Railway

## Key design decisions

1. All tools return `str` (markdown) — no structured_content
2. Standalone — copies logic from intellifin, does not import it
3. `accession_to_filing` mapping lets `read_document` resolve filings without re-querying
4. Two-level cache: L1 in-memory LRU (~20 filings), L2 persistent (filesystem or S3). SEC filings are immutable — no TTL.
5. BM25 via `rank-bm25` — no GPU/API needed
6. Auto-generated API key when binding publicly (0.0.0.0). Auth required on MCP endpoints; `/health`, `/cite/`, `/filing/` are public.
7. Citations work remotely — filing HTML served through main ASGI app via `/cite/` and `/filing/` routes. Set `EDGARMCP_BASE_URL` for remote citation links.

## Environment variables

- `EDGAR_IDENTITY` — Required. SEC User-Agent identity.
- `EDGARMCP_API_KEY` — Bearer token for HTTP auth. Auto-generated if binding to 0.0.0.0.
- `EDGARMCP_BASE_URL` — Base URL for citation links in remote mode (e.g. `https://edgarmcp-production.up.railway.app`).
- `BUCKET`, `ACCESS_KEY_ID`, `SECRET_ACCESS_KEY`, `ENDPOINT`, `REGION` — S3-compatible cache backend (Railway Storage Buckets).
