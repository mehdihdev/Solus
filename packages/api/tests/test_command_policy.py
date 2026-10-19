"""SOLUSDEV-317 cloud CommandPolicy (docs/api/code-command-execution.md §4).

Pure: argv in, verdict out. Denials are defence in depth behind the approval
card and the server's own planner; risks are badges, never denials.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest
from solus_api.agent.command_policy import (
    ELEVATION,
    GIT_CONFIG_FLAGS,
    INLINE_CODE,
    SHELLS,
    WRAPPERS,
    CommandVerdict,
    Risk,
    classify,
    program_name,
)

_DENY_CASES: list[list[str]] = [
    # shells, however argv[0] is spelled
    ["bash", "-c", "echo hi"],
    ["sh", "script.sh"],
    ["/bin/bash"],
    ["/usr/local/bin/zsh", "-l"],
    ["./bash", "-c", "id"],
    ["BASH"],
    ["fish"],
    ["dash"],
    ["ksh"],
    ["csh"],
    ["tcsh"],
    ["pwsh", "-Command", "x"],
    ["bash5"],
    # wrappers that would run another program
    ["env", "bash"],
    ["/usr/bin/env", "python3", "x.py"],
    ["xargs", "rm"],
    ["nohup", "make"],
    ["setsid", "x"],
    ["nice", "-n", "5", "make"],
    ["timeout", "5", "make"],
    ["time", "make"],
    ["watch", "ls"],
    ["script", "-q"],
    ["expect", "x.exp"],
    ["sandbox-exec", "-p", "x", "ls"],
    ["launchctl", "load", "x"],
    ["open", "-a", "Terminal"],
    ["osascript", "-e", "x"],
    # elevation
    ["sudo", "rm", "-rf", "/"],
    ["su", "-"],
    ["doas", "ls"],
    ["pkexec", "ls"],
    # inline code
    ["python", "-c", "print(1)"],
    ["python3", "-c", "print(1)"],
    ["python3.12", "-c", "import os"],
    ["/usr/bin/python3.12", "-Sc", "import os"],
    ["python", "-I", "-c", "x"],
    ["python", "-ic", "x"],
    ["python", "-X", "dev", "-c", "x"],
    ["python", "-W", "ignore", "-c", "x"],
    ["node", "-r", "./x.js", "-e", "1"],
    ["pypy3", "-c", "x"],
    ["node", "-e", "1"],
    ["node", "--eval", "1"],
    ["node", "--eval=1"],
    ["node", "-p", "1"],
    ["node", "--print", "1"],
    ["node", "-pe", "1"],
    ["node20", "-e", "1"],
    ["ruby", "-e", "1"],
    ["ruby", "-ne", "1"],
    ["perl", "-e", "1"],
    ["perl", "-E", "say 1"],
    ["perl", "-lne", "1"],
    ["php", "-r", "echo 1;"],
    ["lua", "-e", "x"],
    ["lua5.4", "-e", "x"],
    ["deno", "eval", "1"],
    ["bun", "-e", "1"],
    ["bun", "--eval", "1"],
    ["Rscript", "-e", "1"],
    ["rscript", "-e", "1"],
    # git config injection (global options only)
    ["git", "-c", "alias.x=!sh", "x"],
    ["git", "-calias.x=!sh", "x"],
    ["git", "--config-env", "core.pager=X", "log"],
    ["git", "--config-env=core.pager=X", "log"],
    ["/usr/bin/git", "-C", "repo", "-c", "core.hooksPath=/tmp", "commit"],
    # malformed
    [],
    [""],
]


@pytest.mark.parametrize("argv", _DENY_CASES, ids=lambda argv: " ".join(argv) or "<empty>")
def test_denied_commands_are_refused_with_a_reason(argv: list[str]) -> None:
    verdict = classify(argv)
    assert verdict.denied is True
    assert verdict.reason


@pytest.mark.parametrize("argv", [None, "bash -c x", ["ls", 3], [b"ls"], ["ls\x00"], ["ls\n"]])
def test_malformed_argv_is_denied(argv: Any) -> None:
    assert classify(argv).denied is True


_ALLOW_CASES: list[list[str]] = [
    ["colcon", "build", "--symlink-install"],
    ["python", "train.py", "-c", "config.yaml"],  # -c after the script is the script's
    ["python", "-m", "pytest", "-c", "pytest.ini"],
    ["python3.12", "-u", "scripts/run.py"],
    ["node", "server.js", "-e", "x"],
    ["node", "--inspect", "app.js"],
    ["ruby", "app.rb"],
    ["perl", "script.pl"],
    ["git", "log", "-c"],  # combined diff, not a global -c
    ["git", "-C", "sub", "status"],
    ["git", "status"],
    ["make", "-j4"],
    ["ros2", "launch", "bringup", "robot.launch.py"],
    ["ls", "-la"],
    ["deno", "run", "main.ts"],
    ["cmake", "--build", "build"],
    ["environment-tool"],  # not "env"
]


@pytest.mark.parametrize("argv", _ALLOW_CASES, ids=lambda argv: " ".join(argv))
def test_ordinary_commands_are_allowed(argv: list[str]) -> None:
    verdict = classify(argv)
    assert verdict == CommandVerdict(denied=False, reason=None, risks=verdict.risks)
    assert verdict.denied is False


@pytest.mark.parametrize(
    ("argv", "risk"),
    [
        (["curl", "-O", "https://x"], Risk.NETWORK),
        (["wget", "https://x"], Risk.NETWORK),
        (["git", "clone", "https://x"], Risk.NETWORK),
        (["git", "pull"], Risk.NETWORK),
        (["pip", "install", "numpy"], Risk.INSTALL),
        (["pip", "install", "numpy"], Risk.NETWORK),
        (["uv", "pip", "install", "x"], Risk.INSTALL),
        (["npm", "install"], Risk.INSTALL),
        (["pnpm", "add", "x"], Risk.INSTALL),
        (["apt-get", "install", "x"], Risk.INSTALL),
        (["brew", "install", "x"], Risk.INSTALL),
        (["rosdep", "install", "--from-paths", "src"], Risk.INSTALL),
        (["rm", "-rf", "build"], Risk.DESTRUCTIVE),
        (["git", "clean", "-fdx"], Risk.DESTRUCTIVE),
        (["git", "reset", "--hard"], Risk.DESTRUCTIVE),
        (["dd", "if=/dev/zero"], Risk.DESTRUCTIVE),
        (["avrdude", "-p", "m328p"], Risk.HARDWARE),
        (["arduino-cli", "upload", "-p", "/dev/ttyACM0"], Risk.HARDWARE),
        (["esptool.py", "write_flash"], Risk.HARDWARE),
        (["cat", "/dev/ttyUSB0"], Risk.HARDWARE),
        (["ssh", "robot@jetson", "ls"], Risk.REMOTE),
        (["scp", "a", "robot@jetson:/tmp"], Risk.REMOTE),
        (["rsync", "-a", "x", "pi:/home"], Risk.REMOTE),
        (["git", "push"], Risk.REMOTE),
        (["make"], Risk.PROJECT_SCRIPTS),
        (["npm", "run", "build"], Risk.PROJECT_SCRIPTS),
        (["pnpm", "run", "dev"], Risk.PROJECT_SCRIPTS),
        (["yarn", "run", "x"], Risk.PROJECT_SCRIPTS),
        (["colcon", "build"], Risk.PROJECT_SCRIPTS),
        (["cmake", "--build", "build"], Risk.PROJECT_SCRIPTS),
        (["./scripts/build.sh"], Risk.PROJECT_SCRIPTS),
        (["tools/flash"], Risk.PROJECT_SCRIPTS),
    ],
)
def test_risks_are_flagged(argv: list[str], risk: Risk) -> None:
    verdict = classify(argv)
    assert verdict.denied is False
    assert risk in verdict.risks


def test_plain_commands_carry_no_risk_and_risks_are_ordered_and_unique() -> None:
    assert classify(["ls", "-la"]).risks == ()
    risks = classify(["pip", "install", "x"]).risks
    assert list(risks) == sorted(set(risks), key=list(Risk).index)


def test_program_name_strips_paths_and_interpreter_versions() -> None:
    assert program_name("/usr/bin/python3.12") == "python"
    assert program_name("python3") == "python"
    assert program_name("./bash") == "bash"
    assert program_name("colcon") == "colcon"
    assert program_name("/opt/ros/jazzy/bin/ros2") == "ros2"


def test_verdict_is_frozen() -> None:
    verdict = classify(["ls"])
    with pytest.raises(AttributeError):
        verdict.denied = True  # type: ignore[misc]


def test_tables_match_the_spec() -> None:
    assert SHELLS == frozenset("sh bash zsh fish dash ksh csh tcsh pwsh".split())
    assert WRAPPERS == frozenset(
        "env xargs nohup setsid nice timeout time watch script expect "
        "sandbox-exec launchctl open osascript".split()
    )
    assert ELEVATION == frozenset({"sudo", "su", "doas", "pkexec"})
    assert set(INLINE_CODE) == {
        "python",
        "node",
        "ruby",
        "perl",
        "php",
        "lua",
        "deno",
        "bun",
        "Rscript",
    }
    assert GIT_CONFIG_FLAGS == frozenset({"-c", "--config-env"})


# ---------------------------------------- cross-check with the server's mirror

_MIRROR = (
    Path(__file__).resolve().parents[3]
    / "integrations"
    / "mcp"
    / "code"
    / "solus"
    / "command_deny.py"
)


def _literal(node: ast.AST) -> Any:
    """`ast.literal_eval` plus `frozenset(...)`/`set(...)`/`tuple(...)` calls."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"frozenset", "set", "tuple", "list"}
    ):
        return frozenset(_literal(node.args[0])) if node.args else frozenset()
    if isinstance(node, ast.Dict):
        return {_literal(k): _literal(v) for k, v in zip(node.keys, node.values, strict=True) if k}
    if isinstance(node, ast.Set | ast.Tuple | ast.List):
        return frozenset(_literal(element) for element in node.elts)
    return ast.literal_eval(node)


