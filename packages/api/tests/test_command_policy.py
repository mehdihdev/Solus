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
    DENIED_PROGRAMS,
    ELEVATION,
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
    ["sh", "-s", "script.sh"],
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
    ["bash5.2"],
    ["python3.12-intel64", "-c", "x"],
    ["perl5.34-thread-multi", "-e", "1"],
    ["php-cgi", "-r", "1"],
    ["gtimeout", "5", "make"],
    ["zsh-5.9"],
    ["bash-5.2", "x.sh"],
    ["php-cgi8.2", "-r", "1"],
    ["sudo-rs", "ls"],
    ["sudo.ws", "ls"],
    ["/usr/bin/env-x", "make"],
    ["env-x", "make"],
    ["/opt/homebrew/bin/gtimeout", "5", "make"],
    ["perl5.36.0-x86_64-linux", "-e", "1"],
    ["python3.12-x86_64", "-c", "x"],
    ["bash+x"],
    ["/usr/bin/zsh_static"],
    ["node", "--inspect=0.0.0.0:9229", "app.js"],
    ["node", "--inspect=[::]:9229", "app.js"],
    ["node", "--inspect=robot.local:9229", "app.js"],
    ["node", "--inspect=localhost", "app.js"],
    ["node", "--inspect-port=0.0.0.0:9229", "app.js"],
    ["node", "-vr", "data:text/javascript,1", "a.js"],
    ["node", "-vrhttps://x.example/a.js", "a.js"],
    ["bun", "-br", "https://x.example/a.js", "a.ts"],
    ["perl", "-wMIO::Socket;system(1)", "x.pl"],
    ["perl", "-wm", "x;y", "x.pl"],
    ["ruby", "-wrhttp://x.example/a", "a.rb"],
    ["ruby", "-wI", "a b", "a.rb"],
    ["genv", "x"],
    ["/usr/bin/git-upload-pack", "."],
    ["git-receive-pack"],
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
    ["make", "-j4"],
    ["ros2", "launch", "bringup", "robot.launch.py"],
    ["ls", "-la"],
    ["deno", "run", "main.ts"],
    ["cmake", "--build", "build"],
    ["environment-tool"],  # not "env"
    ["node", "--inspect=9229", "app.js"],
    ["node", "--inspect=127.0.0.1:9229", "app.js"],
    ["node", "--inspect=localhost:9229", "app.js"],
    ["node", "--inspect=[::1]:9229", "app.js"],
    ["perl", "-wMIO::Socket", "x.pl"],
    ["ruby", "-wrjson", "a.rb"],
    # §9 item 11: prefix matching is version-shaped only
    ["./env_setup.sh"],
    ["./env-check.sh"],
    ["./tools/env-check.sh"],
    ["./time_sync.py"],
    ["./sh_build.sh"],
    ["./nu_test"],
    ["./open_loop"],
    ["./sudo_check"],
    ["./git_report.sh"],
    ["./bashful"],
    ["./timeout-test"],
    ["./envoy"],
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
        (["pip", "install", "numpy"], Risk.INSTALL),
        (["pip", "install", "numpy"], Risk.NETWORK),
        (["uv", "pip", "install", "x"], Risk.INSTALL),
        (["npm", "install"], Risk.INSTALL),
        (["pnpm", "add", "x"], Risk.INSTALL),
        (["apt-get", "install", "x"], Risk.INSTALL),
        (["brew", "install", "x"], Risk.INSTALL),
        (["rosdep", "install", "--from-paths", "src"], Risk.INSTALL),
        (["rm", "-rf", "build"], Risk.DESTRUCTIVE),
        (["dd", "if=/dev/zero"], Risk.DESTRUCTIVE),
        (["avrdude", "-p", "m328p"], Risk.HARDWARE),
        (["arduino-cli", "upload", "-p", "/dev/ttyACM0"], Risk.HARDWARE),
        (["esptool.py", "write_flash"], Risk.HARDWARE),
        (["cat", "/dev/ttyUSB0"], Risk.HARDWARE),
        (["ssh", "robot@jetson", "ls"], Risk.REMOTE),
        (["scp", "a", "robot@jetson:/tmp"], Risk.REMOTE),
        (["rsync", "-a", "x", "pi:/home"], Risk.REMOTE),
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


