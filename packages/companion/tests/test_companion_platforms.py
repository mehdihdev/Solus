"""OS-incompatible servers are inventory, never failed launch attempts."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from solus_companion.config import discover_servers
from solus_companion.supervisor import ServerUnavailableError, Supervisor


def server(root: Path, metadata: str) -> None:
    directory = root / "vendor"
    directory.mkdir()
    (directory / "allowlist.yaml").write_text("server: vendor\nurl: http://127.0.0.1:1234/mcp\n")
    (directory / "platform.json").write_text(metadata)


async def test_unsupported_has_neutral_status_and_never_dials_or_retries(tmp_path: Path) -> None:
    server(tmp_path, json.dumps({"display_name": "Test CAD", "supported_platforms": ["win32"]}))
    with patch("solus_companion.config.sys.platform", "linux"):
        launches = discover_servers(tmp_path)
    supervisor = Supervisor(launches)
    with patch(
        "solus_companion.supervisor._loopback_transport",
        side_effect=AssertionError("must not dial"),
    ) as dial:
        await supervisor.start_all()
        await supervisor.ensure_healthy()
        await supervisor.handles["vendor"].restart()
        with pytest.raises(ServerUnavailableError):
            await supervisor.call_tool("vendor", "read", {})
        await supervisor.stop_all()
        dial.assert_not_called()
    assert supervisor.inventory() == []
    status = supervisor.status_snapshot()[0]
    assert status["state"] == "not_launched"
    assert status["detail"] == "Test CAD is not available on Linux"
    assert supervisor.handles["vendor"].failures == 0


@pytest.mark.parametrize(
    "metadata",
    [
        "{}",
        "[]",
        "{",
        " " * 4097,
        '{"display_name":"CAD","supported_platforms":["plan9"]}',
        '{"display_name":"CAD","supported_platforms":["linux"],"extra":true}',
    ],
)
def test_invalid_metadata_fails_closed(tmp_path: Path, metadata: str) -> None:
    server(tmp_path, metadata)
    launch = discover_servers(tmp_path)[0]
    assert launch.unavailable_reason == "Platform availability is unavailable"


def test_supported_and_unrestricted_servers_remain_launchable(tmp_path: Path) -> None:
    server(tmp_path, json.dumps({"display_name": "Test CAD", "supported_platforms": ["linux"]}))
    with patch("solus_companion.config.sys.platform", "linux"):
        assert discover_servers(tmp_path)[0].unavailable_reason is None
    (tmp_path / "vendor/platform.json").unlink()
    assert discover_servers(tmp_path)[0].unavailable_reason is None


def test_metadata_symlink_escape_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    server(root, "{}")
    target = tmp_path / "external.json"
    target.write_text('{"display_name":"CAD","supported_platforms":["linux"]}')
    metadata = root / "vendor/platform.json"
    metadata.unlink()
    metadata.symlink_to(target)
    assert discover_servers(root)[0].unavailable_reason == "Platform availability is unavailable"
