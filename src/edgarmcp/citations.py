"""Session-scoped citation registry for linking search results to source HTML."""

import secrets
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Citation:
    """A citation linking a tool result to source elements in a filing."""
    id: int
    accession_number: str
    element_ids: list[str]
    source_type: str  # "main", "section", "attachment", "note"
    form: str = ""
    filing_date: str = ""
    company_name: str = ""
    company_symbol: str = ""
    section: Optional[str] = None
    exhibit_number: Optional[str] = None
    note_name: Optional[str] = None
    page: Optional[int] = None


class CitationRegistry:
    """Session-scoped registry mapping citation IDs to source metadata.

    One instance per MCP server process. Counter monotonically increases
    across all tool calls in the session.

    Supports two URL modes:
    - Stdio mode: separate citation server at http://localhost:{port}/{session}/{cid}
    - HTTP mode: citations served through main ASGI app at {base_url_override}/cite/{session}/{cid}
    """

    def __init__(self, enabled: bool = True, port: int = 19823):
        self.enabled = enabled
        self.port = port
        self.base_url_override: Optional[str] = None  # Set in HTTP mode
        self.session_id = secrets.token_hex(3)  # 6-char hex
        self._counter = 0
        self._citations: dict[int, Citation] = {}

    MAX_ELEMENT_IDS = 5  # Cap to keep fragment URLs short

    def add(
        self,
        accession_number: str,
        element_ids: list[str],
        source_type: str,
        **kwargs,
    ) -> Optional[int]:
        """Register a citation and return its ID. Returns None if disabled."""
        if not self.enabled or not element_ids:
            return None
        self._counter += 1
        self._citations[self._counter] = Citation(
            id=self._counter,
            accession_number=accession_number,
            element_ids=element_ids[:self.MAX_ELEMENT_IDS],
            source_type=source_type,
            **kwargs,
        )
        return self._counter

    def get(self, citation_id: int) -> Optional[Citation]:
        return self._citations.get(citation_id)

    @property
    def base_url(self) -> str:
        if self.base_url_override:
            return f"{self.base_url_override}/cite/{self.session_id}"
        return f"http://localhost:{self.port}/{self.session_id}"

    def citation_url(self, citation_id: int) -> str:
        return f"{self.base_url}/{citation_id}"

    def format_tag(self, citation_id: Optional[int]) -> str:
        """Format a serial XML tag: <1>, <2>, etc."""
        if citation_id is None:
            return ""
        return f" <{citation_id}>"

    def format_instructions(self) -> str:
        """One-time instructions appended to tool output telling the LLM how to cite."""
        if not self.enabled:
            return ""
        return (
            "\n**Citations:** The numbered tags (e.g. <1>, <2>) mark citable elements. "
            "When referencing information in your response, cite it as a markdown link: "
            f"[N]({self.base_url}/N) where N is the tag number. "
            "The user can click the link to see the highlighted source in the original filing."
        )


# Global singleton — lives for the entire MCP session (stdio process lifetime)
registry = CitationRegistry()
