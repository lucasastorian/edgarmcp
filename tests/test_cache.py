"""Tests for LRU filing cache."""

import pytest

from edgarmcp.cache import FilingCache, ParsedFiling


def _make_parsed(accession: str) -> ParsedFiling:
    return ParsedFiling(
        accession_number=accession,
        form="10-K",
        filing_date="2024-01-01",
        report_date="2023-12-31",
        company_symbol="TEST",
        company_name="Test Corp",
        cik="12345",
        pages=[],
    )


class TestFilingCache:
    def test_put_and_get(self):
        cache = FilingCache(max_size=5)
        parsed = _make_parsed("acc-1")
        cache.put(parsed)
        assert cache.get("acc-1") is parsed

    def test_get_missing(self):
        cache = FilingCache()
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self):
        cache = FilingCache(max_size=3)
        cache.put(_make_parsed("acc-1"))
        cache.put(_make_parsed("acc-2"))
        cache.put(_make_parsed("acc-3"))
        cache.put(_make_parsed("acc-4"))  # should evict acc-1
        assert cache.get("acc-1") is None
        assert cache.get("acc-2") is not None

    def test_access_refreshes_lru(self):
        cache = FilingCache(max_size=3)
        cache.put(_make_parsed("acc-1"))
        cache.put(_make_parsed("acc-2"))
        cache.put(_make_parsed("acc-3"))
        cache.get("acc-1")  # refresh acc-1
        cache.put(_make_parsed("acc-4"))  # should evict acc-2 (oldest untouched)
        assert cache.get("acc-1") is not None
        assert cache.get("acc-2") is None

    def test_duplicate_put_updates(self):
        cache = FilingCache(max_size=5)
        p1 = _make_parsed("acc-1")
        p2 = _make_parsed("acc-1")
        p2.form = "10-Q"
        cache.put(p1)
        cache.put(p2)
        assert cache.get("acc-1").form == "10-Q"


class TestFilingRefStorage:
    def test_store_and_get_ref(self):
        cache = FilingCache()
        sentinel = object()
        cache.store_filing_ref("acc-1", sentinel)
        assert cache.get_filing_ref("acc-1") is sentinel

    def test_get_missing_ref(self):
        cache = FilingCache()
        assert cache.get_filing_ref("nonexistent") is None
