"""SOLUSDEV-249 — `allowlist.yaml` is the complete three-tool draft, validates
against the cloud-side `ServerAllowlist` model, survives the ingress gate, and
agrees with the Python roster and what the running server registers."""

import logging

import pytest
import yaml
from solus_api.bridge.allowlist import (
    COMPOSED_NAME_MAX,
    ServerAllowlist,
    load_allowlist,
    validate_inventory,
)
from solus_api.bridge.frames import HelloData, HelloServer, HelloTool

from .local_paths import ALLOWLIST_YAML, FORK_DIR, MCP_ROOT, overlay_module  # isort: skip

TOOL_ROSTER: frozenset[str] = overlay_module("roster").TOOL_ROSTER
EXPECTED_ROSTER = frozenset({"scan_folder", "folder_digest", "open_in_tool"})


def _parsed() -> ServerAllowlist:
    return ServerAllowlist.model_validate(yaml.safe_load(ALLOWLIST_YAML.read_text()))


def test_allowlist_validates_and_names_this_directory() -> None:
    parsed = _parsed()
    assert parsed.server == "local" == FORK_DIR.name
    assert parsed.url is None, "a stdio fork declares no url"


def test_roster_is_the_three_documented_tools() -> None:
    assert TOOL_ROSTER == EXPECTED_ROSTER


def test_allowlist_matches_the_roster_exactly() -> None:
    assert {tool.name for tool in _parsed().tools} == TOOL_ROSTER


def test_read_tools_are_unconfirmed_with_reasons() -> None:
    by_name = {tool.name: tool for tool in _parsed().tools}
    for name in ("scan_folder", "folder_digest"):
        assert by_name[name].requires_confirmation is False, name
        assert by_name[name].reason, name


def test_open_in_tool_is_confirmation_gated_with_a_reason() -> None:
    by_name = {tool.name: tool for tool in _parsed().tools}
    entry = by_name["open_in_tool"]
    assert entry.requires_confirmation is True
    assert entry.reason and "launch" in entry.reason.lower()


def test_every_composed_name_fits_the_bound() -> None:
    parsed = _parsed()
    for tool in parsed.tools:
        assert len(parsed.server) + 1 + len(tool.name) <= COMPOSED_NAME_MAX


def test_load_allowlist_accepts_the_local_file_without_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="solus.bridge.allowlist"):
        loaded = load_allowlist(MCP_ROOT)
    assert [record.getMessage() for record in caplog.records] == []
    assert set(loaded.servers["local"]) == TOOL_ROSTER


def _hello(tool_names: list[str]) -> HelloData:
    return HelloData(
        protocol_version=1,
        companion_version="0.0.0-test",
        companion_instance_id="local-test",
        servers=(
            HelloServer(
                server="local",
                tools=tuple(
                    HelloTool(name=name, input_schema={"type": "object"}) for name in tool_names
                ),
            ),
        ),
    )


def test_validate_inventory_gates_open_in_tool_and_drops_strangers() -> None:
    allowlist = load_allowlist(MCP_ROOT)
    specs = validate_inventory(_hello([*sorted(TOOL_ROSTER), "rm_rf_everything"]), allowlist)
    by_remote = {spec.remote_name: spec for spec in specs}
    assert set(by_remote) == TOOL_ROSTER
    assert by_remote["open_in_tool"].descriptor.requires_confirmation is True
    assert by_remote["scan_folder"].descriptor.requires_confirmation is False
    assert by_remote["scan_folder"].descriptor.name == "local.scan_folder"
