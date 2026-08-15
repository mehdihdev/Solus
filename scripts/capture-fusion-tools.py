#!/usr/bin/env python3
"""Capture Fusion's live tool list — CAD-02.

WHY THIS EXISTS. `integrations/mcp/fusion/allowlist.yaml` ships with `tools: []`
and must stay that way until someone runs this. The Fusion MCP server is closed
source with dynamic tooling, so there is no source to read and no published
schema — the only honest source for tool names is the running server.

Writing names from documentation or memory would be the fabricated-fixture
failure the vendoring rules exist to prevent, and here it is worse than a
missing tool: the allowlist IS the security gate, so a wrong name exposes
nothing while looking configured.

This asserts nothing about what it finds. It connects, calls `tools/list`, and
prints what came back, with provenance, so a human can paste it in and decide
per tool whether it is destructive.

    # In Fusion: Preferences -> General -> API ->
    #   "Fusion MCP Server (Runs locally on this device)"   (free Personal tier)
    python3 scripts/capture-fusion-tools.py
    python3 scripts/capture-fusion-tools.py --url http://127.0.0.1:27182/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import sys
from typing import Any
from urllib.parse import urlparse

DEFAULT_URL = "http://127.0.0.1:27182/mcp"


def _is_loopback(url: str) -> bool:
    """Same rule the companion enforces (`companion/config.py:is_loopback_url`).

    Checked here too because this script is the thing a human runs by hand, and
    a pasted URL is exactly where a non-loopback address would slip in.
    """
    import ipaddress

    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


async def _capture(url: str) -> list[dict[str, Any]]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            return [
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema,
                }
                for tool in listing.tools
            ]


def _as_allowlist(tools: list[dict[str, Any]]) -> str:
    """Render a starting point for `allowlist.yaml`.

    Every entry is emitted `requires_confirmation: true` with a TODO reason.
    That is deliberate: the safe default for an unreviewed tool is "gated", and
    a human downgrading one after reading its description is a decision, whereas
    a human upgrading one they overlooked is an accident. The server's own
    destructiveHint is not consulted — it is untrusted.
    """
    lines = ["tools:"]
    for tool in tools:
        summary = " ".join((tool["description"] or "").split())[:100]
        lines.append(f"  - name: {tool['name']}")
        lines.append("    requires_confirmation: true # REVIEW: set false if this only READS")
        lines.append(
            f"    reason: TODO Solus-authored. Vendor says: {summary or '(no description)'}"
        )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--json", action="store_true", help="raw tools/list, for a fixture")
    args = parser.parse_args()

    if not _is_loopback(args.url):
        print(f"refusing a non-loopback url: {args.url}", file=sys.stderr)
        return 2

    try:
        tools = await _capture(args.url)
    except Exception as exc:  # noqa: BLE001 — a human is reading this
        print(f"could not reach the Fusion MCP server at {args.url}: {exc}", file=sys.stderr)
        print(
            "\nIs Fusion running with Preferences -> General -> API -> "
            "'Fusion MCP Server (Runs locally on this device)' enabled?",
            file=sys.stderr,
        )
        return 1

    stamp = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    if args.json:
        print(json.dumps({"captured_at": stamp, "url": args.url, "tools": tools}, indent=2))
        return 0

    print(f"# Captured {len(tools)} tools from {args.url} at {stamp}")
    print("# Provenance: live tools/list against a running Fusion. Record the Fusion")
    print("# build number alongside this — the tool set is dynamic and versioned.")
    print()
    print(_as_allowlist(tools))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