def test_tables_match_the_spec_and_the_security_review() -> None:
    assert SHELLS == frozenset(
        "sh bash zsh fish dash ksh csh tcsh pwsh busybox "
        "rbash ash mksh yash elvish nu xonsh oksh posh".split()
    )
    assert WRAPPERS == frozenset(
        "env xargs nohup setsid nice timeout time watch script expect "
        "sandbox-exec launchctl open osascript stdbuf flock "
        "ionice taskset caffeinate arch chrt systemd-run setpriv prlimit unbuffer "
        "fakeroot proot firejail cpulimit faketime".split()
    )
    assert ELEVATION == frozenset(
        {"sudo", "su", "doas", "pkexec", "runuser", "chroot", "unshare", "nsenter"}
    )
    assert INLINE_CODE == {
        "python": {"-c"},
        "node": {"-e", "--eval", "-p", "--print"},
        "ruby": {"-e"},
        "perl": {"-e", "-E"},
        "php": {"-r", "-B", "-R", "-E", "-F"},
        "lua": {"-e"},
        "deno": {"eval", "repl"},
        "bun": {"-e", "--eval", "-p", "--print"},
        "Rscript": {"-e"},
    }
    assert DENIED_PROGRAMS == frozenset({"git"})


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
    if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "MappingProxyType":
        return _literal(node.args[0])
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


def test_cloud_policy_matches_the_server_deny_table() -> None:
    assert _MIRROR.is_file(), f"server deny table missing: {_MIRROR}"
    from solus_api.agent.command_interpreters import (
        GRAMMARS,
        PERL_MODULE_PATTERN,
        RUBY_LIBRARY_PATTERN,
    )

    tables = _mirror_tables()
    assert frozenset(tables["SHELLS"]) == SHELLS
    assert frozenset(tables["WRAPPERS"]) == WRAPPERS
    assert frozenset(tables["ELEVATION"]) == ELEVATION
    inline = {str(k).lower(): frozenset(v) for k, v in tables["INLINE_CODE"].items()}
    assert inline == {k.lower(): frozenset(v) for k, v in INLINE_CODE.items()}
    assert frozenset(tables["GIT_PROGRAMS"]) == DENIED_PROGRAMS
    assert frozenset(tables["NODE_LOADER_FLAGS"]) <= GRAMMARS["node"].value_options
    assert frozenset(tables["BUN_LOADER_FLAGS"]) <= GRAMMARS["bun"].value_options
    assert tables["PERL_MODULE_PATTERN"] == PERL_MODULE_PATTERN
    assert tables["RUBY_LIBRARY_PATTERN"] == RUBY_LIBRARY_PATTERN


# ------------------------------------------- behavioural parity (§9 item 11)

#: Shared corpus: every argv here must get the same denied/allowed answer from
#: the cloud `classify` and the server's `classify_denial`.
_PARITY_CORPUS: list[list[str]] = [
    *_DENY_CASES[:-2],  # the malformed pair is a cloud-only input shape
    *_ALLOW_CASES,
    ["python3.13t", "-c", "x"],
    ["pythonw", "-c", "x"],
    ["python3-dbg", "-c", "x"],
    ["nodejs", "-e", "1"],
    ["luajit", "-e", "x"],
    ["pypy3.10", "-c", "x"],
    ["python", "--unknown-flag", "x.py"],
    ["ruby", "--weird", "app.rb"],
    ["node", "--import", "data:text/javascript,1", "x.js"],
    ["node", "--inspect=0.0.0.0:9229", "app.js"],
    ["perl", "-MIO::Socket", "x.pl"],
    ["php", "-d", "auto_prepend_file=x", "a.php"],
    ["bun", "-p", "1"],
    ["deno", "repl"],
    ["sudo", "ls"],
    ["runuser", "-u", "x", "ls"],
    ["chroot", "/", "ls"],
    ["unshare", "-r", "ls"],
    ["nsenter", "-t", "1"],
    ["stdbuf", "-o0", "make"],
    ["systemd-run", "x"],
    ["firejail", "x"],
    ["zsh5.9"],
    ["fish-3"],
    ["./env_setup.sh"],
    ["./env-check.sh"],
    ["zsh-5.9"],
    ["perl5.36.0-x86_64-linux", "x.pl"],
    ["python3.12-x86_64", "-c", "x"],
    ["bash+x"],
    ["node", "--inspect=[::]:9229", "app.js"],
    ["node", "--inspect=localhost:9229", "app.js"],
    ["node", "--inspect=9229", "app.js"],
    ["node", "-vr", "data:text/javascript,1", "a.js"],
    ["perl", "-wMIO::Socket;system(1)", "x.pl"],
    ["ruby", "-wrhttp://x.example/a", "a.rb"],
    ["sudo-rs", "ls"],
    ["env-x"],
    ["./nu_test"],
    ["./sh_build.sh"],
    ["./time_sync.py"],
    ["./open_loop"],
    ["cargo", "build"],
    ["npm", "run", "build"],
    ["rm", "-rf", "build"],
    ["ssh", "robot", "ls"],
    ["pip", "install", "numpy"],
    ["/opt/ros/jazzy/bin/ros2", "topic", "list"],
]


