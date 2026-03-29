"""Type definitions for edgarmcp."""

from typing import Literal


class EdgarError(Exception):
    """Raised when an EDGAR operation fails (company not found, filing load error, etc.)."""
    pass

FormType = Literal[
    "10-K", "10-Q", "8-K", "20-F", "6-K",
    "DEF 14A", "S-1", "SC 13D", "SC 13G", "4",
]

AttachmentType = Literal[
    "press_release", "investor_presentation", "cfo_commentary",
    "shareholder_letter", "press_or_investor",
    "material_contract", "merger_agreement", "underwriting_agreement",
    "debt_instrument", "indenture", "supplemental_indenture",
    "charter", "bylaws", "certificate_of_designations",
]

SectionType = Literal[
    "business", "risk_factors", "properties", "legal_proceedings",
    "market", "mda", "market_risk", "financial", "controls",
    "directors", "executive_compensation", "security_ownership",
    "relationships", "principal_accountant", "exhibits",
    "other_information", "unregistered_sales", "cybersecurity",
]

StatementType = Literal["income_statement", "balance_sheet", "cash_flow"]

ReportType = Literal["annual", "quarterly", "ttm"]

DEFAULT_FORMS = ["10-K", "10-Q", "8-K", "20-F", "DEF 14A"]

# Attachment types worth searching (skip certifications, XBRL, etc.)
SEARCHABLE_ATTACHMENT_TYPES = {
    "press_release", "investor_presentation", "cfo_commentary",
    "shareholder_letter", "press_or_investor",
    "material_contract", "merger_agreement", "debt_instrument",
    "charter", "bylaws",
}
