"""LRU cache for parsed filings and accession-to-filing mapping."""

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

from .sections import SectionInfo


@dataclass
class AttachmentMeta:
    exhibit_number: str
    document_type: str
    description: str
    attachment_type: str
    filename: str


@dataclass
class NoteMeta:
    name: str  # e.g. "note_1"
    title: str
    start_page: int
    end_page: int


@dataclass
class ParsedFiling:
    accession_number: str
    form: str
    filing_date: str
    report_date: Optional[str]
    company_symbol: str
    company_name: str
    cik: str
    pages: list  # list of sec2md Page objects
    sections: list[SectionInfo] = field(default_factory=list)
    notes: list[NoteMeta] = field(default_factory=list)
    note_blocks: list = field(default_factory=list)  # sec2md TextBlock objects
    attachments: list[AttachmentMeta] = field(default_factory=list)
    sgml: object = None  # FilingSGML for lazy attachment loading
    filing: object = None  # EntityFiling reference
    navigated: bool = False  # True after first read (skip nav header on re-reads)


class FilingCache:
    """OrderedDict-based LRU cache for parsed filings."""

    def __init__(self, max_size: int = 20):
        self._cache: OrderedDict[str, ParsedFiling] = OrderedDict()
        self._max_size = max_size
        # Maps accession numbers to EntityFiling objects from get_filings calls
        self.accession_to_filing: dict[str, object] = {}

    def get(self, accession_number: str) -> Optional[ParsedFiling]:
        if accession_number in self._cache:
            self._cache.move_to_end(accession_number)
            return self._cache[accession_number]
        return None

    def put(self, parsed: ParsedFiling) -> None:
        if parsed.accession_number in self._cache:
            self._cache.move_to_end(parsed.accession_number)
        self._cache[parsed.accession_number] = parsed
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

    def store_filing_ref(self, accession_number: str, filing) -> None:
        """Store an EntityFiling reference for later resolution by read_document."""
        self.accession_to_filing[accession_number] = filing

    def get_filing_ref(self, accession_number: str):
        """Get a stored EntityFiling reference."""
        return self.accession_to_filing.get(accession_number)


# Global singleton
cache = FilingCache()
