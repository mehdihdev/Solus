"""The server-side deny table for `code.exec` / `code.process_start`
(docs/api/code-command-execution.md §4, widened by the 2026-10-18 security review).

The cloud `CommandPolicy` refuses these before an approval card exists; the
planner refuses them again here, for both the proposed `argv[0]` and the resolved
program (and its realpath). The tables are plain frozen literals so a cross-check
test can compare them with the cloud's mirror. Program names are normalised
case-insensitively with version/build suffixes stripped (`Bash5.2` → `bash`,
`python3.13t` → `python`) and aliases mapped (`nodejs` → `node`, `pypy3` → `python`).
Python and git option parsing FAILS CLOSED on options it does not know.
"""

import os
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType

SHELLS: frozenset[str] = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "fish",
        "dash",
        "ksh",
        "csh",
        "tcsh",
        "pwsh",
        "busybox",
        "rbash",
        "ash",
        "mksh",
        "yash",
        "elvish",
        "nu",
        "xonsh",
        "oksh",
        "posh",
    }
)
WRAPPERS: frozenset[str] = frozenset(
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
ELEVATION: frozenset[str] = frozenset(
    {"sudo", "su", "doas", "pkexec", "chroot", "unshare", "nsenter", "runuser"}
)
#: Interpreter → the options (or, for deno, the subcommands) that run inline code.
INLINE_CODE: Mapping[str, frozenset[str]] = MappingProxyType(
    {
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
)
#: node/bun options whose value is a module specifier; refused with any URL scheme
#: other than `file:` (data:, http(s):, node:, npm:, blob:, …).
NODE_LOADER_FLAGS: frozenset[str] = frozenset(
    {"--import", "--loader", "--experimental-loader", "--require", "-r"}
)
BUN_LOADER_FLAGS: frozenset[str] = frozenset({"--preload", "--require", "-r", "--import"})
ALLOWED_SCHEMES: frozenset[str] = frozenset({"file"})
#: perl -M/-m and ruby -r/-I values must look like plain module / library names.
#: Stricter than `^[A-Za-z0-9_:]+(=[\w,]+)?$`: `::` separators only, so `data:x` fails.
PERL_MODULE_PATTERN = r"^[A-Za-z0-9_]+(::[A-Za-z0-9_]+)*(=[\w,]+)?$"
RUBY_LIBRARY_PATTERN = r"^[A-Za-z0-9_./-]+$"
MODULE_VALUE_FLAGS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "perl": MappingProxyType(
            {"-M": PERL_MODULE_PATTERN, "-m": PERL_MODULE_PATTERN, "-I": RUBY_LIBRARY_PATTERN}
        ),
        "ruby": MappingProxyType({"-r": RUBY_LIBRARY_PATTERN, "-I": RUBY_LIBRARY_PATTERN}),
    }
)
#: git and every `git-*` helper are denied programs: SOL uses the dedicated, previewed
#: git tools (`code.git_*`), never git through exec.
GIT_PROGRAMS: frozenset[str] = frozenset({"git"})
PROGRAM_ALIASES: Mapping[str, str] = MappingProxyType(
    {"nodejs": "node", "luajit": "lua", "pypy": "python"}
)
#: Python's leading options: flags, flags taking a value, safe long options.
PYTHON_FLAGS: frozenset[str] = frozenset("bBdEhiIOPqRsSuvVx?")
PYTHON_VALUE_FLAGS: frozenset[str] = frozenset("WX")
PYTHON_LONG_SAFE: frozenset[str] = frozenset(
    {"--help", "--version", "--help-env", "--help-xoptions", "--help-all"}
)
PYTHON_LONG_VALUE: frozenset[str] = frozenset({"--check-hash-based-pycs"})
#: Generic scanning: options that consume the next argument.
OPTION_VALUES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "node": frozenset({"-r", "--require", "--import", "--loader", "-C", "--conditions"}),
        "perl": frozenset({"-M", "-m", "-I"}),
        "ruby": frozenset({"-r", "-I"}),
    }
)

HINT = "propose the program's argv directly (no shell, no &&, no pipes)"
_SUFFIX = re.compile(r"[-_.]?[0-9][0-9.]*[a-z]*$")
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_INTERPRETERS = {name.casefold(): name for name in INLINE_CODE}
#: Names matched by PREFIX (followed by a non-letter or the end), longest first.
_PREFIX_NAMES = sorted(
    {*SHELLS, *WRAPPERS, *ELEVATION, *GIT_PROGRAMS, *_INTERPRETERS, *PROGRAM_ALIASES},
    key=len,
    reverse=True,
)
_UNSAFE_CHARS = frozenset(chr(code) for code in range(32)) | {chr(127)}
_DENY = "deny"
_ALLOW = "allow"


def _by_prefix(name: str) -> str | None:
    """A known shell/interpreter name that `name` starts with, followed by a non-letter."""
    for known in _PREFIX_NAMES:
        if name.startswith(known) and (len(name) == len(known) or not name[len(known)].isalpha()):
            return known
    return None


