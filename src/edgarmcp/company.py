"""Company resolution — ticker/name/CIK to edgartools Company."""

import gzip
import json
import logging

from edgar import Company as EdgarCompany

from .storage import backend as l2_backend
from .types import EdgarError

logger = logging.getLogger(__name__)


class CompanyInfo:
    __slots__ = ("symbol", "name", "cik", "edgar_company")

    def __init__(self, symbol: str, name: str, cik: str, edgar_company: EdgarCompany):
        self.symbol = symbol
        self.name = name
        self.cik = cik
        self.edgar_company = edgar_company


def resolve_company(query: str) -> CompanyInfo:
    """Resolve a ticker, CIK, or company name to CompanyInfo.

    Raises EdgarError if the company cannot be found.
    """
    query = query.strip()
    if not query:
        raise EdgarError("No company identifier provided.")

    try:
        company = EdgarCompany(query)
    except Exception as e:
        logger.error(f"Company resolution failed for '{query}': {e}")
        raise EdgarError(f"Failed to resolve company '{query}': {e}") from e

    if company.not_found:
        raise EdgarError(f"Company not found: '{query}'. Try a ticker symbol (e.g. AAPL), CIK number, or company name.")

    tickers = company.tickers
    symbol = tickers[0] if tickers else query.upper()

    return CompanyInfo(
        symbol=symbol,
        name=company.name or query,
        cik=str(company.cik),
        edgar_company=company,
    )


async def resolve_company_cached(query: str) -> CompanyInfo:
    """Resolve company with L2 persistent cache.

    On L2 hit, reconstructs EdgarCompany from cached CIK (faster than name/ticker search).
    Raises EdgarError if the company cannot be found.
    """
    query = query.strip()
    if not query:
        raise EdgarError("No company identifier provided.")

    key = f"companies/{query.upper()}.json.gz"
    data = await l2_backend.get(key)
    if data:
        try:
            info = json.loads(gzip.decompress(data))
            company = EdgarCompany(info["cik"])
            if not company.not_found:
                return CompanyInfo(
                    symbol=info["symbol"],
                    name=info["name"],
                    cik=info["cik"],
                    edgar_company=company,
                )
        except Exception as e:
            logger.warning(f"L2 company cache failed for {query}: {e}")

    result = resolve_company(query)

    try:
        cache_data = json.dumps({"symbol": result.symbol, "name": result.name, "cik": result.cik})
        await l2_backend.put(key, gzip.compress(cache_data.encode()))
    except Exception as e:
        logger.warning(f"L2 company cache write failed for {query}: {e}")

    return result
