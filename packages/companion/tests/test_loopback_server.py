"""Loopback MCP servers hosted by the companion — CAD-02 (Fusion).

Autodesk ships its own MCP server, running on the customer's machine at
`127.0.0.1:27182`. Solus does not fork it and does not host it: it connects to
the customer's own licensed Fusion as a local client.

**That is a licensing requirement, not an optimisation.** Autodesk prohibits
hosting or multiplexing a licensed seat, so running Fusion server-side and
exposing it to several users through Solus would breach the EULA. The companion
already satisfies this by construction — it runs on the user's machine — which
is exactly why the transport belongs here and not in the cloud.

The cloud's `MCPTool` speaks streamable-HTTP but cannot reach a customer's
loopback; the companion can, and until now spoke stdio only.

**The security property this file exists for: loopback only.** A companion that
will connect to an arbitrary URL is an SSRF primitive sitting inside the
customer's network, reachable through whatever can influence an allowlist file.
"""

from __future__ import annotations

import logging
import stat
from pathlib import Path

import pytest
from solus_companion.config import discover_servers, is_loopback_url


def _server(root: Path, name: str, url: str | None) -> Path:
    server = root / name
    server.mkdir(parents=True)
    body = f"server: {name}\n"
    if url is not None:
        body += f"url: {url}\n"
    body += "tools: []\n"
    (server / "allowlist.yaml").write_text(body, encoding="utf-8")
    return server


def _with_launcher(server: Path) -> Path:
    (server / "bin").mkdir(parents=True, exist_ok=True)
    launch = server / "bin" / "launch"
    launch.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launch.chmod(launch.stat().st_mode | stat.S_IXUSR)
    return launch


# --------------------------------------------------------- loopback pinning


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:27182/mcp",
        "http://localhost:27182/mcp",
        "http://[::1]:27182/mcp",
        "http://127.5.5.5:9/x",
    ],
)
def test_loopback_urls_are_accepted(url: str) -> None:
    assert is_loopback_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5:27182/mcp",  # private LAN
        "http://192.168.1.10:27182/mcp",
        "http://evil.example.com/mcp",
        "https://evil.example.com/mcp",
        "http://127.0.0.1.evil.com/mcp",  # hostname that merely starts with it
        "file:///etc/passwd",
        "ftp://127.0.0.1/x",
        "not a url",
        "",
    ],
)
def test_everything_else_is_refused(url: str) -> None:
    """A companion that dials arbitrary URLs is an SSRF primitive INSIDE the
    customer's network — the metadata endpoint being the classic target."""
    assert is_loopback_url(url) is False


# ------------------------------------------------------------- discovery


def test_a_url_server_needs_no_launcher(tmp_path: Path) -> None:
    """Fusion is a vendor-run server: there is nothing to vendor, no bin/launch,
    no private env, no PROVENANCE."""
    _server(tmp_path, "fusion", "http://127.0.0.1:27182/mcp")

    (launch,) = discover_servers(tmp_path)

    assert launch.name == "fusion"
    assert launch.url == "http://127.0.0.1:27182/mcp"
    assert launch.command is None


def test_a_non_loopback_url_server_is_refused_entirely(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Refused, not downgraded to stdio — a server we cannot reach safely is not
    a server we half-register."""
    _server(tmp_path, "rogue", "http://169.254.169.254/mcp")

    with caplog.at_level(logging.ERROR, logger="solus.companion.config"):
        servers = discover_servers(tmp_path)

    assert servers == ()
    assert any("loopback" in record.message for record in caplog.records)


def test_a_stdio_server_still_works(tmp_path: Path) -> None:
    """The existing vendored-fork path is untouched."""
    server = _server(tmp_path, "mock", None)
    _with_launcher(server)

    (launch,) = discover_servers(tmp_path)

    assert launch.url is None
    assert launch.command is not None


def test_a_server_with_neither_url_nor_launcher_is_refused(tmp_path: Path) -> None:
    _server(tmp_path, "empty", None)

    assert discover_servers(tmp_path) == ()


def test_a_url_server_ignores_a_stray_launcher(tmp_path: Path) -> None:
    """`url` decides the transport. A directory carrying both is a mistake, and
    silently preferring the launcher would run code the allowlist did not
    describe."""
    server = _server(tmp_path, "fusion", "http://127.0.0.1:27182/mcp")
    _with_launcher(server)

    (launch,) = discover_servers(tmp_path)

    assert launch.url is not None
    assert launch.command is None
