"""SOLUSDEV-317 — the dependency-free Landlock helper (docs/api/code-command-execution.md §3):
write rights of the best ABI are handled, the writable set gets PATH_BENEATH grants,
NO_NEW_PRIVS precedes restriction, and any failure refuses to exec (fail closed)."""

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from code_paths import SOLUS_DIR, overlay_module  # isort: skip

landlock = overlay_module("landlock_exec")

WRITE_V1 = (
    landlock.WRITE_FILE
    | landlock.REMOVE_DIR
    | landlock.REMOVE_FILE
    | landlock.MAKE_CHAR
    | landlock.MAKE_DIR
    | landlock.MAKE_REG
    | landlock.MAKE_SOCK
    | landlock.MAKE_FIFO
    | landlock.MAKE_BLOCK
    | landlock.MAKE_SYM
)


class FakeSyscalls:
    def __init__(self, abi: int = 3, fail: str | None = None) -> None:
        self.version = abi
        self.fail = fail
        self.calls: list[tuple[Any, ...]] = []

    def abi(self) -> int:
        return self.version

    def no_new_privs(self) -> None:
        self.calls.append(("no_new_privs",))

    def create_ruleset(self, handled: int, scoped: int) -> int:
        self.calls.append(("create", handled, scoped))
        if self.fail == "create":
            raise OSError("ENOSYS")
        return 77

    def add_rule(self, ruleset_fd: int, allowed: int, parent_fd: int) -> None:
        self.calls.append(("add", ruleset_fd, allowed))

    def restrict_self(self, ruleset_fd: int) -> None:
        self.calls.append(("restrict", ruleset_fd))


def test_rights_bits_match_the_kernel_uapi() -> None:
    assert landlock.WRITE_FILE == 1 << 1 and landlock.MAKE_SYM == 1 << 12
    assert landlock.REFER == 1 << 13 and landlock.TRUNCATE == 1 << 14
    assert (landlock.SYS_CREATE_RULESET, landlock.SYS_ADD_RULE, landlock.SYS_RESTRICT_SELF) == (
        444,
        445,
        446,
    )


@pytest.mark.parametrize(
    ("abi", "extra"),
    [(1, 0), (2, 1 << 13), (3, (1 << 13) | (1 << 14)), (6, (1 << 13) | (1 << 14))],
)
def test_handled_write_rights_follow_the_best_abi(abi: int, extra: int) -> None:
    assert landlock.handled_access(abi) == WRITE_V1 | extra
    assert not landlock.handled_access(abi) & (1 << 0 | 1 << 2 | 1 << 3)  # exec/read stay open


def test_restrict_grants_directories_and_files_then_restricts(tmp_path: Path) -> None:
    fake = FakeSyscalls(abi=3)
    directory = tmp_path / "ws"
    directory.mkdir()
    device = tmp_path / "null"
    device.write_text("")
    landlock.Landlock(fake).restrict([str(directory), str(device), str(tmp_path / "missing")])
    assert fake.calls[0] == ("no_new_privs",)
    assert fake.calls[1] == ("create", landlock.handled_access(3), 0)
    assert fake.calls[2] == ("add", 77, landlock.handled_access(3))
    assert fake.calls[3] == ("add", 77, landlock.WRITE_FILE | landlock.TRUNCATE)
    assert fake.calls[-1] == ("restrict", 77) and len(fake.calls) == 5


def test_restrict_refuses_without_landlock() -> None:
    with pytest.raises(OSError, match="landlock"):
        landlock.Landlock(FakeSyscalls(abi=0)).restrict(["/"])


def test_main_execs_the_program_only_after_restriction(tmp_path: Path) -> None:
    fake = FakeSyscalls()
    execs: list[tuple[str, list[str], dict[str, str]]] = []
    read, write = os.pipe()
    os.write(write, b"PATH=/opt/ros/bin:/usr/bin\0ROS_DISTRO=jazzy\0EMPTY=\0")
    os.close(write)
    code = landlock.main(
        ["--env-fd", str(read), "--rw", str(tmp_path), "--", "/bin/echo", "hi"],
        landlock=landlock.Landlock(fake),
        execve=lambda program, argv, env: execs.append((program, list(argv), dict(env))),
    )
    assert code == 0
    assert execs == [
        (
            "/bin/echo",
            ["/bin/echo", "hi"],
            {"PATH": "/opt/ros/bin:/usr/bin", "ROS_DISTRO": "jazzy", "EMPTY": ""},
        )
    ]
    with pytest.raises(OSError):
        os.fstat(read)  # the helper closed the env descriptor
    assert ("restrict", 77) in fake.calls


