"""SOLUSDEV-317 — the server's mirror of the cloud CommandPolicy deny table
(docs/api/code-command-execution.md §4): shells, wrappers, elevation, inline
code and git config injection are refused; ordinary argv is not."""

import pytest

from code_paths import overlay_module  # isort: skip

deny = overlay_module("command_deny")


def test_tables_are_plain_frozen_literals_matching_the_spec() -> None:
    assert deny.SHELLS == frozenset(
        {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "pwsh"}
    )
    assert deny.WRAPPERS == frozenset(
        {
            "env",
            "xargs",
            "nohup",
            "setsid",
            "nice",
            "timeout",
            "time",
            "watch",
            "script",
            "expect",
            "sandbox-exec",
            "launchctl",
            "open",
            "osascript",
        }
    )
    assert deny.ELEVATION == frozenset({"sudo", "su", "doas", "pkexec"})
    assert dict(deny.INLINE_CODE) == {
        "python": frozenset({"-c"}),
        "node": frozenset({"-e", "--eval", "-p", "--print"}),
        "ruby": frozenset({"-e"}),
        "perl": frozenset({"-e", "-E"}),
        "php": frozenset({"-r"}),
        "lua": frozenset({"-e"}),
        "deno": frozenset({"eval"}),
        "bun": frozenset({"-e", "--eval"}),
        "Rscript": frozenset({"-e"}),
    }
    assert deny.GIT_CONFIG_FLAGS == frozenset({"-c", "--config-env"})
    with pytest.raises(TypeError):
        deny.INLINE_CODE["python"] = frozenset()


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-lc", "ls"],
        ["/bin/sh", "x.sh"],
        ["ZSH"],
        ["pwsh"],
        ["env", "FOO=1", "make"],
        ["/usr/bin/xargs", "rm"],
        ["sandbox-exec", "-p", "x"],
        ["open", "-a", "Terminal"],
        ["sudo", "make", "install"],
        ["doas", "ls"],
        ["python", "-c", "print(1)"],
        ["python3.12", "-c", "print(1)"],
        ["/usr/bin/python3", "-Bc", "print(1)"],
        ["python", "-cprint(1)"],
        ["python", "-W", "ignore", "-c", "x"],
        ["node", "-e", "1"],
        ["node", "--eval=1"],
        ["node", "-r", "mod", "--print", "1"],
        ["ruby", "-e", "1"],
        ["perl", "-le", "print 1"],
        ["perl", "-E", "say 1"],
        ["php", "-r", "echo 1;"],
        ["lua5.4", "-e", "x"],
        ["deno", "eval", "1"],
        ["bun", "--eval", "1"],
        ["Rscript", "-e", "1"],
        ["git", "-c", "core.hooksPath=/x", "status"],
        ["git", "--config-env=core.pager=X", "log"],
        ["git", "-C", "sub", "-c", "x=y", "log"],
    ],
)
def test_denied_argv(argv: list[str]) -> None:
    reason = deny.denied_reason(argv)
    assert reason is not None and "no shell" in reason


@pytest.mark.parametrize(
    "argv",
    [
        ["colcon", "build", "--symlink-install"],
        ["python", "script.py", "-c", "conf"],
        ["python", "-m", "pytest", "-c", "pytest.ini"],
        ["python", "-Wignore", "x.py"],
        ["node", "server.js", "-e"],
        ["deno", "run", "eval.ts"],
        ["git", "commit", "-c", "HEAD"],
        ["git", "-C", "sub", "status"],
        ["make", "-j4"],
        ["./scripts/build.sh"],
        ["python", "--", "-c"],
        ["environment-tool"],
        ["bashful"],
    ],
)
def test_allowed_argv(argv: list[str]) -> None:
    assert deny.denied_reason(argv) is None


@pytest.mark.parametrize(
    ("path", "name"),
    [
        ("/usr/bin/python3.12", "python"),
        ("python3", "python"),
        ("node18", "node"),
        ("Rscript", "Rscript"),
        ("/opt/x/colcon", "colcon"),
        ("make4", "make4"),
    ],
)
def test_program_name_strips_interpreter_versions_only(path: str, name: str) -> None:
    assert deny.program_name(path) == name


def test_empty_argv_is_denied() -> None:
    assert deny.denied_reason([]) is not None
