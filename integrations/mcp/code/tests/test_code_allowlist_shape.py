"""SOLUSDEV-250 — `allowlist.yaml` is the complete fourteen-tool draft, validates
against the cloud-side `ServerAllowlist`, survives the ingress gate, gates
exactly the eight acting tools with reasons, and agrees with the roster."""

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

from code_paths import ALLOWLIST_YAML, FORK_DIR, MCP_ROOT, overlay_module  # isort: skip

roster = overlay_module("roster")
EXPECTED_READ = frozenset(
    {"probe_environment", "plan", "git_status", "git_log", "git_diff", "arduino_probe"}
)
EXPECTED_GATED = frozenset(
    {
        "create_environment",
        "install",
        "run",
        "test",
        "git_commit",
        "git_push",
        "arduino_prepare",
        "arduino_compile",
    }
)


def _parsed() -> ServerAllowlist:
    return ServerAllowlist.model_validate(yaml.safe_load(ALLOWLIST_YAML.read_text()))


def test_allowlist_validates_and_names_this_directory() -> None:
    parsed = _parsed()
    assert parsed.server == "code" == FORK_DIR.name
    assert parsed.url is None


def test_roster_is_the_documented_tools() -> None:
    assert roster.READ_TOOLS == EXPECTED_READ
    assert roster.GATED_TOOLS == EXPECTED_GATED
    assert roster.TOOL_ROSTER == EXPECTED_READ | EXPECTED_GATED


def test_allowlist_matches_the_roster_exactly() -> None:
    assert {tool.name for tool in _parsed().tools} == roster.TOOL_ROSTER


def test_read_tools_are_unconfirmed_and_acting_tools_are_gated_with_reasons() -> None:
    by_name = {tool.name: tool for tool in _parsed().tools}
    for name in EXPECTED_READ:
        assert by_name[name].requires_confirmation is False and by_name[name].reason, name
    for name in EXPECTED_GATED:
        assert by_name[name].requires_confirmation is True, name
        assert by_name[name].reason and len(by_name[name].reason or "") > 20, name


def test_every_composed_name_fits_the_bound() -> None:
    parsed = _parsed()
    for tool in parsed.tools:
        assert len(parsed.server) + 1 + len(tool.name) <= COMPOSED_NAME_MAX


def test_load_allowlist_accepts_the_code_file_without_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="solus.bridge.allowlist"):
        loaded = load_allowlist(MCP_ROOT)
    assert [record.getMessage() for record in caplog.records] == []
    assert set(loaded.servers["code"]) == roster.TOOL_ROSTER


def _hello(tool_names: list[str]) -> HelloData:
    return HelloData(
        protocol_version=1,
        companion_version="0.0.0-test",
        companion_instance_id="code-test",
        servers=(
            HelloServer(
                server="code",
                tools=tuple(
                    HelloTool(name=name, input_schema={"type": "object"}) for name in tool_names
                ),
            ),
        ),
    )


def test_validate_inventory_gates_the_acting_tools_and_drops_strangers() -> None:
    allowlist = load_allowlist(MCP_ROOT)
    specs = validate_inventory(_hello([*sorted(roster.TOOL_ROSTER), "shell"]), allowlist)
    by_remote = {spec.remote_name: spec for spec in specs}
    assert set(by_remote) == roster.TOOL_ROSTER
    for name in EXPECTED_GATED:
        assert by_remote[name].descriptor.requires_confirmation is True, name
    for name in EXPECTED_READ:
        assert by_remote[name].descriptor.requires_confirmation is False, name
    assert by_remote["plan"].descriptor.name == "code.plan"
