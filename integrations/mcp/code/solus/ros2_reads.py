"""`ros2_nodes` / `ros2_topics` — the live ROS 2 graph through a fixed argv (SOLUSDEV-321 P6;
docs/api/code-command-execution.md §12).

Each tool runs ONE fixed argument list through the same planner, sandbox and executor as `exec`:
`ros2 node list --no-daemon --spin-time 2` or `ros2 topic list --no-daemon -t`. `ros2` resolves
only through the captured profile the call names (this server's PATH is `/usr/bin:/bin`), and a
call is ungated only because the fork's own judge (`command_plan.program_scope`, over every
search-path variable of the profile) finds SYSTEM scope: a profile that reaches the linked folder
(a workspace overlay) can load project code, so it is refused here and `code.exec` keeps its
card. `--no-daemon` starts no ROS daemon, and the executor kills the command's process group and
every descendant once the leader exits, so nothing the read starts outlives it. The answer is the
listed names, each checked against the ROS name grammar and bounded; the cloud re-checks them and
only ever raises edges it already holds (`agent/tools/ros_live.py`).
"""

import re
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .command_plan import SYSTEM_SCOPE
from .execute import MAX_TAIL_BYTES, Runner, default_runner, execute_plan, pinned_which
from .plan import Plan, Which, plan_action
from .sandbox import default_home

NODE_ARGV = ("ros2", "node", "list", "--no-daemon", "--spin-time", "2")
TOPIC_ARGV = ("ros2", "topic", "list", "--no-daemon", "-t")
TIMEOUT_SECONDS = 20
MAX_NAMES = 512
MAX_NAME_CHARS = 256
#: A ROS graph name as the cloud keeps one (R3).
ROS_NAME = re.compile(r"^/?[A-Za-z_][A-Za-z0-9_/]*$")
#: One `topic list -t` line: a name, then its message type in brackets.
TOPIC_LINE = re.compile(r"^(\S+) \[([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z_][A-Za-z0-9_]*){1,2})\]$")
NO_ROS = "ros2 not available: capture a ROS profile first"
OVERLAY = "the profile reaches the linked folder (a workspace overlay): use code.exec"
#: rcl logs under `~/.ros/log`, and the sandbox grants a HOME cache only when it exists.
NO_ROS_HOME = (
    "ros2 needs its log directory ~/.ros, which the sandbox lets it write only when it "
    "exists: create it (or run ros2 once on this machine) and ask again"
)


def read_refusal(key: str, reason: str) -> dict[str, Any]:
    return {"ok": False, key: [], "truncated": False, "reason": reason}


def _plan_read(root: Path, argv: Sequence[str], profile: str | None, which: Which) -> Plan | str:
    """The fixed argv's plan, or why it may not run here without a card."""
    if not profile:
        return NO_ROS
    args = {"argv": list(argv), "profile": profile, "timeout_seconds": TIMEOUT_SECONDS}
    plan = plan_action(root, "exec", args, which=which)
    if not plan.ok:
        reason = plan.reason or "refused"
        return NO_ROS if reason.startswith(("program not found", "no profile named")) else reason
    if plan.program_scope != SYSTEM_SCOPE:
        return OVERLAY
    return plan


def _read_lines(
    root: Path, argv: Sequence[str], profile: str | None, runner: Runner, which: Which
) -> tuple[list[str], bool] | str:
    """The command's stdout lines and whether the tail was cut, or why there are none. Only
    the working directory moves (R136, R137): the read runs from a fresh, empty, private
    directory, since a program treats its working directory as its own (Fast DDS loads
    `DEFAULT_FASTRTPS_PROFILES.xml` from it), while resolution, environment, sandbox and the
    scope re-check right before spawn all stay on the linked folder."""
    planned = _plan_read(root, argv, profile, which)
    if isinstance(planned, str):
        return planned
    if not (default_home() / ".ros").is_dir():
        return NO_ROS_HOME
    with tempfile.TemporaryDirectory(prefix="solus-ros2-") as neutral:
        result = execute_plan(root, planned, runner=runner, which=which, cwd=Path(neutral))
    if not result["ok"]:
        return str(result["reason"] or f"ros2 exited {result['exit_code']}")
    text = str(result["stdout_tail"])
    lines, cut = text.splitlines(), len(text.encode()) >= MAX_TAIL_BYTES
    return (lines[1:] if cut else lines), cut  # a cut tail starts inside a name: never answer it


def _valid_name(name: str) -> bool:
    return len(name) <= MAX_NAME_CHARS and ROS_NAME.match(name) is not None


def ros2_nodes(
    root: Path,
    profile: str | None,
    *,
    runner: Runner = default_runner,
    which: Which = pinned_which,
) -> dict[str, Any]:
    """`{ok, nodes, truncated, reason}`: the live node names."""
    read = _read_lines(root, NODE_ARGV, profile, runner, which)
    if isinstance(read, str):
        return read_refusal("nodes", read)
    lines, cut = read
    names = [line.strip() for line in lines if _valid_name(line.strip())]
    truncated = cut or len(names) > MAX_NAMES
    return {"ok": True, "nodes": names[:MAX_NAMES], "truncated": truncated, "reason": None}


def ros2_topics(
    root: Path,
    profile: str | None,
    *,
    runner: Runner = default_runner,
    which: Which = pinned_which,
) -> dict[str, Any]:
    """`{ok, topics: [{name, type}], truncated, reason}`: the live topics and their types."""
    read = _read_lines(root, TOPIC_ARGV, profile, runner, which)
    if isinstance(read, str):
        return read_refusal("topics", read)
    lines, cut = read
    topics = [
        {"name": match.group(1), "type": match.group(2)}
        for line in lines
        if (match := TOPIC_LINE.match(line.strip())) and _valid_name(match.group(1))
    ]
    truncated = cut or len(topics) > MAX_NAMES
    return {"ok": True, "topics": topics[:MAX_NAMES], "truncated": truncated, "reason": None}
