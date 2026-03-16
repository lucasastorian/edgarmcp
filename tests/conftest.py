"""Shared fixtures for edgarmcp tests."""

from dataclasses import dataclass, field
from typing import Optional

import pytest

from edgarmcp.cache import ParsedFiling, AttachmentMeta, NoteMeta
from edgarmcp.sections import SectionInfo


# Minimal stand-in for sec2md Page/Element objects (no sec2md import needed)
@dataclass
class FakeElement:
    id: str
    content: str


@dataclass
class FakePage:
    number: int
    content: str
    elements: list = field(default_factory=list)
    tags: set = field(default_factory=set)


def make_pages(n: int, content_prefix: str = "Page content") -> list[FakePage]:
    """Create N fake pages with sequential numbering."""
    return [
        FakePage(
            number=i + 1,
            content=f"{content_prefix} {i + 1}",
            elements=[FakeElement(id=f"el-{i + 1}-1", content=f"{content_prefix} {i + 1}")],
        )
        for i in range(n)
    ]


@pytest.fixture
def sample_pages():
    return make_pages(10)


@pytest.fixture
def sample_parsed_filing(sample_pages) -> ParsedFiling:
    return ParsedFiling(
        accession_number="0000320193-24-000081",
        form="10-K",
        filing_date="2024-11-01",
        report_date="2024-09-28",
        company_symbol="AAPL",
        company_name="Apple Inc.",
        cik="320193",
        pages=sample_pages,
        sections=[
            SectionInfo(type="risk_factors", label="Risk Factors", start_page=3, end_page=5),
            SectionInfo(type="mda", label="Management's Discussion and Analysis", start_page=6, end_page=8),
        ],
        notes=[
            NoteMeta(name="note_1", title="Summary of Significant Accounting Policies", start_page=1, end_page=2),
            NoteMeta(name="note_2", title="Revenue Recognition", start_page=3, end_page=4),
        ],
        attachments=[
            AttachmentMeta(
                exhibit_number="99.1",
                document_type="EX-99.1",
                description="Press Release",
                attachment_type="press_release",
                filename="ex99-1.htm",
            ),
            AttachmentMeta(
                exhibit_number="10.1",
                document_type="EX-10.1",
                description="Employment Agreement",
                attachment_type="material_contract",
                filename="ex10-1.htm",
            ),
        ],
    )
