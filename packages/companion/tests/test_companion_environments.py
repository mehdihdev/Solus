"""I3 owns environments; the native builtin cannot provide a second executor."""

from pathlib import Path

import pytest
from solus_companion.machine.server import MachineServer


@pytest.mark.parametrize(
    "tool",
    ["run_command", "install_package", "create_environment", "list_environments", "env_packages"],
)
async def test_duplicate_environment_tools_are_unavailable(tmp_path: Path, tool: str) -> None:
    result = await MachineServer(tmp_path).call_tool(tool, {})
    assert result.isError is True
    assert not list(tmp_path.iterdir())
