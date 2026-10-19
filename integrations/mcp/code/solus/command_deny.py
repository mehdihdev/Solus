"""The server-side deny table for `code.exec` / `code.process_start`
(docs/api/code-command-execution.md §4).

The cloud `CommandPolicy` refuses these before an approval card exists; the
planner refuses them again here. The tables are plain frozen literals so a
cross-check test can compare them with the cloud's mirror. Matching is on the
program's basename, case-insensitively (macOS file systems are), with a
trailing version suffix stripped for interpreters (`python3.12` → `python`).
"""

import os
import re
from collections.abc import Mapping, Sequence
from types import MappingProxyType

SHELLS: frozenset[str] = frozenset(
    {"sh", "bash", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "pwsh"}
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
    }
)
ELEVATION: frozenset[str] = frozenset({"sudo", "su", "doas", "pkexec"})
#: Interpreter → the options (or, for deno, the subcommand) that run inline code.
INLINE_CODE: Mapping[str, frozenset[str]] = MappingProxyType(
    {
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
)
#: `git` global options that inject configuration (hooksPath, pager, …).
GIT_CONFIG_FLAGS: frozenset[str] = frozenset({"-c", "--config-env"})
#: Options that consume the NEXT argument as their value while scanning.
OPTION_VALUES: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "python": frozenset({"-W", "-X"}),
        "node": frozenset({"-r", "--require", "--import", "--loader", "-C", "--conditions"}),
        "git": frozenset({"-C", "--git-dir", "--work-tree", "--namespace"}),
    }
)
#: Options after which the remaining arguments belong to someone else.
TERMINATORS: Mapping[str, frozenset[str]] = MappingProxyType({"python": frozenset({"-m"})})

HINT = "propose the program's argv directly (no shell, no &&, no pipes)"
_VERSION_SUFFIX = re.compile(r"[0-9][0-9.]*$")
_INLINE_BY_FOLDED = {name.casefold(): name for name in INLINE_CODE}


def program_name(path: str) -> str:
    """The basename, with a version suffix stripped when that names an interpreter."""
    base = os.path.basename(path)
    stripped = _VERSION_SUFFIX.sub("", base)
    folded = stripped.casefold()
    if stripped != base and (folded in _INLINE_BY_FOLDED or folded == "git"):
        return _INLINE_BY_FOLDED.get(folded, stripped)
    return base


def _cluster_hit(
    arg: str, flags: frozenset[str], values: frozenset[str], ends: frozenset[str]
) -> str:
    """Scan one `-abc` cluster: "hit", "stop", "value" (next arg consumed) or "next"."""
    for index, char in enumerate(arg[1:]):
        option = f"-{char}"
        if option in flags:
            return "hit"
        if option in ends:
            return "stop"
        if option in values:
            return "value" if index == len(arg) - 2 else "next"
    return "next"


def _scan(args: Sequence[str], flags: frozenset[str], name: str) -> bool:
    """True when an inline-code (or config-injection) option precedes the first positional."""
    values = OPTION_VALUES.get(name, frozenset())
    ends = TERMINATORS.get(name, frozenset())
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        head = arg.split("=", 1)[0]
        if head in flags:
            return True
        if arg == "--" or head in ends or not arg.startswith("-") or arg == "-":
            return False
        if arg.startswith("--"):
            skip = head in values and "=" not in arg
            continue
        verdict = _cluster_hit(arg, flags, values, ends)
        if verdict in ("hit", "stop"):
            return verdict == "hit"
        skip = verdict == "value"
    return False


def _category(name: str) -> str | None:
    folded = name.casefold()
    for label, table in (
        ("shells", SHELLS),
        ("command wrappers", WRAPPERS),
        ("privilege elevation", ELEVATION),
    ):
        if folded in table:
            return label
    return None


def denied_reason(argv: Sequence[str]) -> str | None:
    """Why `argv` is refused, or None when the deny table does not apply."""
    if not argv:
        return f"an empty argv is refused; {HINT}"
    name = program_name(argv[0])
    category = _category(name)
    if category is not None:
        return f"{name[:64]} is refused ({category}); {HINT}"
    interpreter = _INLINE_BY_FOLDED.get(name.casefold())
    if interpreter is not None and _scan(argv[1:], INLINE_CODE[interpreter], interpreter):
        return f"inline code for {interpreter} is refused; {HINT}"
    if name.casefold() == "git" and _scan(argv[1:], GIT_CONFIG_FLAGS, "git"):
        return f"git configuration injection (-c/--config-env) is refused; {HINT}"
    return None
