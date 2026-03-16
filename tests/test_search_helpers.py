"""Tests for search_filings pure helper functions."""

import pytest

from edgarmcp.tools.search_filings import _format_result_header, _describe_scope, _chunk_to_dict, _build_chunks
from edgarmcp.cache import ParsedFiling, AttachmentMeta, NoteMeta
from edgarmcp.sections import SectionInfo
from tests.conftest import FakePage, FakeElement


class TestFormatResultHeader:
    def test_main_filing(self):
        chunk = {
            "company_name": "Apple Inc.",
            "company_symbol": "AAPL",
            "form": "10-K",
            "filing_date": "2024-11-01",
            "report_date": "2024-09-28",
            "source_type": "main",
            "page": 5,
        }
        header = _format_result_header(chunk)
        assert "Apple Inc. (AAPL)" in header
        assert "10-K" in header
        assert "2024-11-01" in header
        assert "Page 5" in header

    def test_attachment_header(self):
        chunk = {
            "company_name": "Apple Inc.",
            "company_symbol": "AAPL",
            "form": "8-K",
            "filing_date": "2024-11-01",
            "source_type": "attachment",
            "attachment_type": "press_release",
            "exhibit_number": "99.1",
            "page": 1,
        }
        header = _format_result_header(chunk)
        assert "Press Release" in header
        assert "EX-99.1" in header

    def test_section_header(self):
        chunk = {
            "company_name": "Apple Inc.",
            "company_symbol": "AAPL",
            "form": "10-K",
            "filing_date": "2024-11-01",
            "source_type": "section",
            "section": "risk_factors",
            "page": 10,
        }
        header = _format_result_header(chunk)
        assert "Risk Factors" in header

    def test_note_header(self):
        chunk = {
            "company_name": "Apple Inc.",
            "company_symbol": "AAPL",
            "form": "10-K",
            "filing_date": "2024-11-01",
            "source_type": "note",
            "note_name": "note_2",
            "page": 15,
        }
        header = _format_result_header(chunk)
        assert "note_2" in header


class TestDescribeScope:
    def test_company_and_forms(self):
        result = _describe_scope("AAPL", ["10-K", "10-Q"], None, None, None)
        assert "AAPL" in result
        assert "10-K" in result

    def test_accession_numbers(self):
        result = _describe_scope(None, None, ["acc-1", "acc-2"], None, None)
        assert "2 filings" in result

    def test_with_attachment_types(self):
        result = _describe_scope("AAPL", ["8-K"], None, ["press_release"], None)
        assert "press_release" in result

    def test_with_sections(self):
        result = _describe_scope("AAPL", ["10-K"], None, None, ["risk_factors", "mda"])
        assert "risk_factors" in result

    def test_empty(self):
        assert _describe_scope(None, None, None, None, None) == "filings"


# Minimal Chunk stand-in for sec2md chunks
class FakeChunk:
    def __init__(self, content, start_page=1, tags=None, element_ids=None):
        self.content = content
        self.start_page = start_page
        self.tags = tags or set()
        self.element_ids = element_ids or []


class TestChunkToDict:
    def test_basic_conversion(self, sample_parsed_filing):
        c = FakeChunk("Revenue grew 10%", start_page=3, tags={"us-gaap:Revenue"}, element_ids=["el-1"])
        result = _chunk_to_dict(c, "main", sample_parsed_filing)
        assert result["text"] == "Revenue grew 10%"
        assert result["source_type"] == "main"
        assert result["accession"] == "0000320193-24-000081"
        assert result["company_symbol"] == "AAPL"
        assert result["page"] == 3
        assert "us-gaap:Revenue" in result["tags"]


class TestBuildChunks:
    """Test that _build_chunks produces the right chunk sources."""

    def _make_filing_with_pages(self) -> ParsedFiling:
        """Create a ParsedFiling with pages that have proper content for chunking."""
        pages = [
            FakePage(
                number=i + 1,
                content=f"Filing content for page {i + 1}. " * 20,  # enough for chunking
                elements=[],  # empty so chunk_pages uses content-based splitting
            )
            for i in range(10)
        ]
        return ParsedFiling(
            accession_number="acc-test",
            form="10-K",
            filing_date="2024-01-01",
            report_date="2023-12-31",
            company_symbol="TEST",
            company_name="Test Corp",
            cik="12345",
            pages=pages,
            notes=[
                NoteMeta(name="note_1", title="Accounting Policies", start_page=1, end_page=2),
                NoteMeta(name="note_2", title="Revenue", start_page=3, end_page=4),
            ],
            attachments=[],
        )

    def test_default_branch_includes_notes(self):
        """After the bug fix, default branch should chunk notes."""
        parsed = self._make_filing_with_pages()
        chunks = _build_chunks(parsed, attachment_types=None, section_types=None)
        source_types = {c["source_type"] for c in chunks}
        assert "main" in source_types
        assert "note" in source_types

    def test_default_branch_note_metadata(self):
        parsed = self._make_filing_with_pages()
        chunks = _build_chunks(parsed, attachment_types=None, section_types=None)
        note_chunks = [c for c in chunks if c["source_type"] == "note"]
        assert len(note_chunks) > 0
        note_names = {c["note_name"] for c in note_chunks}
        assert "note_1" in note_names or "note_2" in note_names
