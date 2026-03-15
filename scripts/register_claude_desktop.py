#!/usr/bin/env python3
"""Add or update edgarmcp in Claude Desktop MCP config."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def default_claude_config_path() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA is not set. Pass --config explicitly.")
        return Path(appdata) / "Claude/claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"


def load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Config file is not valid JSON: {path}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"Config root must be a JSON object: {path}")
    return data


def register_server(config: dict, server_name: str, repo_root: Path, identity: str) -> dict:
    mcp_servers = config.get("mcpServers")
    if mcp_servers is None:
        mcp_servers = {}
        config["mcpServers"] = mcp_servers
    if not isinstance(mcp_servers, dict):
        raise RuntimeError("Expected `mcpServers` to be a JSON object.")

    mcp_servers[server_name] = {
        "command": "uv",
        "args": ["--directory", str(repo_root), "run", "edgarmcp"],
        "env": {"EDGAR_IDENTITY": identity},
    }
    return config


def main() -> int:
    parser = argparse.ArgumentParser(description="Register edgarmcp in Claude Desktop MCP config.")
    parser.add_argument(
        "--identity",
        help="SEC identity, e.g. 'Jane Doe jane@example.com'. Falls back to EDGAR_IDENTITY.",
    )
    parser.add_argument("--name", default="edgarmcp", help="MCP server name in Claude Desktop config.")
    parser.add_argument("--config", type=Path, help="Path to claude_desktop_config.json.")
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Print resulting JSON to stdout instead of writing the config file.",
    )
    args = parser.parse_args()

    identity = (args.identity or os.environ.get("EDGAR_IDENTITY") or "").strip()
    if not identity:
        print("ERROR: pass --identity or set EDGAR_IDENTITY.", file=sys.stderr)
        return 1

    script_path = Path(__file__).resolve()
    repo_root = script_path.parents[1]
    config_path = args.config or default_claude_config_path()

    try:
        config = load_config(config_path)
        updated = register_server(config, args.name, repo_root, identity)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = json.dumps(updated, indent=2) + "\n"

    if args.print_only:
        print(output, end="")
        return 0

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(output, encoding="utf-8")

    print(f"Updated {config_path}")
    print("Restart Claude Desktop to load the MCP server.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
