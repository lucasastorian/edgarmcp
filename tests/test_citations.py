"""Tests for citation registry."""

import pytest

from edgarmcp.citations import CitationRegistry


@pytest.fixture
def reg():
    return CitationRegistry(enabled=True, port=19823)


@pytest.fixture
def disabled_reg():
    return CitationRegistry(enabled=False)


class TestCitationRegistry:
    def test_add_returns_incrementing_ids(self, reg):
        id1 = reg.add(accession_number="acc-1", element_ids=["e1"], source_type="main")
        id2 = reg.add(accession_number="acc-1", element_ids=["e2"], source_type="main")
        assert id1 == 1
        assert id2 == 2

    def test_get_returns_citation(self, reg):
        cid = reg.add(
            accession_number="acc-1",
            element_ids=["e1", "e2"],
            source_type="section",
            form="10-K",
            section="risk_factors",
        )
        c = reg.get(cid)
        assert c.accession_number == "acc-1"
        assert c.element_ids == ["e1", "e2"]
        assert c.source_type == "section"
        assert c.section == "risk_factors"

    def test_get_missing_returns_none(self, reg):
        assert reg.get(999) is None

    def test_disabled_add_returns_none(self, disabled_reg):
        result = disabled_reg.add(accession_number="acc-1", element_ids=["e1"], source_type="main")
        assert result is None

    def test_empty_element_ids_returns_none(self, reg):
        result = reg.add(accession_number="acc-1", element_ids=[], source_type="main")
        assert result is None

    def test_session_id_is_hex(self, reg):
        assert len(reg.session_id) == 6
        int(reg.session_id, 16)  # should not raise


class TestCitationUrls:
    def test_base_url(self, reg):
        assert reg.base_url == f"http://localhost:19823/{reg.session_id}"

    def test_citation_url(self, reg):
        cid = reg.add(accession_number="acc-1", element_ids=["e1"], source_type="main")
        assert reg.citation_url(cid) == f"http://localhost:19823/{reg.session_id}/{cid}"

    def test_custom_port(self):
        reg = CitationRegistry(port=8080)
        assert "8080" in reg.base_url


class TestFormatTag:
    def test_valid_id(self, reg):
        assert reg.format_tag(1) == " <1>"
        assert reg.format_tag(42) == " <42>"

    def test_none_returns_empty(self, reg):
        assert reg.format_tag(None) == ""


class TestFormatInstructions:
    def test_enabled(self, reg):
        instructions = reg.format_instructions()
        assert "Citations" in instructions
        assert reg.session_id in instructions

    def test_disabled(self, disabled_reg):
        assert disabled_reg.format_instructions() == ""
