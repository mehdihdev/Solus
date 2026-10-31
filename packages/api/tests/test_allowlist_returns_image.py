"""SOLUSDEV-321 P5 (R102, R125) — `returns_image` is Solus-owned allowlist data.

A tool that answers with an image (or a PDF to rasterise) is flagged in its fork's `allowlist.yaml`,
never by what a companion advertises. The flag reaches `BridgeToolSpec`, where the runtime keeps
the tool off the model's list and `render_view` consumes its one artifact. The field lands on the
model before any YAML uses it: an unknown key in a server file still rejects the WHOLE file
(`_load_one`), so a typo can never half-load an allowlist.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from solus_api.bridge.allowlist import AllowedTool, load_allowlist, validate_inventory
from solus_api.bridge.frames import HelloData, HelloTool

FLAGGED_YAML = """
server: fake
tools:
  - name: export_view
    returns_image: true
    reason: exports the fake design as one picture for SOL's render
  - name: plain_read
"""

#: The same file with the key misspelled: nothing in it may load.
TYPO_YAML = FLAGGED_YAML.replace("returns_image", "returns_images")


def _write_allowlist(root: Path, body: str) -> None:
    fork = root / "fake"
    fork.mkdir(parents=True)
    (fork / "allowlist.yaml").write_text(body)


def _hello(*names: str) -> HelloData:
    tools: list[dict[str, Any]] = [
        {"name": name, "description": "d", "input_schema": {"type": "object"}} for name in names
    ]
    return HelloData.model_validate(
        {
            "protocol_version": 1,
            "companion_version": "0.1.0",
            "companion_instance_id": "i-1",
            "servers": [{"server": "fake", "tools": tools}],
        }
    )


def test_returns_image_defaults_off_and_reaches_the_spec(tmp_path: Path) -> None:
    _write_allowlist(tmp_path, FLAGGED_YAML)
    allowlist = load_allowlist(tmp_path)

    flagged, plain = allowlist.get("fake", "export_view"), allowlist.get("fake", "plain_read")
    assert flagged is not None and flagged.returns_image is True
    assert plain is not None and plain.returns_image is False
    assert AllowedTool(name="bare").returns_image is False

    specs = validate_inventory(_hello("export_view", "plain_read"), allowlist)
    assert {spec.remote_name: spec.returns_image for spec in specs} == {
        "export_view": True,
        "plain_read": False,
    }


def test_unknown_key_still_rejects_server_file(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _write_allowlist(tmp_path, TYPO_YAML)
    with caplog.at_level(logging.ERROR, logger="solus.bridge.allowlist"):
        allowlist = load_allowlist(tmp_path)

    # Not just the misspelled entry: the whole server, its plain read included.
    assert "fake" not in allowlist.servers
    assert any("is invalid; skipping" in record.getMessage() for record in caplog.records)
    assert validate_inventory(_hello("export_view", "plain_read"), allowlist) == ()


def test_a_companion_cannot_advertise_the_flag() -> None:
    """The flag is Solus's: a hello entry claiming it fails `extra="forbid"` like any other key the
    companion has no say in."""
    with pytest.raises(ValidationError):
        HelloTool.model_validate(
            {"name": "export_view", "input_schema": {"type": "object"}, "returns_image": True}
        )
