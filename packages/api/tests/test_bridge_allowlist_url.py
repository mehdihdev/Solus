"""Vendor-run servers in the bridge allowlist — CAD-02.

One assertion carrying its weight: the allowlist model is `extra="forbid"`, so a
field the companion writes and the cloud does not know about does not merely get
ignored — the whole file fails validation, the server is skipped, and it
registers with ZERO tools without anything looking wrong. That is the footgun
documented in the MCP-03 README, reproduced here so it cannot come back.
"""

from __future__ import annotations

from pathlib import Path

from solus_api.bridge.allowlist import ServerAllowlist, load_allowlist


def test_a_url_allowlist_parses_rather_than_silently_dropping_the_server(
    tmp_path: Path,
) -> None:
    server = tmp_path / "fusion"
    server.mkdir()
    (server / "allowlist.yaml").write_text(
        "server: fusion\n"
        "url: http://127.0.0.1:27182/mcp\n"
        "tools:\n"
        "  - name: get_design_info\n"
        "    requires_confirmation: false\n",
        encoding="utf-8",
    )

    allowlist = load_allowlist(tmp_path)

    assert "fusion" in allowlist.servers
    assert allowlist.get("fusion", "get_design_info") is not None


def test_the_url_field_exists_on_the_model() -> None:
    """Guards the footgun directly: without this field the parse above throws
    and `load_allowlist` skips the server with only a log line."""
    assert "url" in ServerAllowlist.model_fields


def test_an_unknown_field_still_fails_loudly() -> None:
    """extra="forbid" is deliberate — this test exists so adding `url` is not
    read as permission to loosen the model."""
    assert ServerAllowlist.model_config["extra"] == "forbid"
