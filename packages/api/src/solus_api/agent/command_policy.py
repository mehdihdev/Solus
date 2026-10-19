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

from solus_api.agent.command_interpreters import GRAMMARS, INLINE_CODE, interpreter_denial
from solus_api.agent.command_names import (
    INTERPRETERS,
    is_workspace_relative,
    name_match,
    normalise,
)
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
ELEVATION: Final = frozenset(
    {"sudo", "su", "doas", "pkexec", "runuser", "chroot", "unshare", "nsenter"}
)
#: Programs SOL never runs through `code.exec`: git has dedicated, previewed tools.
DENIED_PROGRAMS: Final = frozenset({"git"})
_GIT_MESSAGE: Final = (
    "git is not run through code.exec; use code.git_status, code.git_log, code.git_diff, "
    "code.git_commit or code.git_push"
)

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


def _denial(program: str, args: Sequence[str], *, exact: bool) -> str | None:
    base = posixpath.basename(program)
    if name_match(base, SHELLS, exact=exact) is not None:
        return f"{base} is a shell"
    if name_match(base, WRAPPERS, exact=exact, gnu=True) is not None:
        return f"{base} runs another program"
    if name_match(base, ELEVATION, exact=exact) is not None:
        return f"{base} elevates privileges"
    if name_match(base, DENIED_PROGRAMS, exact=exact) is not None:
        return _GIT_MESSAGE
    interpreter = _interpreter(base, exact=exact)
    if interpreter in GRAMMARS:
        reason = interpreter_denial(interpreter, args)
        return None if reason is None else f"{base}: {reason}"
    return None


def _interpreter(base: str, *, exact: bool) -> str | None:
    if not exact:
        return normalise(base)
    found = name_match(base, INTERPRETERS, exact=True)
    return None if found is None else INTERPRETERS[found]


def classify(argv: object, *, workspace_relative: bool | None = None) -> CommandVerdict:
    """Deny or badge one argument list. Never raises.

    A workspace-relative program (`./env-check.sh`) is matched by its EXACT name;
    anything else fails closed by prefix (§9 item 11). `workspace_relative`
    overrides the inference, for a resolved plan argv whose request was relative."""
    malformed = _malformed(argv)
    if malformed is not None:
        return _deny(malformed)
    items = cast(Sequence[str], argv)
    exact = is_workspace_relative(items[0]) if workspace_relative is None else workspace_relative
    reason = _denial(items[0], items[1:], exact=exact)
    if reason is not None:
        return _deny(reason)
    return CommandVerdict(denied=False, reason=None, risks=risks_for(items))


__all__ = [
    "DENIED_PROGRAMS",
    "ELEVATION",
    "INLINE_CODE",
    "SHELLS",
    "WRAPPERS",
    "CommandVerdict",
    "Risk",
    "classify",
    "normalise",
    "program_name",
]
