"""SOLUSDEV-321 P6 — `ros2_nodes` / `ros2_topics` (docs/api/code-command-execution.md §12): ONE
fixed argv each, through the same planner, sandbox and executor as `exec`; `ros2` only through the
captured profile the call names; ungated only when the fork's own judge finds SYSTEM scope (a
workspace overlay is refused with "use code.exec"); `--no-daemon`, and nothing the read starts
outlives it; the answer is grammar-checked, bounded names."""

import os
import time
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip

ros2_reads = overlay_module("ros2_reads")
execute = overlay_module("execute")
profiles = overlay_module("profiles")
server = overlay_module("server")


class Recorder:
    """A runner that records what would run and answers a fixed stdout."""

    def __init__(self, stdout: bytes = b"", code: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.cwds: list[tuple[Path, list[str]]] = []
        self.stdout, self.code = stdout, code

    def __call__(self, argv: list[str], cwd: Path, env: dict[str, str], timeout: int) -> Any:
        self.calls.append(list(argv))
        self.cwds.append((cwd, sorted(os.listdir(cwd))))
        return execute.Outcome(self.code, self.stdout, b"", False)


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "ws").mkdir()
    root = (tmp_path / "ws").resolve()
    (tmp_path / "home" / ".ros").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    empty = tmp_path / "roots"
    empty.mkdir()
    monkeypatch.setattr(execute, "SEARCH_ROOTS", (str(empty),))
    return root


def _fake_ros2(directory: Path, body: str = "#!/bin/sh\n") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    program = directory / "ros2"
    program.write_text(body)
    program.chmod(0o755)
    return program


def _system_profile(ws: Path, bin_dir: Path) -> None:
    variables = {"PATH": f"{bin_dir}:/usr/bin:/bin", "AMENT_PREFIX_PATH": str(bin_dir.parent)}
    profiles.save(ws, "ros", "/opt/ros/jazzy/setup.bash", None, variables)


def test_requires_system_scope_and_no_daemon(ws: Path, tmp_path: Path) -> None:
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    ros2 = _fake_ros2(bin_dir)
    _system_profile(ws, bin_dir)
    overlay = {"PATH": str(bin_dir), "AMENT_PREFIX_PATH": f"{ws / 'install' / 'pkg'}:{bin_dir}"}
    profiles.save(ws, "overlay", str(ws / "install" / "setup.bash"), None, overlay)
    profiles.save(ws, "bare", "/opt/ros/jazzy/setup.bash", None, {"LANG": "C"})
    runner = Recorder(b"/talker\n/robot/listener\nnot a name\n/[REDACTED]\n")

    def nodes(profile: str | None) -> dict[str, Any]:
        result: dict[str, Any] = ros2_reads.ros2_nodes(ws, profile, runner=runner)
        return result

    # no profile, or one that does not put ros2 on its PATH: nothing runs
    for profile in (None, "", "bare", "missing"):
        assert nodes(profile) == {
            "ok": False,
            "nodes": [],
            "truncated": False,
            "reason": ros2_reads.NO_ROS,
        }, profile
    # a workspace overlay can load project code: refused, and code.exec keeps its card. `ros2` is
    # a Python program, so a profile pointing Python's own user site into the folder is one (R136).
    user_site = {"PATH": str(bin_dir), "PYTHONUSERBASE": str(ws / ".local")}
    profiles.save(ws, "usersite", "/opt/ros/jazzy/setup.bash", None, user_site)
    for profile in ("overlay", "usersite"):
        refused = nodes(profile)
        assert refused["ok"] is False and "use code.exec" in refused["reason"], profile
    assert runner.calls == []

    answer = nodes("ros")

    assert answer == {
        "ok": True,
        "nodes": ["/talker", "/robot/listener"],
        "truncated": False,
        "reason": None,
    }
    (argv,) = runner.calls
    assert str(ros2) in argv  # the profile's ros2, never one from the inherited PATH
    assert argv[-5:] == ["node", "list", "--no-daemon", "--spin-time", "2"]
    # it ran from a neutral, empty, private directory: never the linked folder, which a Python
    # program would put on its import path (R136)
    ((cwd, listing),) = runner.cwds
    assert listing == [] and cwd != ws and ws not in cwd.parents
    assert not cwd.exists()  # removed once the read returned
    assert ros2_reads.NODE_ARGV == ("ros2", "node", "list", "--no-daemon", "--spin-time", "2")
    assert ros2_reads.TOPIC_ARGV == ("ros2", "topic", "list", "--no-daemon", "-t")


def test_topics_carry_their_types_and_bad_lines_are_dropped(ws: Path, tmp_path: Path) -> None:
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    _fake_ros2(bin_dir)
    _system_profile(ws, bin_dir)
    runner = Recorder(
        b"/chatter [std_msgs/msg/String]\n/rosout [rcl_interfaces/msg/Log]\n"
        b"/no_type\nnot a topic [x]\n/bad [type; rm -rf /]\n"
    )

    answer = ros2_reads.ros2_topics(ws, "ros", runner=runner)

    assert answer == {
        "ok": True,
        "topics": [
            {"name": "/chatter", "type": "std_msgs/msg/String"},
            {"name": "/rosout", "type": "rcl_interfaces/msg/Log"},
        ],
        "truncated": False,
        "reason": None,
    }
    assert runner.calls[0][-4:] == ["topic", "list", "--no-daemon", "-t"]


