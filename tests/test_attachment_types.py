"""Tests for attachment type inference and matching."""

import pytest

from edgarmcp.attachment_types import infer_attachment_type, matches_attachment_type, SKIP_EXHIBITS


class TestInferAttachmentType:
    """Classification table — each exhibit prefix maps to the expected type."""

    @pytest.mark.parametrize(
        "exhibit, expected",
        [
            ("1", "underwriting_agreement"),
            ("1.1", "underwriting_agreement"),
            ("5", "legal_opinion"),
            ("5.1", "legal_opinion"),
            ("10", "material_contract"),
            ("10.1", "material_contract"),
            ("10.25", "material_contract"),
            ("21", "subsidiaries"),
            ("21.1", "subsidiaries"),
            ("23", "consent"),
            ("23.1", "consent"),
        ],
    )
    def test_direct_prefix_mapping(self, exhibit, expected):
        assert infer_attachment_type(exhibit) == expected

    @pytest.mark.parametrize(
        "exhibit, expected",
        [
            ("2.1", "merger_agreement"),
            ("2.2", "other"),
            ("2.3", "other"),
        ],
    )
    def test_prefix_2(self, exhibit, expected):
        assert infer_attachment_type(exhibit) == expected

    @pytest.mark.parametrize(
        "exhibit, expected",
        [
            ("3", "charter"),
            ("3.1", "certificate_of_designations"),
            ("3.2", "bylaws"),
            ("3.3", "charter"),
        ],
    )
    def test_prefix_3(self, exhibit, expected):
        assert infer_attachment_type(exhibit) == expected

    @pytest.mark.parametrize(
        "exhibit, expected",
        [
            ("4", "debt_instrument"),
            ("4.1", "indenture"),
            ("4.2", "supplemental_indenture"),
            ("4.3", "debt_instrument"),
        ],
    )
    def test_prefix_4(self, exhibit, expected):
        assert infer_attachment_type(exhibit) == expected

    def test_unknown_prefix(self):
        assert infer_attachment_type("999") == "other"
        assert infer_attachment_type("15.1") == "other"


class TestClassifyEx99:
    """EX-99 classification by description text."""

    @pytest.mark.parametrize(
        "desc, expected",
        [
            ("Q3 2024 Press Release", "press_release"),
            ("News Release dated October 31, 2024", "press_release"),
            ("Earnings Release", "press_release"),
            ("Media Release", "press_release"),
            ("Investor Presentation Q3 2024", "investor_presentation"),
            ("Earnings Deck", "investor_presentation"),
            ("Investor Deck", "investor_presentation"),
            ("Earnings Presentation", "investor_presentation"),
            ("CFO Commentary for Q3 2024", "cfo_commentary"),
            ("Letter to Shareholders", "shareholder_letter"),
            ("Shareholder Letter", "shareholder_letter"),
        ],
    )
    def test_description_classification(self, desc, expected):
        assert infer_attachment_type("99.1", description=desc) == expected

    def test_no_description(self):
        assert infer_attachment_type("99.1") == "press_or_investor"

    def test_echo_description_ignored(self):
        """Descriptions that just echo exhibit type fall through to default."""
        assert infer_attachment_type("99.1", description="EX-99.1") == "press_or_investor"
        assert infer_attachment_type("99.1", description="EXHIBIT 99.1") == "press_or_investor"

    def test_generic_description(self):
        assert infer_attachment_type("99.1", description="Financial Information") == "press_or_investor"


class TestMatchesAttachmentType:
    def test_exact_match(self):
        assert matches_attachment_type("press_release", ["press_release"]) is True

    def test_no_match(self):
        assert matches_attachment_type("material_contract", ["press_release"]) is False

    def test_wildcard_press_or_investor(self):
        """press_or_investor matches either press_release or investor_presentation."""
        assert matches_attachment_type("press_or_investor", ["press_release"]) is True
        assert matches_attachment_type("press_or_investor", ["investor_presentation"]) is True
        assert matches_attachment_type("press_or_investor", ["material_contract"]) is False

    def test_multiple_requested(self):
        assert matches_attachment_type("charter", ["charter", "bylaws"]) is True


class TestSkipExhibits:
    def test_certifications_skipped(self):
        assert "EX-31" in SKIP_EXHIBITS
        assert "EX-31.1" in SKIP_EXHIBITS
        assert "EX-32" in SKIP_EXHIBITS

    def test_xbrl_skipped(self):
        assert "EX-101" in SKIP_EXHIBITS

    def test_consent_skipped(self):
        assert "EX-23" in SKIP_EXHIBITS
