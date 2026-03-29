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

    from .storage import backend
    print(f"Cache: {backend}", file=sys.stderr)

    from .citations import registry
    if args.no_citations:
        registry.enabled = False
    elif args.http:
        base_url = os.environ.get("EDGARMCP_BASE_URL")
        if not base_url:
            host = "localhost" if args.host == "0.0.0.0" else args.host
            base_url = f"http://{host}:{args.port}"
        registry.base_url_override = base_url
        print(f"Citations: {base_url}/cite/...", file=sys.stderr)
    else:
        registry.port = args.citation_port
        _start_citation_server(args.citation_port)

    if args.http:
        _run_http(args)
    else:
        mcp.run(transport="stdio")


def _run_http(args):
    import uvicorn
    from .auth import ApiKeyAuthMiddleware, resolve_api_key

    public = args.host == "0.0.0.0"
    api_key = resolve_api_key(public=public)

    if api_key:
        print(f"Auth: Bearer {api_key}", file=sys.stderr)
    else:
        print("Auth: disabled (localhost only)", file=sys.stderr)

    app = mcp.streamable_http_app()
    app = ApiKeyAuthMiddleware(app, api_key=api_key)

    uvicorn.run(app, host=args.host, port=args.port)


def _start_citation_server(port: int):
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
