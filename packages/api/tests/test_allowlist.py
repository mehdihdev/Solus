"""Unit tests for the bridge allowlist loader + hello-inventory gate (ADR-031)."""

from pathlib import Path
from typing import Any

import pytest
from solus_api.bridge.allowlist import (
    BridgeAllowlist,
    load_allowlist,
    validate_inventory,
)
from solus_api.bridge.frames import HelloData
from solus_api.core.config import Settings

GOOD_YAML = """
server: mock
tools:
  - name: echo
  - name: flash_firmware
    requires_confirmation: true
    reason: writes to the device
"""


def _write_allowlist(root: Path, server: str, body: str) -> None:
    fork = root / server
    fork.mkdir(parents=True)
    (fork / "allowlist.yaml").write_text(body)


def _hello(servers: list[dict[str, Any]]) -> HelloData:
    return HelloData.model_validate(
        {
            "protocol_version": 1,
            "companion_version": "0.1.0",
            "companion_instance_id": "i-1",
            "servers": servers,
        }
    )


def _tool(name: str, **overrides: Any) -> dict[str, Any]:
    tool: dict[str, Any] = {"name": name, "description": "d", "input_schema": {"type": "object"}}
    tool.update(overrides)
    return tool


def test_descriptors_carry_solus_consent_text_not_fork_text(tmp_path: Path) -> None:
    """SOLX-01 SEC-C1/H1: every bridge descriptor's description is
    fork-advertised text — never trusted — and a destructive entry's consent
    sentence is the Solus-authored allowlist `reason`, asserted over the
    PRODUCTION builder rather than a hand-built descriptor."""
    _write_allowlist(tmp_path, "mock", GOOD_YAML)
    hello = _hello([{"server": "mock", "tools": [_tool("echo"), _tool("flash_firmware")]}])
    specs = validate_inventory(hello, load_allowlist(tmp_path))
    by_name = {spec.descriptor.name: spec.descriptor for spec in specs}
    assert set(by_name) == {"mock.echo", "mock.flash_firmware"}
    assert all(d.description_trusted is False for d in by_name.values())
    assert by_name["mock.flash_firmware"].consent_summary == "writes to the device"
    assert by_name["mock.flash_firmware"].requires_confirmation is True


def test_load_allowlist_good_file(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, "mock", GOOD_YAML)
    allowlist = load_allowlist(tmp_path)
    assert allowlist.get("mock", "echo") is not None
    assert allowlist.get("mock", "flash_firmware").requires_confirmation is True  # type: ignore[union-attr]
    assert allowlist.get("mock", "absent") is None


def test_load_allowlist_skips_broken_files(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, "mock", "server: other_name\ntools: []\n")  # dir mismatch
    _write_allowlist(tmp_path, "Bad.Name", "server: Bad.Name\ntools: []\n")  # invalid name
    _write_allowlist(tmp_path, "broken", ":: not yaml ::[")
    _write_allowlist(
        tmp_path,
        "noreason",
        "server: noreason\ntools:\n  - name: rm\n    requires_confirmation: true\n",
    )
    allowlist = load_allowlist(tmp_path)
    assert allowlist.servers.get("mock") is None
    assert allowlist.servers.get("Bad.Name") is None
    assert allowlist.servers.get("broken") is None
    assert allowlist.servers.get("noreason") is None


def test_load_allowlist_empty_root(tmp_path: Path) -> None:
    assert load_allowlist(tmp_path / "missing").servers == {}


def test_validate_inventory_gates_against_allowlist(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, "mock", GOOD_YAML)
    allowlist = load_allowlist(tmp_path)
    hello = _hello(
        [
            {
                "server": "mock",
                "tools": [
                    _tool("echo"),
                    _tool("not_allowlisted"),
                    _tool("bad name!"),
                    _tool("refy", input_schema={"$ref": "#/x"}),
                    _tool("malformed", input_schema={"type": "not-a-real-type"}),
                ],
            },
            {"server": "unknown_server", "tools": [_tool("echo")]},
            {"server": "Invalid.Server", "tools": [_tool("echo")]},
        ]
    )
    specs = validate_inventory(hello, allowlist)
    assert [spec.descriptor.name for spec in specs] == ["mock.echo"]
    assert specs[0].remote_name == "echo"
    assert specs[0].descriptor.requires_confirmation is False


def test_confirmation_flag_comes_only_from_allowlist(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, "mock", GOOD_YAML)
    allowlist = load_allowlist(tmp_path)
    hello = _hello([{"server": "mock", "tools": [_tool("flash_firmware")]}])
    specs = validate_inventory(hello, allowlist)
    assert specs[0].descriptor.requires_confirmation is True


def test_validate_inventory_caps_description(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, "mock", GOOD_YAML)
    allowlist = load_allowlist(tmp_path)
    hello = _hello([{"server": "mock", "tools": [_tool("echo", description="x" * 2000)]}])
    specs = validate_inventory(hello, allowlist)
    assert len(specs[0].descriptor.description) == 500


def test_validate_inventory_empty_allowlist_registers_nothing() -> None:
    hello = _hello([{"server": "mock", "tools": [_tool("echo")]}])
    assert validate_inventory(hello, BridgeAllowlist(servers={})) == ()


def test_duplicate_advertisement_is_dropped_not_fatal(tmp_path: Path) -> None:
    # SEC-M4: a duplicate composed name must not blow up ToolRegistry.register.
    _write_allowlist(tmp_path, "mock", GOOD_YAML)
    allowlist = load_allowlist(tmp_path)
    hello = _hello(
        [
            {"server": "mock", "tools": [_tool("echo"), _tool("echo")]},
            {"server": "mock", "tools": [_tool("echo")]},
        ]
    )
    specs = validate_inventory(hello, allowlist)
    assert [spec.descriptor.name for spec in specs] == ["mock.echo"]


def test_the_default_allowlist_root_is_anchored_not_cwd_relative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default used to be the bare relative `integrations/mcp`, so it only
    resolved when the process happened to start at the repo root — which the
    repo's own `make dev-api` (cd packages/api) does not do, and which the
    container does not do either. It failed silently: an empty allowlist drops
    every advertised tool as "not allowlisted" rather than raising.

    Hermetic: no `.env`, no ambient override, and run from somewhere else
    entirely, since cwd-independence is the whole property.
    """
    monkeypatch.delenv("SOLUS_BRIDGE_ALLOWLIST_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings(_env_file=None, supabase_jwt_secret="x")  # type: ignore[call-arg]
    root = Path(settings.bridge_allowlist_root)

    assert root.is_absolute()
    # The repo's real forks — proves the anchor points somewhere that exists.
    assert load_allowlist(root).servers