def test_the_read_is_judged_on_the_folder_right_before_it_runs(
    ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R137: only the working directory moves. The read hands the executor the linked folder as
    its root, so the scope judgement right before spawn sees a profile entry that has come to
    reach the folder since planning, and refuses."""
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    _fake_ros2(bin_dir)
    (tmp_path / "opt_ros" / "lib").mkdir()
    link = tmp_path / "pylib"
    link.symlink_to(tmp_path / "opt_ros" / "lib")
    variables = {"PATH": f"{bin_dir}:/usr/bin:/bin", "PYTHONPATH": str(link)}
    profiles.save(ws, "ros", "/opt/ros/jazzy/setup.bash", None, variables)
    handed: list[tuple[Path, Path | None]] = []
    real = ros2_reads.execute_plan

    def spy(root: Path, planned: Any, **kwargs: Any) -> Any:
        handed.append((root, kwargs.get("cwd")))
        return real(root, planned, **kwargs)

    monkeypatch.setattr(ros2_reads, "execute_plan", spy)
    assert ros2_reads.ros2_nodes(ws, "ros", runner=Recorder(b"/talker\n"))["nodes"] == ["/talker"]
    ((root, cwd),) = handed
    assert root == ws and cwd is not None and cwd != ws and ws not in cwd.parents

    planned_read = ros2_reads._plan_read

    def flip_after_planning(*args: Any) -> Any:
        planned = planned_read(*args)
        link.unlink()
        link.symlink_to(ws)  # the same PYTHONPATH entry now reaches the folder
        return planned

    monkeypatch.setattr(ros2_reads, "_plan_read", flip_after_planning)
    runner = Recorder(b"/talker\n")
    answer = ros2_reads.ros2_nodes(ws, "ros", runner=runner)
    assert runner.calls == [] and answer["ok"] is False
    assert answer["reason"] == execute.PROGRAM_CHANGED


def test_a_missing_ros_home_is_said_before_anything_runs(ws: Path, tmp_path: Path) -> None:
    """The sandbox lets `ros2` write only an EXISTING `~/.ros` (its log directory); without one
    rcl logging fails and `ros2` exits 1 for no visible reason, so the read says why instead."""
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    _fake_ros2(bin_dir)
    _system_profile(ws, bin_dir)
    (tmp_path / "home" / ".ros").rmdir()
    runner = Recorder(b"/talker\n")
    answer = ros2_reads.ros2_nodes(ws, "ros", runner=runner)
    assert answer["ok"] is False and answer["reason"] == ros2_reads.NO_ROS_HOME
    assert runner.calls == []


def test_a_failing_ros2_answers_no_names(ws: Path, tmp_path: Path) -> None:
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    _fake_ros2(bin_dir)
    _system_profile(ws, bin_dir)
    answer = ros2_reads.ros2_nodes(ws, "ros", runner=Recorder(b"/talker\n", code=1))
    assert answer == {"ok": False, "nodes": [], "truncated": False, "reason": "ros2 exited 1"}


def test_the_names_are_bounded(ws: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    _fake_ros2(bin_dir)
    _system_profile(ws, bin_dir)
    monkeypatch.setattr(ros2_reads, "MAX_NAMES", 2)
    long = "/" + "a" * 300
    runner = Recorder(f"/a\n{long}\n/b\n/c\n".encode())
    answer = ros2_reads.ros2_nodes(ws, "ros", runner=runner)
    assert answer["nodes"] == ["/a", "/b"] and answer["truncated"] is True


def test_a_cut_listings_first_line_is_dropped(ws: Path, tmp_path: Path) -> None:
    """m1: the executor keeps the last 16 KiB, so a cut listing starts inside a name: `/arm/x`
    is the end of `/robot/arm/x`, and would raise another node's edges. It never answers."""
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    _fake_ros2(bin_dir)
    _system_profile(ws, bin_dir)
    tail = b"/arm/x\n" + b"/b\n" * ((execute.MAX_TAIL_BYTES - 7) // 3)
    assert len(tail) == execute.MAX_TAIL_BYTES  # exactly what the executor keeps
    answer = ros2_reads.ros2_nodes(ws, "ros", runner=Recorder(b"/robot" + tail))
    assert "/arm/x" not in answer["nodes"] and answer["nodes"][:1] == ["/b"]
    assert answer["truncated"] is True


def test_the_server_registers_both_reads_unconfirmed_and_never_raises(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(ws))
    assert {"ros2_nodes", "ros2_topics"} <= set(server._TOOLS)
    assert {"ros2_nodes", "ros2_topics"} <= server.STRICT_TOOLS
    assert server.tool_ros2_nodes()["reason"] == ros2_reads.NO_ROS
    monkeypatch.setattr(ros2_reads, "ros2_topics", lambda *a, **k: 1 / 0)
    assert server.tool_ros2_topics(profile="ros") == {
        "ok": False,
        "topics": [],
        "truncated": False,
        "reason": "ros2_topics failed",
    }


def _alive_with(marker: str) -> list[int]:
    found: list[int] = []
    for entry in Path("/proc").iterdir():
        try:
            if entry.name.isdigit() and marker in (entry / "cmdline").read_bytes().decode():
                found.append(int(entry.name))
        except OSError:
            continue
    return found


@pytest.mark.real_sandbox
def test_nothing_the_read_starts_outlives_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `ros2` that leaves a background child behind (a daemon would be one): the executor kills
    the command's group and every descendant once the leader exits."""
    ws = (tmp_path / "ws").resolve()
    ws.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home" / ".ros").mkdir(parents=True)
    marker = f"solus-ros2-daemon-{os.getpid()}-{time.monotonic_ns()}"
    bin_dir = tmp_path / "opt_ros" / "jazzy" / "bin"
    _fake_ros2(bin_dir, f"#!/bin/sh\n(exec -a {marker} sleep 30) &\necho /talker\n")
    _system_profile(ws, bin_dir)

    answer = ros2_reads.ros2_nodes(ws, "ros")

    assert answer["nodes"] == ["/talker"], answer
    deadline = time.monotonic() + 5
    while _alive_with(marker) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _alive_with(marker) == []
