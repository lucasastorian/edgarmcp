# edgarmcp

MCP server for SEC EDGAR. 5 tools, zero infrastructure. Resolves everything in real-time against EDGAR + XBRL.

- **`get_filings`** — Discover filings, press releases, contracts, and notes
- **`read_document`** — Read filings, sections, exhibits, or notes as Markdown
- **`search_filings`** — BM25 search across filings, attachments, and notes
- **`view_financials`** — XBRL statements with Q4 inference, YTD normalization, stock splits, TTM
- **`search_edgar`** — Full-text search across all of EDGAR (SEC EFTS)

### Key features

- **Multi-period financials** — Pull 8 quarters or 3 years in one call. Q4 inferred, YTD normalized, stock splits adjusted, TTM computed.
- **Everything is addressable** — Sections, press releases, exhibits, and notes are individually discoverable, readable, and searchable.
- **Clickable citations** — Results link to the exact element in the original SEC filing HTML. Click to open, highlight, and scroll to source.
- **High-fidelity parsing** — Powered by [sec2md](https://github.com/lucasastorian/sec2md). Tables, sections, iXBRL tags, and page structure preserved.
- **Two-stage search** — Broad discovery across all EDGAR via EFTS, then deep BM25 search within specific filings.

---

## Quick Start

### Install from PyPI

```bash
pip install mcp-sec-edgar
```

Or install from source:

```bash
git clone https://github.com/lucasastorian/edgarmcp.git
cd edgarmcp
pip install -e .
```

### Claude Code

```bash
claude mcp add edgarmcp -- env EDGAR_IDENTITY="Your Name your@email.com" edgarmcp
```

### Claude Desktop

Add to your Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "edgarmcp": {
      "command": "edgarmcp",
      "env": {
        "EDGAR_IDENTITY": "Your Name your@email.com"
      }
    }
  }
}
```

If installed from source with uv:

```json
{
  "mcpServers": {
    "edgarmcp": {
      "command": "uv",
      "args": ["--directory", "/path/to/edgarmcp", "run", "edgarmcp"],
      "env": {
        "EDGAR_IDENTITY": "Your Name your@email.com"
      }
    }
  }
}
```

Restart Claude Desktop. `edgarmcp` should appear as an MCP server.

### Transport

```bash
edgarmcp                            # stdio (default)
edgarmcp --http --port 8000         # streamable HTTP
edgarmcp --no-citations             # disable citation server
```

### EDGAR Identity

The SEC requires a User-Agent header identifying who is making requests. Set the `EDGAR_IDENTITY` environment variable to your name and email:

```bash
export EDGAR_IDENTITY="Your Name your@email.com"
```

---

## Tools

### `get_filings`

Discover a company's SEC filings, attachments, and notes — all as a flat document list. Combines company lookup, filing listing, attachment listing, and notes listing in a single tool.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `company` | `str` | yes | Ticker, company name, or CIK |
| `forms` | `list[FormType]` | no | Filter by form type (default: major forms) |
| `attachment_types` | `list[AttachmentType]` | no | Filter to specific attachment types |
| `include_notes` | `bool` | no | Include notes to financial statements |
| `start_date` / `end_date` | `str` | no | YYYY-MM-DD date range (default: last 2 years) |
| `limit` | `int` | no | Max documents returned (default: 20, max: 100) |

Supported forms: 10-K, 10-Q, 8-K, 20-F, 6-K, DEF 14A, S-1, SC 13D, SC 13G, Form 4. Attachment types include press releases, investor presentations, material contracts, merger agreements, debt instruments, charter/bylaws, and more.

### `read_document`

Unified reader — one tool for main filings, sections, press releases, exhibits, and notes. Route by parameter:

| Parameter | Type | Required | Description |
|---|---|---|---|
| `accession_number` | `str` | yes | Filing accession number |
| `section` | `SectionType` | no | Specific section (e.g. `"risk_factors"`, `"mda"`) |
| `exhibit_number` | `str` | no | Exhibit to read (e.g. `"99.1"`) |
| `note_name` | `str` | no | Note to read (e.g. `"note_2"`) |
| `start_page` / `end_page` | `int` | no | Page range (max 20 pages per request) |

First read of any filing returns a navigation header with sections, notes, and attachments — the LLM uses these to decide where to go next.

Section extraction covers 10-K, 10-Q, 8-K, and 20-F.

### `search_filings`

BM25 search across a company's filings, attachments, and notes. Resolves filings internally, loads and parses them, chunks everything, and ranks by BM25.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | `str` | yes | Search query |
| `company` | `str` | yes* | Ticker/name/CIK (*or provide `accession_numbers`) |
| `forms` | `list[FormType]` | yes* | Form types to search |
| `sections` | `list[SectionType]` | no | Scope to specific sections |
| `attachment_types` | `list[AttachmentType]` | no | Search only these attachment types |
| `xbrl_tags` | `list[str]` | no | Filter to chunks containing XBRL concept tags |
| `accession_numbers` | `list[str]` | no | Search explicit filings directly |
| `limit` | `int` | no | Max filings to load (default: 5, max: 10) |
| `top_k` | `int` | no | Results to return (default: 10, max: 25) |

Searches main filing pages, notes, and high-value attachments (press releases, investor presentations, material contracts, etc.) by default.

### `view_financials`

Pull financial statements from XBRL with full period merging.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `symbol` | `str` | yes | Ticker symbol |
| `statement_type` | `StatementType` | yes | `income_statement`, `balance_sheet`, or `cash_flow` |
| `report_type` | `ReportType` | yes | `annual`, `quarterly`, or `ttm` |
| `periods` | `int` | no | Number of periods (default: 4, max: 8) |

Under the hood: loads XBRL from filings, extracts statement DataFrames, then runs Q4 inference (FY - Q1 - Q2 - Q3), YTD normalization (converting 6M/9M data to individual quarters), stock split adjustment, and TTM computation. Returns a clean Markdown table with the notes index from the source filings so the LLM can immediately dig into accounting details.

### `search_edgar`

Full-text search across the entire EDGAR corpus using SEC EFTS.

| Parameter | Type | Required | Description |
|---|---|---|---|
| `query` | `str` | yes | Full-text query (supports boolean operators) |
| `entity` | `str` | no | Company name or CIK to scope the search |
| `forms` | `list[FormType]` | no | Filter by form type |
| `start_date` / `end_date` | `str` | no | YYYY-MM-DD |
| `limit` | `int` | no | Max results (default: 10, max: 50) |

The discovery tool. Search all of EDGAR without knowing which companies to look at. Pipe results into `read_document` or `search_filings` for deeper analysis.

---

## Design Decisions

**5 tools, maximum coverage.** Company lookup, filing listing, attachment listing, and notes listing are consolidated into `get_filings`. Filing, attachment, and note reading are unified in `read_document`. Minimum surface area for the LLM.

**No database.** Everything resolved in real-time against EDGAR. Slower per-query but zero setup. Parsed filings cached in an LRU (~20 most recent) so repeat reads are instant.

**BM25 over embeddings.** Pure Python, no GPU or API needed. Good enough for keyword-heavy SEC filings. SEC EFTS covers cross-corpus discovery.

---

## Limitations

- **No embedding search** — BM25 only. Mitigated by SEC EFTS for cross-corpus discovery.
- **Cold start per filing** — First read requires download + parse (~2-5s). Subsequent reads cached.
- **SEC rate limits** — 10 requests/second. Parallel loading respects this via edgartools-async.
- **XBRL availability** — `view_financials` requires XBRL (10-K/10-Q/20-F, generally available since ~2009).
- **No market data** — No price or market cap context.
- **Memory** — Each cached filing ~1-5MB. 20 filings = 20-100MB.
- **`view_financials` latency** — Loading XBRL for 4-8 filings takes ~5-15s on first call.

## Dependencies

[edgartools-async](https://github.com/dgunning/edgartools), [sec2md](https://github.com/lucasastorian/sec2md), [mcp](https://github.com/modelcontextprotocol/python-sdk) (FastMCP), [rank-bm25](https://github.com/dorianbrown/rank_bm25), [pydantic](https://github.com/pydantic/pydantic), [pandas](https://github.com/pandas-dev/pandas)

## License

Apache 2.0 — see [LICENSE](LICENSE) for details.