def _mirror_tables() -> dict[str, Any]:
    tree = ast.parse(_MIRROR.read_text())
    tables: dict[str, Any] = {}
    for statement in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target, value = statement.targets[0], statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            target, value = statement.target, statement.value
        if isinstance(target, ast.Name) and value is not None:
            try:
                tables[target.id] = _literal(value)
            except (ValueError, TypeError, IndexError):
                continue
    return tables


@pytest.mark.skipif(
    not _MIRROR.exists(),
    reason="server deny table integrations/mcp/code/solus/command_deny.py not merged yet "
    "(SOLUSDEV-317 code-server sub-branch); un-skip at integration",
)
def test_cloud_policy_matches_the_server_deny_table() -> None:
    tables = _mirror_tables()
    assert frozenset(tables["SHELLS"]) == SHELLS
    assert frozenset(tables["WRAPPERS"]) == WRAPPERS
    assert frozenset(tables["ELEVATION"]) == ELEVATION
    inline = {str(k).lower(): frozenset(v) for k, v in tables["INLINE_CODE"].items()}
    assert inline == {k.lower(): frozenset(v) for k, v in INLINE_CODE.items()}
    git = [value for name, value in tables.items() if "GIT" in name.upper()]
    assert any(frozenset(value) == GIT_CONFIG_FLAGS for value in git), git
