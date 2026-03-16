"""Tiny HTTP server for serving annotated filing HTML with citation highlighting."""

import asyncio
import logging
import os
from pathlib import Path

from aiohttp import web

from .citations import registry

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("EDGARMCP_HTML_CACHE", Path.home() / ".edgarmcp" / "html"))

# Hash-based highlight script — reads element IDs from URL fragment,
# highlights them yellow, scrolls to the first one.
# Works with sec2md's data-sec2md-block attributes on annotated HTML.
HIGHLIGHT_SCRIPT = """\
<script id="sec2md-highlight">
(function() {
  function highlight() {
    var hash = location.hash.slice(1);
    if (!hash) return;
    document.querySelectorAll('[data-sec2md-hl]').forEach(function(el) {
      el.style.backgroundColor = '';
      el.removeAttribute('data-sec2md-hl');
    });
    var ids = hash.split(',');
    var first = null;
    ids.forEach(function(id) {
      document.querySelectorAll('[data-sec2md-block="' + id + '"]').forEach(function(el) {
        el.style.backgroundColor = '#FFFF00';
        el.setAttribute('data-sec2md-hl', '1');
        var children = el.querySelectorAll('*');
        for (var i = 0; i < children.length; i++) {
          children[i].style.backgroundColor = '#FFFF00';
          children[i].setAttribute('data-sec2md-hl', '1');
        }
        if (!first) first = el;
      });
    });
    if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  window.addEventListener('hashchange', highlight);
  window.addEventListener('DOMContentLoaded', highlight);
})();
</script>"""


def cache_annotated_html(accession_number: str, html: str) -> Path:
    """Save annotated HTML with highlight script to cache directory.

    Args:
        accession_number: Filing accession number (used as filename).
        html: Annotated HTML from Parser.html() (contains data-sec2md-block attributes).

    Returns:
        Path to the cached HTML file.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Inject highlight script before </body> or append
    lower = html.lower()
    body_end = lower.find("</body>")
    if body_end != -1:
        html = html[:body_end] + HIGHLIGHT_SCRIPT + html[body_end:]
    else:
        html += HIGHLIGHT_SCRIPT

    path = CACHE_DIR / f"{accession_number}.html"
    path.write_text(html, encoding="utf-8")
    return path


async def handle_citation(request: web.Request) -> web.Response:
    """Resolve a citation ID to an HTML filing with element ID anchors."""
    session_id = request.match_info["session_id"]
    citation_id_str = request.match_info["citation_id"]

    if session_id != registry.session_id:
        return web.Response(text="Session expired. Restart the MCP server.", status=410)

    try:
        citation_id = int(citation_id_str)
    except ValueError:
        return web.Response(text="Invalid citation ID.", status=400)

    citation = registry.get(citation_id)
    if not citation:
        return web.Response(text=f"Citation {citation_id} not found.", status=404)

    # Build redirect URL — route attachments to their own cached HTML
    fragment = ",".join(citation.element_ids)
    if citation.source_type == "attachment" and citation.exhibit_number:
        filename = f"{citation.accession_number}_ex_{citation.exhibit_number}"
    else:
        filename = citation.accession_number
    redirect_url = f"/filing/{filename}.html#{fragment}"

    # Client-side redirect (fragment is not sent to server in 302)
    html = f"""<!DOCTYPE html>
<html><head><script>window.location.replace("{redirect_url}");</script></head>
<body>Redirecting to source...</body></html>"""
    return web.Response(text=html, content_type="text/html")


async def handle_filing(request: web.Request) -> web.Response:
    """Serve a cached annotated HTML filing."""
    filename = request.match_info["filename"]
    path = CACHE_DIR / filename
    if not path.exists():
        return web.Response(text=f"Filing HTML not cached: {filename}", status=404)

    html = path.read_text(encoding="utf-8")
    return web.Response(text=html, content_type="text/html")


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/{session_id}/{citation_id}", handle_citation)
    app.router.add_get("/filing/{filename}", handle_filing)
    return app


async def start_server(port: int = 19823) -> asyncio.Task:
    """Start the HTML server in the background. Returns the running task."""
    app = create_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    try:
        await site.start()
        logger.info(f"Citation server running at http://localhost:{port}")
    except OSError as e:
        logger.warning(f"Could not start citation server on port {port}: {e}")
