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
    {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "pwsh", "busybox"}
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
#: node options whose value is a module to load; refused with a remote/inline value.
NODE_LOADER_FLAGS: frozenset[str] = frozenset(
    {"--import", "--loader", "--experimental-loader", "--require", "-r"}
)
REMOTE_PREFIXES: tuple[str, ...] = ("data:", "http:", "https:")
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
#: git global options (before the subcommand).
GIT_DENIED_GLOBAL_OPTIONS: frozenset[str] = frozenset({"-c", "--config-env", "--exec-path"})
GIT_SAFE_GLOBAL_OPTIONS: frozenset[str] = frozenset(
    {
        "-C",
        "--git-dir",
        "--work-tree",
        "--namespace",
        "--no-pager",
        "-P",
        "--paginate",
        "-p",
        "--bare",
        "--version",
        "-v",
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
GIT_VALUE_OPTIONS: frozenset[str] = frozenset({"-C", "--git-dir", "--work-tree", "--namespace"})
#: Generic scanning: options that consume the next argument.
OPTION_VALUES: Mapping[str, frozenset[str]] = MappingProxyType(
    {"node": frozenset({"-r", "--require", "--import", "--loader", "-C", "--conditions"})}
)

HINT = "propose the program's argv directly (no shell, no &&, no pipes)"
_SUFFIX = re.compile(r"[-_.]?[0-9][0-9.]*[a-z]*$")
_INTERPRETERS = {name.casefold(): name for name in INLINE_CODE}
_DENY = "deny"
_ALLOW = "allow"


def program_name(path: str) -> str:
    """Normalised program name: casefolded, version/build suffixes stripped, aliases mapped."""
    name = os.path.basename(path).casefold()
    if name.endswith("-dbg"):
        name = name[: -len("-dbg")]
    stripped = _SUFFIX.sub("", name) or name
    if stripped.startswith("pypy"):
        stripped = "pypy"
    stripped = PROGRAM_ALIASES.get(stripped, stripped)
    if stripped.endswith(("w", "t")) and stripped[:-1] in _INTERPRETERS:
        stripped = stripped[:-1]
    return _INTERPRETERS.get(stripped, stripped)


def _remote(value: str) -> bool:
    return value.casefold().startswith(REMOTE_PREFIXES)


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


def _node_loader(arg: str, following: str | None) -> bool:
    head, equals, value = arg.partition("=")
    if head not in NODE_LOADER_FLAGS:
        return False
    return _remote(value if equals else following or "")


def _generic(args: Sequence[str], name: str) -> str:
    """Inline-code options anywhere before the first positional (short clusters too)."""
    flags = INLINE_CODE[name]
    values = OPTION_VALUES.get(name, frozenset())
    index = 0
    while index < len(args):
        arg = args[index]
        following = args[index + 1] if index + 1 < len(args) else None
        if arg.split("=", 1)[0] in flags or (name == "node" and _node_loader(arg, following)):
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
        if _remote(arg.split("=", 1)[-1]):
            return _DENY
        if arg.startswith("-"):
            continue
        if arg in INLINE_CODE["deno"]:
            return _DENY
        positionals += 1
        if positionals == 2:
            return _ALLOW
    return _ALLOW


def _git(args: Sequence[str]) -> str:
    index = 0
    while index < len(args):
        arg = args[index]
        if not arg.startswith("-"):
            return _ALLOW
        head = arg.split("=", 1)[0]
        if head in GIT_DENIED_GLOBAL_OPTIONS or arg.startswith("-c"):
            return _DENY
        if head not in GIT_SAFE_GLOBAL_OPTIONS:
            return _DENY
        index += 2 if head in GIT_VALUE_OPTIONS and "=" not in arg else 1
    return _ALLOW


def _category(name: str) -> str | None:
    for label, table in (
        ("shells", SHELLS),
        ("command wrappers", WRAPPERS),
        ("privilege elevation", ELEVATION),
    ):
        if name in table:
            return label
    return None


def _check(name: str, args: Sequence[str]) -> str | None:
    category = _category(name)
    if category is not None:
        return f"{name[:64]} is refused ({category}); {HINT}"
    if name == "git" and _git(args) == _DENY:
        return f"git configuration injection or an unknown global option is refused; {HINT}"
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