def _server_classifier() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location("_server_command_deny", _MIRROR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.classify_denial


def _server_denied(answer: Any) -> bool:
    denied = getattr(answer, "denied", None)
    return bool(answer) if denied is None else bool(denied)


def test_the_parity_corpus_is_large_enough() -> None:
    assert len(_PARITY_CORPUS) >= 60


def test_cloud_and_server_classifiers_agree_on_the_shared_corpus() -> None:
    classify_denial = _server_classifier()
    disagreements = [
        argv
        for argv in _PARITY_CORPUS
        if classify(argv).denied is not _server_denied(classify_denial(argv))
    ]
    assert disagreements == []


@pytest.mark.parametrize(
    "argv",
    [["../../usr/local/bin/bash-5.2"], ["tools/../../bin/zsh-5.9"], ["./../sudo-rs", "ls"]],
)
def test_a_path_that_climbs_out_is_not_workspace_relative(argv: list[str]) -> None:
    assert classify(argv).denied


# ------------------------------------- §10.2: bash/sh running a workspace script


_SHELL_SCRIPT_ALLOWED: list[list[str]] = [
    ["bash", "scripts/build.sh"],
    ["sh", "script.sh"],
    ["sh", "./setup.sh", "--fast", "-c", "x"],  # options AFTER the script are its own
    ["bash", "tools/flash.bash", "robot"],
    ["/bin/bash", "scripts/build.sh"],
    ["/bin/sh", "scripts/build.sh"],
]

_SHELL_SCRIPT_DENIED: list[list[str]] = [
    ["bash"],
    ["bash", "-c", "scripts/build.sh"],
    ["bash", "-e", "scripts/build.sh"],
    ["bash", "-x", "scripts/build.sh"],
    ["bash", "--rcfile", "x.sh", "scripts/build.sh"],
    ["bash", "--init-file", "x.sh"],
    ["bash", "-o", "errexit", "scripts/build.sh"],
    ["bash", "+o", "posix", "scripts/build.sh"],
    ["bash", "-s", "scripts/build.sh"],
    ["bash", "-i", "scripts/build.sh"],
    ["bash", "-"],
    ["bash", "-.sh"],
    ["bash", "+x.sh"],
    ["bash", "../build.sh"],
    ["bash", "scripts/../../build.sh"],
    ["bash", "/tmp/build.sh"],
    ["bash", "~/build.sh"],
    ["bash", "scripts/build.py"],
    ["bash", "scripts/build.sh.txt"],
    ["zsh", "scripts/build.sh"],
    ["dash", "scripts/build.sh"],
    ["fish", "scripts/build.fish"],
    ["bash5", "scripts/build.sh"],
    ["BASH", "scripts/build.sh"],
    ["bash-5.2", "scripts/build.sh"],
    ["env", "bash", "scripts/build.sh"],
    ["sudo", "bash", "scripts/build.sh"],
]


@pytest.mark.parametrize("argv", _SHELL_SCRIPT_ALLOWED, ids=lambda argv: " ".join(argv))
def test_bash_or_sh_may_run_a_workspace_script_behind_a_card(argv: list[str]) -> None:
    verdict = classify(argv)
    assert verdict.denied is False, verdict.reason
    assert Risk.RUNS_SHELL in verdict.risks
    assert Risk.PROJECT_SCRIPTS in verdict.risks
    assert list(verdict.risks) == sorted(set(verdict.risks), key=list(Risk).index)


@pytest.mark.parametrize("argv", _SHELL_SCRIPT_DENIED, ids=lambda argv: " ".join(argv))
def test_every_other_shell_form_stays_denied(argv: list[str]) -> None:
    assert classify(argv).denied


@pytest.mark.parametrize("argv", _SHELL_SCRIPT_DENIED, ids=lambda argv: " ".join(argv))
def test_the_server_denies_the_other_shell_forms_too(argv: list[str]) -> None:
    assert _server_denied(_server_classifier()(argv))


@pytest.mark.parametrize("argv", _SHELL_SCRIPT_ALLOWED, ids=lambda argv: " ".join(argv))
def test_the_server_allows_the_same_shell_scripts(argv: list[str]) -> None:
    assert not _server_denied(_server_classifier()(argv))


# ---------------- security review 2026-10-19: system programs running project code


@pytest.mark.parametrize(
    "argv",
    [
        ["python3", "train.py"],
        ["python", "-u", "scripts/run.py"],
        ["python3", "-m", "pytest"],
        ["/usr/bin/python3.12", "-m", "http.server"],
        ["node", "app.js"],
        ["ruby", "x.rb"],
        ["perl", "script.pl"],
        ["php", "index.php"],
        ["deno", "run", "main.ts"],
        ["bun", "test"],
        ["lua", "x.lua"],
        ["Rscript", "x.R"],
        ["pytest"],
        ["pytest", "-q", "tests"],
        ["py.test"],
        ["tox"],
        ["nox", "-s", "lint"],
        ["npm", "test"],
        ["npx", "tsc"],
        ["pnpm", "lint"],
        ["yarn"],
        ["cargo", "run"],
        ["cargo", "build"],
        ["go", "test", "./..."],
        ["make"],
        ["gmake", "all"],
        ["ninja"],
        ["cmake", "--build", "build"],
        ["cmake", "-S", ".", "-B", "build"],
        ["cmake", "."],
        ["colcon", "build"],
        ["catkin", "build"],
        ["catkin_make"],
        ["ros2", "run", "pkg", "node"],
        ["ros2", "launch", "pkg", "x.launch.py"],
        ["gradle", "build"],
        ["gradlew", "build"],
        ["mvn", "test"],
        ["rake"],
        ["bundle", "exec", "rspec"],
        ["poetry", "run", "pytest"],
        ["uv", "run", "main.py"],
        ["pipenv", "run", "x"],
        ["hatch", "run", "test"],
        ["pio", "run"],
        ["platformio", "test"],
        # Orchestrator addition 2026-10-19 (2)
        ["pip", "wheel", "."],
        ["pip3", "download", "x"],
        ["uv", "sync"],
        ["uv", "pip", "install", "x"],
        ["uv", "build"],
        ["uv", "tool", "run", "x"],
        ["poetry", "install"],
        ["poetry", "build"],
        ["pdm", "run", "x"],
        ["rye", "sync"],
        ["pixi", "run", "x"],
        ["conda", "run", "-n", "x", "y"],
        ["mamba", "install", "x"],
        ["micromamba", "env", "create"],
        ["rosrun", "pkg", "node"],
        ["roslaunch", "pkg", "x.launch"],
        ["ctest"],
        ["meson", "compile"],
        ["scons"],
        ["bazel", "build", "//..."],
        ["bazelisk", "test", "//..."],
        ["just"],
        ["task", "build"],
        ["invoke", "build"],
        ["pre-commit", "run"],
        # Runners load workspace plugins/toolchains even for version or help.
        ["pytest", "--help"],
        ["pytest", "--version"],
        ["make", "--version"],
        ["cargo", "--version"],
        ["go", "version"],
        ["npm", "--version"],
        ["cmake", "--version"],
        ["ninja", "--version"],
        ["bazelisk", "--version"],
        ["bazel", "--help"],
        ["pre-commit", "--version"],
        ["hatch", "--version"],
    ],
    ids=lambda argv: " ".join(argv),
)
def test_system_programs_running_project_code_are_flagged(argv: list[str]) -> None:
    verdict = classify(argv)
    assert verdict.denied is False, verdict.reason
    assert Risk.PROJECT_SCRIPTS in verdict.risks


@pytest.mark.parametrize(
    "argv",
    [
        ["python3", "--version"],
        ["python3", "-V"],
        ["python", "--help"],
        ["node", "--version"],
        ["ros2", "topic", "list"],
        ["uv", "--version"],
        ["pip", "--version"],
        ["pip", "list"],
        ["conda", "--version"],
        ["conda", "info"],
        ["poetry", "--version"],
        ["bundle", "--version"],
        ["pio", "--version"],
        ["ls", "-la"],
    ],
    ids=lambda argv: " ".join(argv),
)
def test_version_and_help_only_invocations_stay_no_risk(argv: list[str]) -> None:
    verdict = classify(argv)
    assert verdict.denied is False and verdict.risks == ()
