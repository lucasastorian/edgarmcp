"""Tests for HTML server citation routing logic."""

import pytest

from edgarmcp.citations import Citation, CitationRegistry
from edgarmcp.html_server import cache_annotated_html, HIGHLIGHT_SCRIPT


class TestCitationRedirectTarget:
    """Test the redirect URL construction logic from handle_citation.

    We test the logic without spinning up aiohttp — just the URL construction.
    """

    def _build_redirect_url(self, citation: Citation) -> str:
        """Replicate the redirect URL logic from handle_citation."""
        fragment = ",".join(citation.element_ids)
        if citation.source_type == "attachment" and citation.exhibit_number:
            filename = f"{citation.accession_number}_ex_{citation.exhibit_number}"
        else:
            filename = citation.accession_number
        return f"/filing/{filename}.html#{fragment}"

    def test_main_filing_redirect(self):
        c = Citation(
            id=1,
            accession_number="0000320193-24-000081",
            element_ids=["el-1", "el-2"],
            source_type="main",
        )
        url = self._build_redirect_url(c)
        assert url == "/filing/0000320193-24-000081.html#el-1,el-2"

    def test_attachment_redirect(self):
        c = Citation(
            id=2,
            accession_number="0000320193-24-000081",
            element_ids=["el-5"],
            source_type="attachment",
            exhibit_number="99.1",
        )
        url = self._build_redirect_url(c)
        assert url == "/filing/0000320193-24-000081_ex_99.1.html#el-5"

    def test_section_redirect(self):
        """Sections use main filing HTML, not a separate file."""
        c = Citation(
            id=3,
            accession_number="0000320193-24-000081",
            element_ids=["el-10"],
            source_type="section",
            section="risk_factors",
        )
        url = self._build_redirect_url(c)
        assert url == "/filing/0000320193-24-000081.html#el-10"

    def test_note_redirect(self):
        """Notes use main filing HTML."""
        c = Citation(
            id=4,
            accession_number="0000320193-24-000081",
            element_ids=["el-20"],
            source_type="note",
            note_name="note_2",
        )
        url = self._build_redirect_url(c)
        assert url == "/filing/0000320193-24-000081.html#el-20"

    def test_attachment_without_exhibit_number(self):
        """Edge case: attachment source_type but no exhibit_number uses main path."""
        c = Citation(
            id=5,
            accession_number="0000320193-24-000081",
            element_ids=["el-1"],
            source_type="attachment",
            exhibit_number=None,
        )
        url = self._build_redirect_url(c)
        assert url == "/filing/0000320193-24-000081.html#el-1"


class TestCacheAnnotatedHtml:
    def test_injects_script_before_body_end(self, tmp_path, monkeypatch):
        monkeypatch.setattr("edgarmcp.html_server.CACHE_DIR", tmp_path)
        html = "<html><body><p>Content</p></body></html>"
        path = cache_annotated_html("acc-123", html)
        result = path.read_text()
        assert "sec2md-highlight" in result
        assert result.index("sec2md-highlight") < result.index("</body>")

    def test_appends_script_when_no_body_tag(self, tmp_path, monkeypatch):
        monkeypatch.setattr("edgarmcp.html_server.CACHE_DIR", tmp_path)
        html = "<div>Content only</div>"
        path = cache_annotated_html("acc-456", html)
        result = path.read_text()
        assert "sec2md-highlight" in result

    def test_filename_from_accession(self, tmp_path, monkeypatch):
        monkeypatch.setattr("edgarmcp.html_server.CACHE_DIR", tmp_path)
        path = cache_annotated_html("0000320193-24-000081", "<html></html>")
        assert path.name == "0000320193-24-000081.html"
