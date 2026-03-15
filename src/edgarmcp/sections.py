"""Section type mappings and extraction wrapper."""

import logging
from dataclasses import dataclass, field
from typing import Optional

from sec2md import SectionExtractor

logger = logging.getLogger(__name__)

# Section item -> SectionType mappings
TENK_SECTIONS = {
    "ITEM 1": "business",
    "ITEM 1A": "risk_factors",
    "ITEM 1C": "cybersecurity",
    "ITEM 2": "properties",
    "ITEM 3": "legal_proceedings",
    "ITEM 5": "market",
    "ITEM 7": "mda",
    "ITEM 7A": "market_risk",
    "ITEM 8": "financial",
    "ITEM 9A": "controls",
    "ITEM 9B": "other_information",
    "ITEM 10": "directors",
    "ITEM 11": "executive_compensation",
    "ITEM 12": "security_ownership",
    "ITEM 13": "relationships",
    "ITEM 14": "principal_accountant",
    "ITEM 15": "exhibits",
    "ITEM 16": "exhibits",
}

TENQ_SECTIONS_PART1 = {
    "ITEM 2": "mda",
    "ITEM 3": "market_risk",
    "ITEM 4": "controls",
}

TENQ_SECTIONS_PART2 = {
    "ITEM 1": "legal_proceedings",
    "ITEM 1A": "risk_factors",
    "ITEM 2": "unregistered_sales",
    "ITEM 5": "other_information",
}

TWENTYF_SECTIONS = {
    "ITEM 3": "business",
    "ITEM 3D": "risk_factors",
    "ITEM 4": "business",
    "ITEM 5": "mda",
    "ITEM 6": "directors",
    "ITEM 8": "legal_proceedings",
    "ITEM 11": "market_risk",
    "ITEM 15": "controls",
}

EIGHTK_SECTIONS = {
    "ITEM 1.01": "legal_proceedings",
    "ITEM 1.02": "legal_proceedings",
    "ITEM 1.03": "legal_proceedings",
    "ITEM 2.01": "business",
    "ITEM 2.02": "financial",
    "ITEM 2.03": "financial",
    "ITEM 2.04": "financial",
    "ITEM 2.05": "financial",
    "ITEM 2.06": "financial",
    "ITEM 3.01": "market",
    "ITEM 3.02": "unregistered_sales",
    "ITEM 3.03": "market",
    "ITEM 4.01": "controls",
    "ITEM 4.02": "financial",
    "ITEM 5.01": "controls",
    "ITEM 5.02": "directors",
    "ITEM 5.03": "controls",
    "ITEM 5.07": "market",
    "ITEM 5.08": "directors",
    "ITEM 7.01": "other_information",
    "ITEM 8.01": "other_information",
    "ITEM 9.01": "exhibits",
}


@dataclass
class SectionInfo:
    type: str
    label: str
    start_page: int
    end_page: int
    pages: list = field(default_factory=list)


def _get_section_map(filing_type: str) -> dict:
    """Get the appropriate section mapping for a filing type."""
    ft = filing_type.replace("/A", "")
    if ft == "10-K":
        return TENK_SECTIONS
    elif ft == "20-F":
        return TWENTYF_SECTIONS
    elif ft == "8-K":
        return EIGHTK_SECTIONS
    return {}  # 10-Q handled specially


def _get_section_type(section, filing_type: str) -> Optional[str]:
    """Map a sec2md section object to our SectionType."""
    ft = filing_type.replace("/A", "")
    if ft == "10-K":
        return TENK_SECTIONS.get(section.item)
    elif ft == "10-Q":
        if section.part == "PART I":
            return TENQ_SECTIONS_PART1.get(section.item)
        elif section.part == "PART II":
            return TENQ_SECTIONS_PART2.get(section.item)
        return None
    elif ft == "20-F":
        return TWENTYF_SECTIONS.get(section.item)
    elif ft == "8-K":
        return EIGHTK_SECTIONS.get(section.item)
    return None


def extract_sections(pages: list, filing_type: str) -> list[SectionInfo]:
    """Extract sections from parsed pages using sec2md SectionExtractor.

    Returns list of SectionInfo with mapped SectionType.
    """
    ft = filing_type.replace("/A", "")
    if ft not in ("10-K", "10-Q", "20-F", "8-K"):
        return []

    try:
        extractor = SectionExtractor(pages=pages, filing_type=ft)
        raw_sections = extractor.get_sections()
    except Exception as e:
        if "Section must contain at least one page" in str(e):
            logger.warning(f"sec2md empty section pages for {filing_type}")
            return []
        logger.warning(f"Section extraction failed for {filing_type}: {e}")
        return []

    result = []
    for section in raw_sections:
        section_type = _get_section_type(section, filing_type)
        if not section_type:
            continue
        if not section.pages:
            continue
        page_nums = [p.number for p in section.pages]
        result.append(SectionInfo(
            type=section_type,
            label=getattr(section, 'item_title', None) or section.item,
            start_page=min(page_nums),
            end_page=max(page_nums),
            pages=list(section.pages),
        ))
    return result
