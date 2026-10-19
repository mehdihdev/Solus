"""Fail-closed git argument policy (SOLUSDEV-317 §4, security review rounds 1–2).

Global options before the verb must be known; configuration/program injection
(`-c`, `--config-env`, `--exec-path`) is denied. Verbs that run an arbitrary
program from their arguments are denied too: `--upload-pack`/`--receive-pack`,
`-u` on clone/fetch/ls-remote/archive, `--exec` on push/archive/rebase,
`rebase -x`, `difftool -x/--extcmd`, `bisect run`, `submodule foreach`,
`filter-branch`. Defence in depth behind the approval card and the sandbox.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

#: Git global options before the subcommand (security review: fail closed).
GIT_CONFIG_FLAGS: Final = frozenset({"-c", "--config-env"})
_GIT_DENIED_PREFIXES: Final = ("-c", "--config-env", "--exec-path")
_GIT_VALUE_OPTIONS: Final = frozenset({"-C", "--git-dir", "--work-tree", "--namespace"})
_GIT_SAFE_FLAGS: Final = frozenset(
    {
        "--no-pager",
        "-P",
        "-p",
        "--paginate",
        "--bare",
        "--version",
        "--help",
        "-h",
        "--no-replace-objects",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
        "--no-optional-locks",
        "--no-advice",
    }
)


_PACK_PROGRAMS: Final = ("--upload-pack", "--receive-pack")
_U_VERBS: Final = frozenset({"clone", "fetch", "ls-remote", "archive"})
_EXEC_VERBS: Final = frozenset({"push", "archive", "rebase"})


def _flag(arg: str, *names: str) -> bool:
    return any(arg == name or arg.startswith(f"{name}=") for name in names)


def _verb_denial(verb: str, rest: Sequence[str]) -> str | None:
    if verb == "filter-branch":
        return "git filter-branch runs shell filters"
    if any(_flag(arg, *_PACK_PROGRAMS) for arg in rest):
        return "git --upload-pack/--receive-pack names a program to run"
    if verb in _U_VERBS and any(arg.startswith("-u") and not arg.startswith("--") for arg in rest):
        return f"git {verb} -u names a program to run"
    if verb in _EXEC_VERBS and any(_flag(arg, "--exec") for arg in rest):
        return f"git {verb} --exec runs a program"
    if verb == "rebase" and any(arg.startswith("-x") for arg in rest):
        return "git rebase -x runs a shell command"
    if verb == "difftool" and any(arg.startswith("-x") or _flag(arg, "--extcmd") for arg in rest):
        return "git difftool -x/--extcmd runs a program"
    if verb == "bisect" and next((a for a in rest if not a.startswith("-")), None) == "run":
        return "git bisect run runs a program"
    if verb == "submodule" and "foreach" in rest:
        return "git submodule foreach runs a shell command"
    return None


def git_denial(args: Sequence[str]) -> str | None:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return _verb_denial(arg, args[index + 1 :])
        if arg.startswith(_GIT_DENIED_PREFIXES):
            return "git -c / --config-env / --exec-path injects configuration or programs"
        name = arg.partition("=")[0]
        if name in _GIT_VALUE_OPTIONS:
            index += 1 if "=" in arg else 2
        elif arg in _GIT_SAFE_FLAGS:
            index += 1
        else:
            return f"unrecognised git global option {name[:32]}"
    return None
