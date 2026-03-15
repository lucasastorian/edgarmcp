# edgarmcp

Zero-infrastructure MCP server for SEC EDGAR. 5 tools. No Postgres, no Qdrant, no Redis.
Spin up in 3 minutes. Resolves everything in real-time against EDGAR + XBRL.

---

## Why

Every serious financial workflow eventually hits EDGAR — and it's always the same bottleneck. You need the 10-K, but first you need to find the filing, then download it, then parse 200 pages of nested HTML, then locate the right section, then extract the table, then cross-reference it with last quarter. Multiply by every company in a portfolio.

edgarmcp gives an LLM direct, structured access to the entire EDGAR corpus through 5 tools:

- **`get_filings`** — Discover filings, press releases, contracts, and notes for any company
- **`read_document`** — Read filings, sections, exhibits, or individual notes as clean Markdown
- **`search_filings`** — BM25 search across a company's filings, attachments, and notes
- **`view_financials`** — Pull income statements, balance sheets, and cash flows from XBRL with Q4 inference, YTD normalization, stock split adjustment, and TTM computation
- **`search_edgar`** — Full-text search across the entire EDGAR corpus via SEC EFTS

The result: an LLM can go from "what did Apple say about AI risk in their last three 10-Ks?" to a sourced, cross-referenced answer in a single conversation — without you writing any glue code.

## What Makes This Different

**Multi-period financial statements, ready to analyze.** Pull 8 quarters of income statements, balance sheets, or cash flows in a single call. Q4 is inferred from full-year minus Q1-Q3. Year-to-date figures are normalized into individual quarters. Stock splits are detected and adjusted. TTM is computed. The LLM gets a clean table it can reason over immediately — not raw XBRL facts that need post-processing.

**Notes, press releases, and exhibits are individually addressable.** A 10-K isn't one document — it's a bundle. The press release has the earnings guidance. The EX-10.1 has the CEO's employment agreement. Note 2 has the revenue recognition policy that explains the numbers. edgarmcp makes every piece independently discoverable, readable, and searchable. "Show me Apple's last 5 press releases" or "read the revenue recognition note from the latest 10-K" — no manual navigation through parent filings required.

**Numbers link back to the accounting.** `view_financials` surfaces the notes index from the source filings alongside the numbers. The LLM can go from a line item in the income statement to the accounting policy that explains it in one hop — read the revenue recognition note, check the lease assumptions, dig into the segment breakdown. The financial statements and the prose that explains them are connected, not siloed.

**High-fidelity parsing underneath.** Powered by [sec2md](https://github.com/lucasastorian/sec2md), which converts SEC HTML into structured Markdown while preserving tables, page boundaries, section structure, iXBRL tags, and images. Every other EDGAR tool is only as good as its parser. Most use generic HTML-to-text converters that destroy the structure LLMs need to reason over financial documents.

**Clickable citations.** Search results and document reads include citation tags that link directly to the source element in the original SEC filing HTML. Click a citation and the filing opens in your browser with the relevant paragraph, table, or section highlighted and scrolled into view.

**Full-corpus discovery.** Search the entire EDGAR corpus for a topic ("material weakness" AND "internal controls"), get matching filings across all companies, then pipe those accession numbers into deep search within the filings themselves. Two-stage: broad discovery via SEC EFTS, then targeted analysis via BM25.

---

## What It Looks Like

### "Compare NVIDIA and AMD gross margins"
```
view_financials(symbol="NVDA", statement_type="income_statement", report_type="quarterly", periods=8)
view_financials(symbol="AMD", statement_type="income_statement", report_type="quarterly", periods=8)
-> Two markdown tables, 8 quarters each. LLM computes and compares.
```

### "How has Apple's risk factor language around AI changed?"
```
search_filings(query="artificial intelligence", company="AAPL", forms=["10-K"], sections=["risk_factors"], limit=5)
-> BM25 across last 5 10-K risk factors sections. Compare language year over year.
```

### "Read Apple's revenue recognition note"
```
get_filings(company="AAPL", forms=["10-K"], include_notes=true, limit=1)
-> Filing with notes index: note_1: Accounting Policies, note_2: Revenue Recognition, ...

read_document(accession_number="...", note_name="note_2")
-> Full note as clean Markdown.
```

### "Which semiconductor companies disclosed supply chain risks in 2024?"
```
search_edgar(query="\"supply chain risk\" AND \"semiconductor\"", forms=["10-K"], start_date="2024-01-01")
-> Discovery across all of EDGAR.

search_filings(query="supply chain concentration single source", accession_numbers=[top hits])
-> Deep search within those specific filings.
```

### "What did Apple say about AI in their latest earnings?"
```
search_filings(query="artificial intelligence AI", company="AAPL", forms=["8-K"], attachment_types=["press_release"], limit=3)
-> BM25 results from last 3 press releases, ranked by relevance.
```

### "Show me Apple's income statement, then explain the accounting"
```
view_financials(symbol="AAPL", statement_type="income_statement", report_type="quarterly")
-> Numbers + notes index with accession number.

read_document(accession_number="...", note_name="note_2")
-> Revenue recognition note from the source 10-K.
```

---

## Quick Start

### Install from PyPI

```bash
pip install edgarmcp
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

Section extraction covers 10-K (18 items), 10-Q (11 items), 8-K (41 items), 20-F, SC 13D, and SC 13G.

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
