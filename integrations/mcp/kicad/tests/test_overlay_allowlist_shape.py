"""SOLUSDEV-100 T1b — allowlist.yaml is the COMPLETE single-file draft: the
read roster plus the T2b write tool, validating against the cloud-side
ServerAllowlist model and surviving the validate_inventory ingress gate."""

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

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line above them.
from test_overlay_support import ALLOWLIST_YAML, FORK, MCP_ROOT  # isort: skip

from solus.roster import READ_ROSTER, WRITE_ROSTER


def _parsed() -> ServerAllowlist:
    return ServerAllowlist.model_validate(yaml.safe_load(ALLOWLIST_YAML.read_text()))


# --- shape: the model accepts the file ------------------------------------------


def test_allowlist_validates_against_the_server_allowlist_model() -> None:
    parsed = _parsed()
    assert parsed.server == "kicad" == FORK.name


def test_allowlist_is_the_complete_draft_in_one_file() -> None:
    """Read roster AND the T2b write tool land together so no later MR ever
    widens an existing allowlist (integrations/mcp/CLAUDE.md rule 2)."""
    names = {tool.name for tool in _parsed().tools}
    assert names == READ_ROSTER | WRITE_ROSTER


def test_read_roster_entries_are_unconfirmed_reads_with_reasons() -> None:
    by_name = {tool.name: tool for tool in _parsed().tools}
    for name in sorted(READ_ROSTER):
        entry = by_name[name]
        assert entry.requires_confirmation is False, f"{name} is a read tool"
        assert entry.reason, f"{name} needs its one-line reviewable reason"


def test_set_symbol_property_is_confirmation_gated_with_a_reason() -> None:
    by_name = {tool.name: tool for tool in _parsed().tools}
    entry = by_name["set_symbol_property"]
    assert entry.requires_confirmation is True
    assert entry.reason is not None and "mutat" in entry.reason.lower()


def test_every_composed_name_fits_the_bound() -> None:
    parsed = _parsed()
    for tool in parsed.tools:
        assert len(parsed.server) + 1 + len(tool.name) <= COMPOSED_NAME_MAX


# --- the real tree loads without a single skipped entry ---------------------------


def test_load_allowlist_accepts_the_kicad_file_without_skips(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR, logger="solus.bridge.allowlist"):
        loaded = load_allowlist(MCP_ROOT)
    assert [record.getMessage() for record in caplog.records] == []
    assert set(loaded.servers["kicad"]) == READ_ROSTER | WRITE_ROSTER


# --- the ingress gate: validate_inventory -----------------------------------------


def _hello(tool_names: list[str]) -> HelloData:
    return HelloData(
        protocol_version=1,
        companion_version="0.0.0-test",
        companion_instance_id="t1b-test",
        servers=(
            HelloServer(
                server="kicad",
                tools=tuple(
                    HelloTool(name=name, input_schema={"type": "object"}) for name in tool_names
                ),
            ),
        ),
    )


def test_validate_inventory_passes_the_read_roster_unconfirmed() -> None:
    allowlist = load_allowlist(MCP_ROOT)
    specs = validate_inventory(_hello(sorted(READ_ROSTER)), allowlist)
    by_remote = {spec.remote_name: spec for spec in specs}
    assert set(by_remote) == READ_ROSTER
    for name, spec in by_remote.items():
        assert spec.server == "kicad"
        assert spec.descriptor.name == f"kicad.{name}"
        assert spec.descriptor.requires_confirmation is False


def test_validate_inventory_flags_set_symbol_property_as_confirmation_gated() -> None:
    allowlist = load_allowlist(MCP_ROOT)
    specs = validate_inventory(_hello(["set_symbol_property"]), allowlist)
    assert len(specs) == 1
    assert specs[0].descriptor.requires_confirmation is True


def test_validate_inventory_drops_tools_outside_the_allowlist() -> None:
    allowlist = load_allowlist(MCP_ROOT)
    specs = validate_inventory(
        _hello([*sorted(READ_ROSTER), "run_drc_check", "open_project", "rm_rf_everything"]),
        allowlist,
    )
    assert {spec.remote_name for spec in specs} == READ_ROSTER
