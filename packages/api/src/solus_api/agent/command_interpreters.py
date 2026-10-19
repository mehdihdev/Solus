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
    attached_flags: frozenset[str] = frozenset()  # long flags with an OPTIONAL `=value`
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
        },
        value_options=frozenset(
            {"-r", "--require", "--import", "--loader", "--experimental-loader", "-C"}
            | {"--conditions", "--input-type", "--env-file", "--title", "--inspect-port"}
        ),
        attached_flags=frozenset(
            {"--inspect", "--inspect-brk", "--inspect-wait", "--max-old-space-size"}
            | {"--stack-size", "--unhandled-rejections"}
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

_SCHEME: Final = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_PERL_MODULE: Final = re.compile(r"^[A-Za-z0-9_:]+(?:=[\w,]+)?$")
_RUBY_NAME: Final = re.compile(r"^[\w./@+-]+$")
_PHP_DENIED_INI: Final = frozenset({"allow_url_include", "auto_prepend_file", "auto_append_file"})
_LOCAL_HOSTS: Final = frozenset({"127.0.0.1", "localhost", "::1"})
_JS: Final = frozenset({"node", "bun", "deno"})


def _unsafe_chars(value: str) -> bool:
    return any(ord(ch) < 0x20 or ch.isspace() for ch in value)


def _remote(value: str) -> bool:
    """A specifier that is not a plain workspace file: ANY whitespace or C0
    control character anywhere, or any scheme but `file:` (npm:, jsr:, node:,
    data:, blob:, http…)."""
    if _unsafe_chars(value):
        return True
    match = _SCHEME.match(value)
    return match is not None and match.group(1).lower() != "file"


def _off_host(value: str) -> bool:
    """`--inspect=<[host:]port>` bound anywhere but loopback."""
    if not value or value.isdigit():
        return False
    host = value[1 : value.find("]")] if value.startswith("[") else value.rpartition(":")[0]
    host = host or value
    return host.lower() not in _LOCAL_HOSTS


def _bad_value(interpreter: str, option: str, value: str) -> str | None:
    if option.startswith("--inspect"):
        return f"{option} exposes the debugger beyond this machine" if _off_host(value) else None
    if interpreter in _JS and _remote(value):
        return f"{option} loads code that is not a workspace file"
    if interpreter == "perl" and option in ("-M", "-m", "-I") and _unsafe_chars(value):
        return f"{option} must name a module or directory"
    if interpreter == "perl" and option in ("-M", "-m") and not _PERL_MODULE.match(value):
        return f"{option} with a non-module value runs code"
    if (
        interpreter == "ruby"
        and option in ("-r", "-I")
        and (_remote(value) or not _RUBY_NAME.match(value))
    ):
        return f"{option} must name a library or directory"
    if interpreter == "php" and option == "-d":
        if value.partition("=")[0].strip().lower() in _PHP_DENIED_INI:
            return "-d sets an ini option that loads code"
    return None


def _long_option(interpreter: str, grammar: Grammar, name: str, attached: str | None) -> str | None:
    if name in grammar.attached_flags:
        return None if attached is None else _bad_value(interpreter, name, attached)
    if name in grammar.long_flags:
        return None if attached is None else f"{name} takes no value"
    return f"unrecognised option {name[:32]}"


def _option(
    interpreter: str, grammar: Grammar, args: Sequence[str], index: int
) -> tuple[str | None, int]:
    """Judge the option at `index`: (denial reason | None, next index)."""
    arg = args[index]
    inline = INLINE_CODE[interpreter]
    long = arg.startswith("--")
    name, equals, attached = arg.partition("=") if long else (arg, "", "")
    if name in inline:
        return "an inline-code flag runs code that is not in a file", index + 1
    if name in grammar.value_options:
        if equals:
            return _bad_value(interpreter, name, attached), index + 1
        value = args[index + 1] if index + 1 < len(args) else ""
        return _bad_value(interpreter, name, value), index + 2
    if long:
        return _long_option(interpreter, grammar, name, attached if equals else None), index + 1
    return _short_cluster(interpreter, grammar, args, index)


def _short_cluster(
    interpreter: str, grammar: Grammar, args: Sequence[str], index: int
) -> tuple[str | None, int]:
    """`-wMfoo`, `-Sc`, `-lne`: each letter must be a safe flag until the first
    value-taking letter, whose value is the rest of the group or the next arg."""
    arg = args[index]
    inline_letters = {f[1] for f in INLINE_CODE[interpreter] if len(f) == 2 and f[0] == "-"}
    value_letters = {o[1] for o in grammar.value_options if len(o) == 2 and o[0] == "-"}
    for position, letter in enumerate(arg[1:], start=2):
        if letter in inline_letters:
            return "an inline-code flag runs code that is not in a file", index + 1
        if letter in value_letters:
            rest = arg[position:]
            if rest:
                return _bad_value(interpreter, f"-{letter}", rest), index + 1
            value = args[index + 1] if index + 1 < len(args) else ""
            return _bad_value(interpreter, f"-{letter}", value), index + 2
        if letter not in grammar.short_flags:
            return f"unrecognised option {arg[:32]}", index + 1
    return (None if len(arg) > 1 else "an empty option"), index + 1


def _deno_denial(rest: Sequence[str]) -> str | None:
    """Every argument after deno's global options: no eval/repl subcommand
    anywhere, and no non-`file:` specifier in any argument or `--x=value`."""
    for arg in rest:
        value = arg.partition("=")[2] if arg.startswith("--") else arg
        if not arg.startswith("-") and arg in INLINE_CODE["deno"]:
            return f"deno {arg} runs code that is not in a file"
        if _remote(value):
            return "a non-file specifier runs code that is not in the workspace"
    return None


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
    if interpreter == "deno":
        return _deno_denial(rest)
    positionals = [a for a in rest if not a.startswith("-")]
    # node: the script is the specifier; bun: a subcommand may precede it.
    specifiers = positionals[:1] if interpreter == "node" else positionals
    if interpreter in _JS and any(_remote(spec) for spec in specifiers):
        return "a non-file specifier runs code that is not in the workspace"
    return None
