"""API key auth + health endpoint + citation serving for remote MCP deployment."""

import os
import secrets
from pathlib import Path

from starlette.responses import HTMLResponse, JSONResponse, Response

FILING_HTML_DIR = Path(os.environ.get("EDGARMCP_HTML_CACHE", Path.home() / ".edgarmcp" / "html"))


def resolve_api_key(public: bool = False) -> str | None:
    """Return the API key, auto-generating one if binding publicly with no key set."""
    key = os.environ.get("EDGARMCP_API_KEY")
    if key:
        return key
    if public:
        key = secrets.token_hex(32)
        os.environ["EDGARMCP_API_KEY"] = key
        return key
    return None


class ApiKeyAuthMiddleware:
    """ASGI middleware: auth + health + citation routes.

    Public (no auth): /health, /cite/*, /filing/*
    All other routes require Bearer token when api_key is set.
    """

    def __init__(self, app, api_key: str | None = None):
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

        if path == "/health":
            response = JSONResponse({"status": "ok"})
            return await response(scope, receive, send)

        if path.startswith("/cite/"):
            response = _handle_citation(path)
            return await response(scope, receive, send)

        if path.startswith("/filing/"):
            response = _handle_filing(path)
            return await response(scope, receive, send)

        if self.api_key:
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth != f"Bearer {self.api_key}":
                response = JSONResponse(
                    {"error": "Invalid or missing API key"},
                    status_code=401,
                    headers={"WWW-Authenticate": "Bearer"},
                )
                return await response(scope, receive, send)

        return await self.app(scope, receive, send)


def _handle_citation(path: str) -> Response:
    """Resolve citation ID -> redirect to filing HTML with element highlights."""
    from .citations import registry

    parts = path.strip("/").split("/")
    if len(parts) != 3:
        return JSONResponse({"error": "Invalid citation URL"}, status_code=400)

    _, session_id, citation_id_str = parts

    if session_id != registry.session_id:
        return HTMLResponse("Session expired. Restart the MCP server.", status_code=410)

    try:
        citation_id = int(citation_id_str)
    except ValueError:
        return JSONResponse({"error": "Invalid citation ID"}, status_code=400)

    citation = registry.get(citation_id)
    if not citation:
        return JSONResponse({"error": f"Citation {citation_id} not found"}, status_code=404)

    fragment = ",".join(citation.element_ids)
    if citation.source_type == "attachment" and citation.exhibit_number:
        filename = f"{citation.accession_number}_ex_{citation.exhibit_number}"
    else:
        filename = citation.accession_number

    redirect_url = f"/filing/{filename}.html#{fragment}"
    html = (
        f'<!DOCTYPE html><html><head>'
        f'<script>window.location.replace("{redirect_url}");</script>'
        f'</head><body>Redirecting to source...</body></html>'
    )
    return HTMLResponse(html)


def _handle_filing(path: str) -> Response:
    """Serve cached annotated filing HTML with highlight script."""
    filename = path[len("/filing/"):]
    if not filename:
        return JSONResponse({"error": "No filename"}, status_code=400)

    filepath = FILING_HTML_DIR / filename

    try:
        filepath.resolve().relative_to(FILING_HTML_DIR.resolve())
    except ValueError:
        return JSONResponse({"error": "Invalid path"}, status_code=400)

    if not filepath.exists() or not filepath.is_file():
        return HTMLResponse(f"Filing HTML not cached: {filename}", status_code=404)

    html = filepath.read_text(encoding="utf-8")
    return HTMLResponse(html)
