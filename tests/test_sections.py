"""Tests for section type mappings."""

import pytest

from edgarmcp.sections import (
    TENK_SECTIONS,
    TENQ_SECTIONS_PART1,
    TENQ_SECTIONS_PART2,
    TWENTYF_SECTIONS,
    EIGHTK_SECTIONS,
    _get_section_map,
    _get_section_type,
)


class TestSectionMappings:
    """Verify key item → SectionType mappings are correct."""

    def test_10k_risk_factors(self):
        assert TENK_SECTIONS["ITEM 1A"] == "risk_factors"

    def test_10k_mda(self):
        assert TENK_SECTIONS["ITEM 7"] == "mda"

    def test_10k_financial(self):
        assert TENK_SECTIONS["ITEM 8"] == "financial"

    def test_10k_business(self):
        assert TENK_SECTIONS["ITEM 1"] == "business"

    def test_10k_cybersecurity(self):
        assert TENK_SECTIONS["ITEM 1C"] == "cybersecurity"

    def test_10q_part1_mda(self):
        assert TENQ_SECTIONS_PART1["ITEM 2"] == "mda"

    def test_10q_part2_risk_factors(self):
        assert TENQ_SECTIONS_PART2["ITEM 1A"] == "risk_factors"

    def test_20f_mda(self):
        assert TWENTYF_SECTIONS["ITEM 5"] == "mda"

    def test_20f_risk_factors(self):
        assert TWENTYF_SECTIONS["ITEM 3D"] == "risk_factors"

    def test_8k_financial(self):
        assert EIGHTK_SECTIONS["ITEM 2.02"] == "financial"

    def test_8k_exhibits(self):
        assert EIGHTK_SECTIONS["ITEM 9.01"] == "exhibits"


class TestGetSectionMap:
    def test_10k(self):
        assert _get_section_map("10-K") == TENK_SECTIONS

    def test_10k_amendment(self):
        assert _get_section_map("10-K/A") == TENK_SECTIONS

    def test_20f(self):
        assert _get_section_map("20-F") == TWENTYF_SECTIONS

    def test_8k(self):
        assert _get_section_map("8-K") == EIGHTK_SECTIONS

    def test_10q_returns_empty(self):
        """10-Q is handled specially via part logic, not via _get_section_map."""
        assert _get_section_map("10-Q") == {}

    def test_unsupported_form(self):
        assert _get_section_map("SC 13D") == {}


class FakeSection:
    """Minimal stand-in for sec2md Section object."""

    def __init__(self, item: str, part: str = ""):
        self.item = item
        self.part = part


class TestGetSectionType:
    def test_10k_item(self):
        s = FakeSection("ITEM 1A")
        assert _get_section_type(s, "10-K") == "risk_factors"

    def test_10q_part1(self):
        s = FakeSection("ITEM 2", part="PART I")
        assert _get_section_type(s, "10-Q") == "mda"

    def test_10q_part2(self):
        s = FakeSection("ITEM 1A", part="PART II")
        assert _get_section_type(s, "10-Q") == "risk_factors"

    def test_10q_unknown_part(self):
        s = FakeSection("ITEM 2", part="PART III")
        assert _get_section_type(s, "10-Q") is None

    def test_20f(self):
        s = FakeSection("ITEM 3D")
        assert _get_section_type(s, "20-F") == "risk_factors"

    def test_8k(self):
        s = FakeSection("ITEM 2.02")
        assert _get_section_type(s, "8-K") == "financial"

    def test_amendment_stripping(self):
        s = FakeSection("ITEM 7")
        assert _get_section_type(s, "10-K/A") == "mda"

    def test_unsupported_form(self):
        s = FakeSection("ITEM 1")
        assert _get_section_type(s, "SC 13D") is None

    def test_unmapped_item(self):
        s = FakeSection("ITEM 99")
        assert _get_section_type(s, "10-K") is None
