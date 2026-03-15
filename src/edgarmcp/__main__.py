"""Entry point for python -m edgarmcp."""

import argparse
import asyncio
import os
import sys

import edgar

from .server import mcp


def main():
    identity = os.environ.get("EDGAR_IDENTITY")
    if not identity:
        print("ERROR: Set EDGAR_IDENTITY env var (e.g. 'Your Name your@email.com')", file=sys.stderr)
        sys.exit(1)

    edgar.set_identity(identity)

    parser = argparse.ArgumentParser(description="edgarmcp — SEC EDGAR MCP server")
    parser.add_argument("--http", action="store_true", help="Use Streamable HTTP transport")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost only)")
    parser.add_argument("--no-citations", action="store_true", help="Disable citation tags and HTML server")
    parser.add_argument("--citation-port", type=int, default=19823, help="Port for citation HTML server (default: 19823)")
    args = parser.parse_args()

    # Configure citations
    from .citations import registry
    if args.no_citations:
        registry.enabled = False
    else:
        registry.port = args.citation_port

    # Start citation HTML server if enabled
    if registry.enabled:
        _start_citation_server(args.citation_port)

    if args.http:
        if args.host == "0.0.0.0":
            print("WARNING: Binding to 0.0.0.0 exposes MCP server publicly WITHOUT authentication.", file=sys.stderr)
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio")


def _start_citation_server(port: int):
    """Start the citation HTML server in a background thread."""
    import threading
    from .html_server import create_app
    from aiohttp import web

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = create_app()
        runner = web.AppRunner(app, max_field_size=65536, max_line_size=65536)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, "127.0.0.1", port)
        try:
            loop.run_until_complete(site.start())
            print(f"Citation server: http://localhost:{port}", file=sys.stderr)
            loop.run_forever()
        except OSError as e:
            print(f"Warning: Could not start citation server on port {port}: {e}", file=sys.stderr)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()


if __name__ == "__main__":
    main()
