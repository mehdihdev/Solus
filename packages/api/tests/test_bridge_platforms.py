"""Catalog metadata cannot grant an unsupported OS availability."""

import json
from pathlib import Path

import pytest
from solus_api.bridge.platforms import platform_fields
from solus_companion.platforms import unavailable_reason


@pytest.fixture(scope="session")
def _schema() -> None:
    """These filesystem-only tests do not use the database."""


@pytest.mark.parametrize(
    "metadata",
    [
        None,
        {},
        [],
        {"display_name": "CAD", "supported_platforms": ["linux"]},
        {"display_name": "CAD", "supported_platforms": ["plan9"]},
        {"display_name": "CAD", "supported_platforms": ["win32"], "unknown": True},
    ],
)
def test_api_and_companion_agree_on_availability(tmp_path: Path, metadata: object) -> None:
    directory = tmp_path / "vendor"
    directory.mkdir()
    if metadata is not None:
        (directory / "platform.json").write_text(json.dumps(metadata))
    fields = platform_fields("vendor", root=tmp_path)
    supported = fields["supported_platforms"]
    assert supported is None or isinstance(supported, list)
    for platform in ["linux", "darwin", "win32"]:
        allowed = supported is None or platform in supported
        assert (unavailable_reason(tmp_path, directory, platform) is None) == allowed


@pytest.mark.parametrize("content", ["{", " " * 4097])
def test_malformed_or_oversized_metadata_disables_catalog(tmp_path: Path, content: str) -> None:
    directory = tmp_path / "vendor"
    directory.mkdir()
    (directory / "platform.json").write_text(content)
    assert platform_fields("vendor", root=tmp_path)["supported_platforms"] == []


def test_refuses_escaping_metadata_path(tmp_path: Path) -> None:
    root = tmp_path / "root"
    directory = root / "vendor"
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text('{"display_name":"CAD","supported_platforms":["linux"]}')
    (directory / "platform.json").symlink_to(outside)
    assert platform_fields("vendor", root=root)["supported_platforms"] == []


def test_shipped_desktop_tools_have_verified_platforms() -> None:
    expected = {
        "fusion": ["darwin", "win32"],
        "autocad": ["darwin", "win32"],
        "altium": ["win32"],
        "solidworks": ["win32"],
    }
    for server, platforms in expected.items():
        assert platform_fields(server)["supported_platforms"] == platforms
