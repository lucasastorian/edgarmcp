"""Company resolution — ticker/name/CIK to edgartools Company."""

import logging
from dataclasses import dataclass
from typing import Optional

from edgar import Company as EdgarCompany

logger = logging.getLogger(__name__)


@dataclass
class CompanyInfo:
    symbol: str
    name: str
    cik: str
    edgar_company: EdgarCompany


def resolve_company(query: str) -> CompanyInfo | str:
    """Resolve a ticker, CIK, or company name to CompanyInfo.

    Returns CompanyInfo on success, or an error message string on failure.
    """
    query = query.strip()
    if not query:
        return "No company identifier provided."

    try:
        company = EdgarCompany(query)
        if company.not_found:
            return f"Company not found: '{query}'. Try a ticker symbol (e.g. AAPL), CIK number, or company name."
        return CompanyInfo(
            symbol=getattr(company, 'tickers', [query])[0] if getattr(company, 'tickers', None) else query.upper(),
            name=company.name or query,
            cik=str(company.cik),
            edgar_company=company,
        )
    except Exception as e:
        logger.error(f"Company resolution failed for '{query}': {e}")
        return f"Failed to resolve company '{query}': {e}"
