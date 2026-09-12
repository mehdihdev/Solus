"""`AllowedTool.files_errors` (SOLUSDEV-252 S5): a Solus-owned allowlist flag that
rides onto the bridge descriptor so a failing machine action is filed into `.solus`
Error logging automatically. Like `requires_confirmation`, it comes ONLY from the
allowlist — never from what a companion advertises."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.bridge.allowlist import AllowedTool, load_allowlist, validate_inventory
from solus_api.bridge.frames import HelloData

YAML = """
server: mock
tools:
  - name: run_command
    requires_confirmation: true
    files_errors: true
    reason: runs a command on your machine
  - name: list_environments
"""


def _hello(tools: list[str]) -> HelloData:
    return HelloData.model_validate(
        {
            "protocol_version": 1,
            "companion_version": "0.1.0",
            "companion_instance_id": "i-1",
            "servers": [
                {
                    "server": "mock",
                    "tools": [
                        {"name": name, "description": "d", "input_schema": {"type": "object"}}
                        for name in tools
                    ],
                }
            ],
        }
    )


def test_files_errors_defaults_false() -> None:
    assert AllowedTool(name="x").files_errors is False


def test_files_errors_is_copied_onto_the_descriptor(tmp_path: Path) -> None:
    (tmp_path / "mock").mkdir()
    (tmp_path / "mock" / "allowlist.yaml").write_text(YAML)
    specs = validate_inventory(
        _hello(["run_command", "list_environments"]), load_allowlist(tmp_path)
    )
    by_name: dict[str, Any] = {s.descriptor.name: s.descriptor for s in specs}
    assert by_name["mock.run_command"].files_errors is True
    assert by_name["mock.run_command"].requires_confirmation is True
    assert by_name["mock.list_environments"].files_errors is False


# --- `supports_dry_run`: Solus-owned, per tool --------------------------------

DRY_RUN_YAML = """
server: machine
tools:
  - name: run_command
    requires_confirmation: true
    reason: runs a command on your machine
  - name: read_file
    requires_confirmation: true
    reason: reads one file from your machine
"""

FORGED_YAML = """
server: mock
tools:
  - name: run_command
    requires_confirmation: true
    supports_dry_run: true
    reason: runs a command on your machine
"""


def _write(root: Path, server: str, body: str) -> Path:
    (root / server).mkdir()
    (root / server / "allowlist.yaml").write_text(body)
    return root


def test_supports_dry_run_defaults_false_and_is_set_per_tool(tmp_path: Path) -> None:
    loaded = load_allowlist(_write(tmp_path, "machine", DRY_RUN_YAML))
    run = loaded.get("machine", "run_command")
    read = loaded.get("machine", "read_file")
    assert run is not None and run.supports_dry_run is True
    assert read is not None and read.supports_dry_run is False  # advertises no dry_run
    assert AllowedTool(name="x").supports_dry_run is False


def test_an_allowlist_file_cannot_opt_a_tool_into_dry_run(tmp_path: Path) -> None:
    # The flag says what the FORK accepts, so it is ours, not the yaml's: a
    # tool must never be called with an argument it does not advertise.
    entry = load_allowlist(_write(tmp_path, "mock", FORGED_YAML)).get("mock", "run_command")
    assert entry is not None and entry.supports_dry_run is False


def test_launched_by_defaults_to_companion_and_accepts_the_declared_owners() -> None:
    """The field exists on the cloud model because both readers are
    extra="forbid": an allowlist declaring it would otherwise fail to load and
    the whole server would register with ZERO tools, silently."""
    from solus_api.bridge.allowlist import ServerAllowlist

    assert ServerAllowlist(server="k").launched_by == "companion"
    for owner in ("companion", "cloud", "builtin"):
        assert ServerAllowlist(server="k", launched_by=owner).launched_by == owner
    with pytest.raises(ValidationError):
        # Deliberately invalid: the assertion IS that pydantic refuses it.
        ServerAllowlist(server="k", launched_by="somebody-else")  # type: ignore[arg-type]


def test_the_shipped_allowlists_declare_who_launches_them() -> None:
    """brave is spawned by the API (it needs Node); machine is implemented inside
    the companion. Both must say so, or a companion tries to launch them."""
    import yaml

    root = Path(__file__).resolve().parents[3] / "integrations" / "mcp"
    declared = {
        path.parent.name: yaml.safe_load(path.read_text()).get("launched_by", "companion")
        for path in sorted(root.glob("*/allowlist.yaml"))
    }
    assert declared["brave"] == "cloud"
    assert declared["machine"] == "builtin"
    assert declared["kicad"] == "companion"