def program_name(path: str) -> str:
    """Normalised program name: casefolded, version/build suffixes stripped, aliases
    mapped, and any `<known name><non-letter>…` mapped to the known name (fail closed)."""
    name = os.path.basename(path).casefold()
    prefixed = _by_prefix(name)
    if prefixed is not None:
        name = prefixed
    if name.endswith("-dbg"):
        name = name[: -len("-dbg")]
    stripped = _SUFFIX.sub("", name) or name
    if stripped.startswith("pypy"):
        stripped = "pypy"
    stripped = PROGRAM_ALIASES.get(stripped, stripped)
    if stripped.endswith(("w", "t")) and stripped[:-1] in _INTERPRETERS:
        stripped = stripped[:-1]
    gnu = _by_prefix(stripped[1:]) if stripped.startswith("g") else None
    if gnu is not None and gnu in WRAPPERS:
        return gnu  # GNU coreutils prefix: gtimeout, genv, gxargs, …
    return _INTERPRETERS.get(stripped, stripped)


def _remote(value: str) -> bool:
    """True for a value with any whitespace or control character, or with any URL
    scheme except `file:` (fail closed on anything a loader could reinterpret)."""
    if any(char in _UNSAFE_CHARS or char.isspace() for char in value):
        return True
    match = _SCHEME.match(value)
    return match is not None and match.group(1).casefold() not in ALLOWED_SCHEMES


def _python(args: Sequence[str]) -> str:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("--", "-") or not arg.startswith("-"):
            return _ALLOW
        if arg.startswith("--"):
            head = arg.split("=", 1)[0]
            if head in PYTHON_LONG_VALUE:
                index += 1 if "=" in arg else 2
                continue
            if head not in PYTHON_LONG_SAFE:
                return _DENY
            index += 1
            continue
        verdict = _python_cluster(arg)
        if verdict != "next" and verdict != "value":
            return verdict
        index += 2 if verdict == "value" else 1
    return _ALLOW


def _python_cluster(arg: str) -> str:
    for position, char in enumerate(arg[1:]):
        if char == "c" or (char not in PYTHON_FLAGS and char not in "mWX"):
            return _DENY
        if char == "m":
            return _ALLOW
        if char in PYTHON_VALUE_FLAGS:
            return "value" if position == len(arg) - 2 else "next"
    return "next"


def _loader(name: str, arg: str, following: str | None) -> bool:
    flags = {"node": NODE_LOADER_FLAGS, "bun": BUN_LOADER_FLAGS}.get(name, frozenset())
    head, equals, value = arg.partition("=")
    if head not in flags:
        return False
    return _remote(value if equals else following or "")


def _bad_module_value(name: str, arg: str, following: str | None) -> bool:
    """perl -M/-m/-I and ruby -r/-I (also inside a short cluster, at the first
    value-taking letter) with a value that is not a plain module / library name."""
    patterns = MODULE_VALUE_FLAGS.get(name)
    if patterns is None or arg.startswith("--") or not arg.startswith("-"):
        return False
    values = OPTION_VALUES.get(name, frozenset())
    for position, char in enumerate(arg[1:]):
        option = f"-{char}"
        if option in patterns:
            value = arg[position + 2 :] or following or ""
            # The patterns admit no whitespace/controls; perl's `::` is not a scheme.
            schemed = name != "perl" and _remote(value)
            return schemed or re.fullmatch(patterns[option], value) is None
        if option in values:
            return False
    return False


def _generic(args: Sequence[str], name: str) -> str:
    """Inline-code options anywhere before the first positional (short clusters too)."""
    flags = INLINE_CODE[name]
    values = OPTION_VALUES.get(name, frozenset())
    index = 0
    while index < len(args):
        arg = args[index]
        following = args[index + 1] if index + 1 < len(args) else None
        if (
            arg.split("=", 1)[0] in flags
            or _loader(name, arg, following)
            or _bad_module_value(name, arg, following)
        ):
            return _DENY
        if arg in ("--", "-") or not arg.startswith("-"):
            return _ALLOW
        consumes = arg.split("=", 1)[0] in values and "=" not in arg
        if not arg.startswith("--"):
            for char in arg[1:]:
                if f"-{char}" in flags:
                    return _DENY
                if f"-{char}" in values:
                    consumes = arg.endswith(char)
                    break
        index += 2 if consumes else 1
    return _ALLOW


def _deno(args: Sequence[str]) -> str:
    positionals = 0
    for arg in args:
        if arg == "--":
            return _ALLOW
        if _remote(arg) or _remote(arg.split("=", 1)[-1]):
            return _DENY
        if arg.startswith("-"):
            continue
        if arg in INLINE_CODE["deno"]:
            return _DENY
        positionals += 1
        if positionals == 2:
            return _ALLOW
    return _ALLOW


def _category(name: str) -> str | None:
    for label, table in (
        ("shells", SHELLS),
        ("command wrappers", WRAPPERS),
        ("privilege elevation", ELEVATION),
        ("git — use the dedicated git tools", GIT_PROGRAMS),
    ):
        if name in table:
            return label
    return None


def _check(name: str, args: Sequence[str]) -> str | None:
    category = _category(name)
    if category is not None:
        return f"{name[:64]} is refused ({category}); {HINT}"
    if name not in INLINE_CODE:
        return None
    scanner = {"python": _python, "deno": _deno}.get(name)
    verdict = scanner(args) if scanner else _generic(args, name)
    if verdict == _DENY:
        return f"inline code (or an unknown leading option) for {name} is refused; {HINT}"
    return None


def denied_reason(argv: Sequence[str], *, resolved: Sequence[str] = ()) -> str | None:
    """Why `argv` is refused, or None. `resolved` adds the resolved program path and
    its realpath: each name is checked against the same arguments."""
    if not argv:
        return f"an empty argv is refused; {HINT}"
    for path in (argv[0], *resolved):
        reason = _check(program_name(path), argv[1:])
        if reason is not None:
            return reason
    return None