def _feed(write: int, payload: bytes) -> None:
    try:
        os.write(write, payload)
    except OSError:
        pass  # the helper stopped reading at its cap
    finally:
        os.close(write)


@pytest.mark.parametrize("payload", [b"A=" + b"x" * (1024 * 1024 + 1), b"no-equals-sign\0"])
def test_main_refuses_an_oversized_or_malformed_environment(tmp_path: Path, payload: bytes) -> None:
    assert landlock.MAX_ENV_BYTES == 1024 * 1024
    read, write = os.pipe()
    writer = threading.Thread(target=_feed, args=(write, payload))
    writer.start()
    execs: list[object] = []
    code = landlock.main(
        ["--env-fd", str(read), "--rw", str(tmp_path), "--", "/bin/true"],
        landlock=landlock.Landlock(FakeSyscalls()),
        execve=lambda *args: execs.append(args),
    )
    writer.join()
    assert code == 126 and execs == []


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--rw", "/tmp"],
        ["--rw", "/tmp", "--"],
        ["--", "relative"],
        ["--bogus", "--", "/x"],
        ["--env-fd", "x", "--", "/x"],
    ],
)
def test_main_refuses_malformed_arguments(argv: list[str]) -> None:
    execs: list[object] = []
    code = landlock.main(
        argv, landlock=landlock.Landlock(FakeSyscalls()), execve=lambda *a: execs.append(a)
    )
    assert code == 2 and execs == []


def test_main_fails_closed_when_restriction_fails(tmp_path: Path) -> None:
    execs: list[object] = []
    code = landlock.main(
        ["--rw", str(tmp_path), "--", "/bin/true"],
        landlock=landlock.Landlock(FakeSyscalls(fail="create")),
        execve=lambda *args: execs.append(args),
    )
    assert code == 126 and execs == []


def _landlock_works() -> bool:
    if not str(sys.platform).startswith("linux"):
        return False
    try:
        return bool(landlock.Landlock().abi() >= 1)
    except OSError:
        return False


@pytest.mark.skipif(not _landlock_works(), reason="needs Linux with Landlock")
def test_real_landlock_confines_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    other = tmp_path / "other"
    workspace.mkdir()
    other.mkdir()
    script = f"echo ok > {workspace}/inside; echo no > {other}/outside; exit 0"
    read, write = os.pipe()
    os.write(write, b"PATH=/usr/bin:/bin\0")
    os.close(write)
    subprocess.run(
        [sys.executable, "-I", str(SOLUS_DIR / "landlock_exec.py"), "--env-fd", str(read)]
        + ["--rw", str(workspace), "--", "/bin/sh", "-c", script],
        check=True,
        env={"PATH": "/usr/bin:/bin"},
        pass_fds=(read,),
    )
    os.close(read)
    assert (workspace / "inside").read_text() == "ok\n"
    assert not (other / "outside").exists()
    assert os.access(other, os.R_OK)


def test_abi_six_scopes_abstract_sockets_and_signals_but_not_network(tmp_path: Path) -> None:
    fake = FakeSyscalls(abi=6)
    landlock.Landlock(fake).restrict([str(tmp_path)])
    create = next(call for call in fake.calls if call[0] == "create")
    assert create[2] == landlock.SCOPE_ABSTRACT_UNIX_SOCKET | landlock.SCOPE_SIGNAL
    assert (landlock.SCOPE_ABSTRACT_UNIX_SOCKET, landlock.SCOPE_SIGNAL) == (1, 2)
    for abi in (1, 4, 5):
        older = FakeSyscalls(abi=abi)
        landlock.Landlock(older).restrict([str(tmp_path)])
        assert next(call for call in older.calls if call[0] == "create")[2] == 0
