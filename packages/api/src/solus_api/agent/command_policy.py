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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from solus_api.agent.command_risks import Risk, risks_for

#: Mirrored in the server deny table; keep both in lockstep (test cross-checks).
SHELLS: Final = frozenset({"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "pwsh"})
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
    }
)
ELEVATION: Final = frozenset({"sudo", "su", "doas", "pkexec"})
#: interpreter -> the flags (or, for deno, the subcommand) that run inline code.
INLINE_CODE: Final[Mapping[str, frozenset[str]]] = {
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
#: Git global options that inject configuration (aliases, hooks paths, pagers).
GIT_CONFIG_FLAGS: Final = frozenset({"-c", "--config-env"})

_INTERPRETERS: Final = {name.lower(): name for name in INLINE_CODE} | {"pypy": "python"}
_VERSION_SUFFIX: Final = re.compile(r"[-_]?[0-9][0-9.]*$")
_GIT_ARG_OPTIONS: Final = frozenset({"-C", "-c", "--config-env", "--git-dir", "--work-tree"})
#: Interpreter options whose value is the NEXT argument (scanning must skip it).
_VALUE_OPTIONS: Final[Mapping[str, frozenset[str]]] = {
    "python": frozenset({"-W", "-X"}),
    "node": frozenset(
        {"-r", "--require", "--import", "--loader", "--experimental-loader", "-C", "--conditions"}
        | {"--input-type", "--env-file", "--title", "--inspect-port"}
    ),
    "ruby": frozenset({"-I", "-r", "-C", "-E", "-F"}),
    "perl": frozenset({"-I", "-M", "-m"}),
    "php": frozenset({"-d", "-c", "-z"}),
    "lua": frozenset({"-l"}),
    "bun": frozenset({"-r", "--preload", "--cwd", "--env-file", "--config"}),
    "Rscript": frozenset({"--default-packages"}),
}
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
    stem = _VERSION_SUFFIX.sub("", base).lower()
    return _INTERPRETERS.get(stem, base)


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


def _leading_options(args: Sequence[str], consumes: frozenset[str]) -> list[str]:
    """Interpreter options before the script/module: where inline-code flags
    live. Options in `consumes` take the next argument as their value, so
    `python -X dev -c ...` is still scanned past `dev`."""
    options: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-" or not arg.startswith("-") or arg in ("-m", "--"):
            break
        options.append(arg)
        index += 2 if arg in consumes else 1
    return options


def _is_inline_flag(arg: str, flags: frozenset[str]) -> bool:
    if arg in flags or any(arg.startswith(f"{flag}=") for flag in flags if flag.startswith("--")):
        return True
    # Clustered short flags: `-Sc`, `-pe`, `-lne` — any short inline letter.
    letters = {flag[1] for flag in flags if len(flag) == 2 and flag[0] == "-"}
    return not arg.startswith("--") and any(letter in arg[1:] for letter in letters)


def _inline_code(name: str, args: Sequence[str]) -> bool:
    interpreter = _INTERPRETERS.get(_VERSION_SUFFIX.sub("", name).lower())
    if interpreter is None:
        return False
    flags = INLINE_CODE[interpreter]
    if interpreter == "deno":
        return bool(args) and args[0] in flags
    consumes = _VALUE_OPTIONS.get(interpreter, frozenset())
    return any(_is_inline_flag(arg, flags) for arg in _leading_options(args, consumes))


def _git_config_injection(args: Sequence[str]) -> bool:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return False  # the subcommand: its own options are not global
        if arg.startswith("-c") or arg.startswith("--config-env"):
            return True
        index += 2 if arg in _GIT_ARG_OPTIONS else 1
    return False


def _denial(name: str, args: Sequence[str]) -> str | None:
    lowered = name.lower()
    stem = _VERSION_SUFFIX.sub("", lowered)
    if lowered in SHELLS or stem in SHELLS:
        return f"{name} is a shell"
    if lowered in WRAPPERS:
        return f"{name} runs another program"
    if lowered in ELEVATION:
        return f"{name} elevates privileges"
    if _inline_code(name, args):
        return f"{name} with an inline-code flag runs code that is not in a file"
    if lowered == "git" and _git_config_injection(args):
        return "git -c / --config-env injects configuration"
    return None


def classify(argv: Sequence[str]) -> CommandVerdict:
    """Deny or badge one argument list. Never raises."""
    malformed = _malformed(argv)
    if malformed is not None:
        return _deny(malformed)
    name = program_name(argv[0])
    reason = _denial(posixpath.basename(argv[0]), argv[1:])
    if reason is not None:
        return _deny(reason)
    return CommandVerdict(denied=False, reason=None, risks=risks_for(name, argv))


__all__ = [
    "ELEVATION",
    "GIT_CONFIG_FLAGS",
    "INLINE_CODE",
    "SHELLS",
    "WRAPPERS",
    "CommandVerdict",
    "Risk",
    "classify",
    "program_name",
]
