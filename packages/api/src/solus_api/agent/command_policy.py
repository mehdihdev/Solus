"""Cloud-side CommandPolicy for `code.exec` / `code.process_start` (SOLUSDEV-317).

docs/api/code-command-execution.md §4 and the ADR-031 amendment of 2026-10-18.
Pure: `classify(argv)` answers whether a model-proposed argument list is DENIED
(refused before any approval card exists) and which RISK badges the card shows.
Denial is defence in depth — the approval card and the server's own planner
(`integrations/mcp/code/solus/command_deny.py`, cross-checked by a test) still
stand behind it. A risk is never a denial: the person decides.
"""

from __future__ import annotations

import posixpath
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, cast

from solus_api.agent.command_git import GIT_CONFIG_FLAGS, git_denial
from solus_api.agent.command_interpreters import GRAMMARS, INLINE_CODE, interpreter_denial
from solus_api.agent.command_names import INTERPRETERS, normalise, prefix_match
from solus_api.agent.command_risks import Risk, risks_for

#: Mirrored in the server deny table; keep both in lockstep (test cross-checks).
SHELLS: Final = frozenset(
    {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "pwsh", "busybox"}
    | {"rbash", "ash", "mksh", "yash", "elvish", "nu", "xonsh", "oksh", "posh"}
)
WRAPPERS: Final = frozenset(
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
        "stdbuf",
        "chroot",
        "unshare",
        "nsenter",
        "flock",
        "ionice",
        "taskset",
        "caffeinate",
        "arch",
        "chrt",
        "systemd-run",
        "setpriv",
        "prlimit",
        "unbuffer",
        "fakeroot",
        "proot",
        "firejail",
        "cpulimit",
        "faketime",
    }
)
ELEVATION: Final = frozenset({"sudo", "su", "doas", "pkexec", "runuser"})

_MAX_ARGS: Final = 64
_MAX_ARG_CHARS: Final = 1024


@dataclass(frozen=True)
class CommandVerdict:
    denied: bool
    reason: str | None
    risks: tuple[Risk, ...] = ()


def program_name(program: str) -> str:
    """argv[0]'s basename, version suffix stripped for interpreters
    (`/usr/bin/python3.12` → `python`). Other names keep their spelling."""
    base = posixpath.basename(program)
    stem = normalise(base)
    return stem if stem in INTERPRETERS.values() else base


def _deny(reason: str) -> CommandVerdict:
    return CommandVerdict(denied=True, reason=reason)


def _malformed(argv: object) -> str | None:
    if not isinstance(argv, list | tuple) or not 1 <= len(argv) <= _MAX_ARGS:
        return f"argv must be a list of 1-{_MAX_ARGS} strings"
    for arg in argv:
        if not isinstance(arg, str) or not 1 <= len(arg) <= _MAX_ARG_CHARS:
            return f"every argv item must be a string of 1-{_MAX_ARG_CHARS} characters"
        if any(ch in arg for ch in "\x00\r\n"):
            return "argv items may not contain NUL, CR or LF"
    return None


def _denial(base: str, args: Sequence[str]) -> str | None:
    if prefix_match(base, SHELLS) is not None:
        return f"{base} is a shell"
    if prefix_match(base, WRAPPERS) is not None:
        return f"{base} runs another program"
    if prefix_match(base, ELEVATION) is not None:
        return f"{base} elevates privileges"
    interpreter = normalise(base)
    if interpreter in GRAMMARS:
        reason = interpreter_denial(interpreter, args)
        return None if reason is None else f"{base}: {reason}"
    if prefix_match(base, ("git",)) is not None:
        return git_denial(args)
    return None


def classify(argv: object) -> CommandVerdict:
    """Deny or badge one argument list. Never raises."""
    malformed = _malformed(argv)
    if malformed is not None:
        return _deny(malformed)
    items = cast(Sequence[str], argv)
    reason = _denial(posixpath.basename(items[0]), items[1:])
    if reason is not None:
        return _deny(reason)
    return CommandVerdict(denied=False, reason=None, risks=risks_for(items))


__all__ = [
    "ELEVATION",
    "GIT_CONFIG_FLAGS",
    "INLINE_CODE",
    "SHELLS",
    "WRAPPERS",
    "CommandVerdict",
    "Risk",
    "classify",
    "normalise",
    "program_name",
]
