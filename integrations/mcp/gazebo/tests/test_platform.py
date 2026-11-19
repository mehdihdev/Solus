"""Solus-authored OS restriction for the gazebo fork (SOLUSDEV-329): platform.json
parses with the companion's own reader and names exactly the hosts it runs on."""

from __future__ import annotations

from pathlib import Path

import pytest
from solus_companion.platforms import PlatformMetadata, unavailable_reason

FORK = Path(__file__).resolve().parents[1]
MCP_ROOT = FORK.parent


def test_platform_json_is_valid_and_names_linux_and_macos() -> None:
    metadata = PlatformMetadata.model_validate_json((FORK / "platform.json").read_bytes())
    assert metadata.display_name == "Gazebo"
    assert metadata.supported_platforms == ["linux", "darwin"]


@pytest.mark.parametrize(
    ("platform", "reason"),
    [("linux", None), ("darwin", None), ("win32", "Gazebo is not available on Windows")],
)
def test_unavailable_reason_per_host(platform: str, reason: str | None) -> None:
    assert unavailable_reason(MCP_ROOT.resolve(), FORK, platform) == reason
