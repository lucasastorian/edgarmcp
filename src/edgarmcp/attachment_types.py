"""Attachment type inference from exhibit numbers and descriptions."""

import re
from typing import Optional

SKIP_EXHIBITS = {
    "EX-31", "EX-31.1", "EX-31.2",
    "EX-32", "EX-32.1", "EX-32.2",
    "EX-101", "EX-23", "EX-23.1", "EX-24",
}


def infer_attachment_type(exhibit_number: str, description: Optional[str] = None) -> str:
    """Classify an exhibit by number and description."""
    parts = exhibit_number.split(".")
    prefix = parts[0]
    suffix = parts[1] if len(parts) > 1 else None

    type_map = {
        "1": "underwriting_agreement",
        "5": "legal_opinion",
        "10": "material_contract",
        "21": "subsidiaries",
        "23": "consent",
    }

    if prefix in type_map:
        return type_map[prefix]
    elif prefix == "2":
        return "merger_agreement" if suffix == "1" else "other"
    elif prefix == "3":
        return {"1": "certificate_of_designations", "2": "bylaws"}.get(suffix, "charter")
    elif prefix == "4":
        return {"1": "indenture", "2": "supplemental_indenture"}.get(suffix, "debt_instrument")
    elif prefix == "99":
        return _classify_ex99(description)
    return "other"


def _classify_ex99(description: Optional[str] = None) -> str:
    """Classify EX-99.x exhibits by description text."""
    if not description:
        return "press_or_investor"
    # Strip descriptions that just echo the exhibit type (e.g. "EX-99.1", "EXHIBIT 10.1")
    if re.match(r'^(EX-?\d|EXHIBIT\s+\d)', description, re.IGNORECASE):
        return "press_or_investor"
    desc_lower = description.lower()
    for pattern, result in [
        (r'cfo\s+commentary', "cfo_commentary"),
        (r'press\s+release|news\s+release|earnings\s+release|media\s+release', "press_release"),
        (r'investor\s+presentation|earnings\s+presentation|earnings\s+deck|investor\s+deck', "investor_presentation"),
        (r'shareholder\s+letter|letter\s+to\s+shareholders', "shareholder_letter"),
    ]:
        if re.search(pattern, desc_lower):
            return result
    return "press_or_investor"


def matches_attachment_type(att_type: str, requested_types: list[str]) -> bool:
    """Check if an attachment type matches the requested filter.

    press_or_investor is a wildcard — matches press_release or investor_presentation.
    """
    if att_type in requested_types:
        return True
    if att_type == "press_or_investor":
        return "press_release" in requested_types or "investor_presentation" in requested_types
    return False
