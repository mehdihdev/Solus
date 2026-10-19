"""Fail-closed option parsing for interpreters and git (SOLUSDEV-317 §4).

Security review 2026-10-18: an inline-code flag can hide behind any option the
scanner does not understand (`python -X dev -c …`, `node --frobnicate -e …`).
So every option before the script/module/subcommand must be KNOWN: a safe flag,
or a value option whose value is checked. Anything else is denied. Denial is
defence in depth — the approval card and the sandbox remain the primary controls.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

#: interpreter -> the flags (or, for deno, the subcommands) that run inline code.
#: Mirrored in the server deny table (cross-checked by a test).
INLINE_CODE: Final[Mapping[str, frozenset[str]]] = {
    "python": frozenset({"-c"}),
    "node": frozenset({"-e", "--eval", "-p", "--print"}),
    "ruby": frozenset({"-e"}),
    "perl": frozenset({"-e", "-E"}),
    "php": frozenset({"-r", "-B", "-R", "-E", "-F"}),
    "lua": frozenset({"-e"}),
    "deno": frozenset({"eval", "repl"}),
    "bun": frozenset({"-e", "--eval", "-p", "--print"}),
    "Rscript": frozenset({"-e"}),
}


@dataclass(frozen=True)
class Grammar:
    """The leading options an interpreter accepts before its script."""

    short_flags: str = ""  # single letters that take no value (clusterable)
    long_flags: frozenset[str] = frozenset()
    value_options: frozenset[str] = frozenset()  # value attached (`-Wx`, `--a=b`) or next
    stop: frozenset[str] = frozenset({"--", "-"})  # end of options


_HELP: Final = frozenset({"--version", "--help"})
GRAMMARS: Final[Mapping[str, Grammar]] = {
    "python": Grammar(
        short_flags="bBdEhiIOPqsSuvVxR",
        long_flags=_HELP | {"--help-env", "--help-xoptions", "--help-all"},
        value_options=frozenset({"-W", "-X", "--check-hash-based-pycs"}),
        stop=frozenset({"--", "-", "-m"}),
    ),
    "node": Grammar(
        short_flags="vhci",
        long_flags=_HELP
        | {
            "--inspect",
            "--inspect-brk",
            "--enable-source-maps",
            "--no-warnings",
            "--trace-warnings",
            "--trace-uncaught",
            "--trace-deprecation",
            "--no-deprecation",
            "--expose-gc",
            "--experimental-vm-modules",
            "--preserve-symlinks",
            "--abort-on-uncaught-exception",
            "--watch",
            "--test",
            "--max-old-space-size",
            "--stack-size",
            "--unhandled-rejections",
        },
        value_options=frozenset(
            {"-r", "--require", "--import", "--loader", "--experimental-loader", "-C"}
            | {"--conditions", "--input-type", "--env-file", "--title", "--inspect-port"}
        ),
    ),
    "ruby": Grammar(
        short_flags="acdhlnpsvwWyU",
        long_flags=_HELP | {"--verbose", "--copyright", "--jit", "--yjit", "--disable-gems"},
        value_options=frozenset({"-I", "-r", "-C", "-E", "-F", "--disable", "--enable"}),
    ),
    "perl": Grammar(
        short_flags="acdlnpstTuUwWX0",
        long_flags=_HELP,
        value_options=frozenset({"-I", "-M", "-m"}),
    ),
    "php": Grammar(
        short_flags="hvnqsilma",
        long_flags=_HELP,
        value_options=frozenset({"-d", "-c", "-z", "-f", "-t", "-S"}),
    ),
    "lua": Grammar(short_flags="viEW", value_options=frozenset({"-l", "-j", "-O"})),
    "bun": Grammar(
        short_flags="vhb",
        long_flags=_HELP | {"--watch", "--hot", "--smol", "--silent", "--bun"},
        value_options=frozenset({"-r", "--preload", "--cwd", "--env-file", "--config"}),
    ),
    "deno": Grammar(short_flags="qhV", long_flags=_HELP | {"--quiet", "--unstable"}),
    "Rscript": Grammar(
        long_flags=_HELP
        | {"--vanilla", "--verbose", "--no-environ", "--no-site-file", "--no-init-file"}
        | {"--restore", "--no-restore", "--save", "--no-save", "--slave", "--quiet"},
        value_options=frozenset({"--default-packages"}),
    ),
}

_REMOTE_SPECIFIER: Final = re.compile(r"^(?:data|https?|blob):", re.IGNORECASE)
_PERL_MODULE: Final = re.compile(r"^-?[A-Za-z_][\w:]*(?:=[\w,:]*)?$")
_JS: Final = frozenset({"node", "bun", "deno"})


def _short_value_option(arg: str, grammar: Grammar) -> str | None:
    """`-Wignore` → `-W` when `-W` is a short value option."""
    prefix = arg[:2]
    return prefix if len(arg) > 2 and prefix in grammar.value_options else None


def _bad_value(interpreter: str, option: str, value: str) -> str | None:
    if interpreter in _JS and _REMOTE_SPECIFIER.match(value):
        return f"{option} loads remote or inline code"
    if interpreter == "perl" and option in ("-M", "-m") and not _PERL_MODULE.match(value):
        return f"{option} with a non-module value runs code"
    return None


def _option(
    interpreter: str, grammar: Grammar, args: Sequence[str], index: int
) -> tuple[str | None, int]:
    """Judge the option at `index`: (denial reason | None, next index)."""
    arg = args[index]
    inline = INLINE_CODE[interpreter]
    name, _, attached = arg.partition("=") if arg.startswith("--") else (arg, "", "")
    if name in inline:
        return "an inline-code flag runs code that is not in a file", index + 1
    if name in grammar.value_options:
        if attached or "=" in arg:
            return _bad_value(interpreter, name, attached), index + 1
        value = args[index + 1] if index + 1 < len(args) else ""
        return _bad_value(interpreter, name, value), index + 2
    if arg.startswith("--"):
        known = name in grammar.long_flags
        return (None if known else f"unrecognised option {name}"), index + 1
    short = _short_value_option(arg, grammar)
    if short is not None:
        return _bad_value(interpreter, short, arg[2:]), index + 1
    letters = arg[1:]
    inline_letters = {flag[1] for flag in inline if len(flag) == 2 and flag[0] == "-"}
    if any(letter in inline_letters for letter in letters):
        return "an inline-code flag runs code that is not in a file", index + 1
    if letters and all(letter in grammar.short_flags for letter in letters):
        return None, index + 1
    return f"unrecognised option {arg[:32]}", index + 1


def interpreter_denial(interpreter: str, args: Sequence[str]) -> str | None:
    """Why `interpreter args…` is denied, or None. Fail closed on unknown options."""
    grammar = GRAMMARS[interpreter]
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in grammar.stop or not arg.startswith("-"):
            break
        reason, index = _option(interpreter, grammar, args, index)
        if reason is not None:
            return reason
    rest = args[index:]
    positional = next((a for a in rest if not a.startswith("-")), None)
    if interpreter == "deno":
        if positional in INLINE_CODE["deno"]:
            return f"deno {positional} runs code that is not in a file"
        positional = next((a for a in rest[1:] if not a.startswith("-")), None)
    if interpreter in _JS and positional is not None and _REMOTE_SPECIFIER.match(positional):
        return "a data: or remote specifier runs code that is not in the workspace"
    return None


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


def git_denial(args: Sequence[str]) -> str | None:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return None  # the subcommand: its own options are not global
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
