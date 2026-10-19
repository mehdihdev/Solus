"""The server-side deny table for `code.exec` / `code.process_start`
(docs/api/code-command-execution.md §4, widened by the 2026-10-18 security review
and §9.11 of the 2026-10-19 Phase 4 amendments).

The cloud `CommandPolicy` refuses these before an approval card exists; the
planner refuses them again here, for both the proposed `argv[0]` and the resolved
program (and its realpath). The tables are plain frozen literals so a cross-check
test can compare them with the cloud's mirror; `classify_denial(argv)` is the pure
entry point the cloud's behavioural parity test loads BY PATH (stdlib only, no
package imports — keep it that way).

Name matching depends on where the program comes from (derived from argv[0] alone):
* a program that is NOT workspace-relative (a bare name or an absolute path) maps to
  a denied name when its casefolded basename is that name followed by the end or any
  non-letter (`zsh-5.9`, `php-cgi8.2`, `sudo-rs`, `python3.12-x86_64`, `sh~`), plus the
  GNU `g` prefix (`gtimeout`) — fail closed;
* a workspace-relative program (`./env_setup.sh`, `tools/x`) is denied only on the
  EXACT normalised name of argv[0] and of its resolved realpath (`./bash`).
Every interpreter in INLINE_CODE FAILS CLOSED on leading options it does not know.
"""

import os
import re
from collections.abc import Callable, Mapping, Sequence
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
LUA_MODULE_PATTERN = r"^[A-Za-z0-9_.]+(=[A-Za-z0-9_.]+)?$"
MODULE_VALUE_FLAGS: Mapping[str, Mapping[str, str]] = MappingProxyType(
    {
        "perl": MappingProxyType(
            {"-M": PERL_MODULE_PATTERN, "-m": PERL_MODULE_PATTERN, "-I": RUBY_LIBRARY_PATTERN}
        ),
        "ruby": MappingProxyType({"-r": RUBY_LIBRARY_PATTERN, "-I": RUBY_LIBRARY_PATTERN}),
        "lua": MappingProxyType({"-l": LUA_MODULE_PATTERN}),
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
        "lua": frozenset({"-l"}),
    }
)


class Options:
    """Leading options an interpreter may take before its script (anything else is
    refused): long flags, long options with a value (`--x=v` or `--x v`), short
    flag letters (clusterable), short letters taking a value (rest of the cluster
    or the next argument), and whether digits may appear in a cluster (`-W0`, `-0777`)."""

    __slots__ = ("long_flags", "long_values", "short_flags", "short_values", "digits")

    def __init__(
        self,
        long_flags: frozenset[str] = frozenset(),
        long_values: frozenset[str] = frozenset(),
        short_flags: str = "",
        short_values: str = "",
        digits: bool = False,
    ) -> None:
        self.long_flags = long_flags
        self.long_values = long_values
        self.short_flags = short_flags
        self.short_values = short_values
        self.digits = digits


_HELP = frozenset({"--help", "--version"})
#: Known-safe leading options per interpreter (python and deno have their own scanners).
SAFE_OPTIONS: Mapping[str, Options] = MappingProxyType(
    {
        "node": Options(
            _HELP
            | {
                "--enable-source-maps",
                "--no-warnings",
                "--no-deprecation",
                "--trace-warnings",
                "--trace-deprecation",
                "--trace-uncaught",
                "--expose-gc",
                "--preserve-symlinks",
                "--abort-on-uncaught-exception",
                "--experimental-vm-modules",
                "--watch",
            },
            frozenset(
                {
                    "--require",
                    "--import",
                    "--loader",
                    "--experimental-loader",
                    "--conditions",
                    "--max-old-space-size",
                    "--stack-size",
                    "--unhandled-rejections",
                    "--title",
                }
            ),
            short_flags="vh",
            short_values="rC",
        ),
        "bun": Options(
            _HELP | {"--hot", "--watch", "--smol", "--silent", "--bun"},
            frozenset({"--preload", "--require", "--import"}),
            short_flags="bvh",
            short_values="r",
        ),
        "ruby": Options(
            _HELP | {"--verbose", "--disable-gems"},
            frozenset({"--encoding", "--external-encoding", "--internal-encoding"}),
            short_flags="wvdhUWcynpal",
            short_values="rIE",
            digits=True,
        ),
        "perl": Options(_HELP, short_flags="wWXtTlcnpasvhU0", short_values="MmI", digits=True),
        "php": Options(_HELP, short_flags="nqvhlsimH", short_values="f"),
        "lua": Options(short_flags="viEW", short_values="l"),
        "Rscript": Options(
            _HELP
            | {
                "--vanilla",
                "--no-save",
                "--no-restore",
                "--no-restore-data",
                "--no-environ",
                "--no-site-file",
                "--no-init-file",
                "--verbose",
                "--quiet",
                "--silent",
            },
            frozenset({"--default-packages", "--encoding"}),
        ),
    }
)
DENO_LEADING: frozenset[str] = frozenset({"-q", "--quiet", "--unstable", "-h", "-V", *_HELP})

HINT = "propose the program's argv directly (no shell, no &&, no pipes)"
_SUFFIX = re.compile(r"[-_.]?[0-9][0-9.]*[a-z]*$")
#: Inspector addresses: a port, optionally on a loopback host (never 0.0.0.0, [::], LAN).
_INSPECT_VALUE = re.compile(r"^((127\.0\.0\.1|localhost|\[::1\]):)?[0-9]{1,5}$")
INSPECT_FLAGS: frozenset[str] = frozenset({"--inspect", "--inspect-brk", "--inspect-wait"})
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*):")
_INTERPRETERS = {name.casefold(): name for name in INLINE_CODE}
#: Names matched by PREFIX outside the workspace (then the end or a non-letter), longest first.
_PREFIX_NAMES = sorted(
    {*SHELLS, *WRAPPERS, *ELEVATION, *GIT_PROGRAMS, *_INTERPRETERS, *PROGRAM_ALIASES},
    key=len,
    reverse=True,
)
_UNSAFE_CHARS = frozenset(chr(code) for code in range(32)) | {chr(127)}
_DENY = "deny"
_ALLOW = "allow"


def _by_prefix(name: str) -> str | None:
    """A known denied name that `name` starts with, followed by the end or ANY
    non-letter (`zsh-5.9`, `perl5.36.0-x86_64-linux`, `bash+x`, `sh~`) — fail closed."""
    for known in _PREFIX_NAMES:
        if name.startswith(known) and (len(name) == len(known) or not name[len(known)].isalpha()):
            return known
    return None


def _gnu(name: str, exact: bool) -> str | None:
    """The wrapper behind a GNU coreutils `g` prefix (`gtimeout`, `genv`, …)."""
    if not name.startswith("g"):
        return None
    inner = name[1:] if exact else _by_prefix(name[1:])
    return inner if inner in WRAPPERS else None


def program_name(path: str, *, exact: bool = False) -> str:
    """Normalised program name: casefolded, version/build suffixes stripped, aliases
    mapped. Unless `exact` (workspace-relative programs), any denied name followed by a
    version and/or `[-.]` tokens maps to that name (fail closed)."""
    name = os.path.basename(path).casefold()
    prefixed = None if exact else _by_prefix(name)
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
    gnu = _gnu(stripped, exact)
    if gnu is not None:
        return gnu
    return _INTERPRETERS.get(stripped, stripped)


def workspace_relative(argv0: str) -> bool:
    """argv[0] names a workspace program (`./x`, `tools/x`), judged by syntax alone. A
    `..` segment can climb out of the workspace, so it is not one (fail closed)."""
    if "/" not in argv0 or os.path.isabs(argv0) or argv0.startswith("~"):
        return False
    return ".." not in argv0.split("/")


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
    """A node/bun loader option whose value is remote — long (`--import x`,
    `--import=x`) or a short letter anywhere in a cluster (`-rX`, `-vr X`)."""
    flags = {"node": NODE_LOADER_FLAGS, "bun": BUN_LOADER_FLAGS}.get(name, frozenset())
    if not flags:
        return False
    if arg.startswith("--") or not arg.startswith("-"):
        head, equals, value = arg.partition("=")
        return head in flags and _remote(value if equals else following or "")
    values = SAFE_OPTIONS[name].short_values
    for position, char in enumerate(arg[1:]):
        if f"-{char}" in flags:
            return _remote(arg[position + 2 :] or following or "")
        if char in values:
            return False
    return False


def _bad_inspect(name: str, arg: str) -> bool:
    """`--inspect*` is a bare flag or a loopback port; anything else is refused."""
    if name not in ("node", "bun"):
        return False
    head, equals, value = arg.partition("=")
    return head in INSPECT_FLAGS and bool(equals) and _INSPECT_VALUE.match(value) is None


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


def _long(arg: str, options: Options) -> int | None:
    """Arguments consumed by a long option, None when it is not known-safe."""
    head, equals, _ = arg.partition("=")
    if equals:
        return 1 if head in options.long_values else None
    if head in options.long_flags:
        return 1
    return 2 if head in options.long_values else None


def _short(arg: str, options: Options) -> int | None:
    """Arguments consumed by a short cluster, None when any letter is not known-safe."""
    for position, char in enumerate(arg[1:]):
        if char in options.short_values:
            return 2 if position == len(arg) - 2 else 1
        if char not in options.short_flags and not (options.digits and char.isdigit()):
            return None
    return 1


def _letters(arg: str, options: Options) -> str:
    """A short cluster's option letters, up to and including the first value letter."""
    for position, char in enumerate(arg[1:]):
        if char in options.short_values:
            return arg[1 : position + 2]
    return arg[1:]


def _generic(args: Sequence[str], name: str) -> str:
    """Leading options up to the first positional: inline code, remote loaders and
    bad module values are refused, and so is any option not known-safe (fail closed)."""
    flags = INLINE_CODE[name]
    options = SAFE_OPTIONS[name]
    index = 0
    while index < len(args):
        arg = args[index]
        following = args[index + 1] if index + 1 < len(args) else None
        if (
            arg.split("=", 1)[0] in flags
            or _loader(name, arg, following)
            or _bad_module_value(name, arg, following)
            or _bad_inspect(name, arg)
        ):
            return _DENY
        if arg in ("--", "-") or not arg.startswith("-"):
            return _ALLOW
        if arg.split("=", 1)[0] in INSPECT_FLAGS and name in ("node", "bun"):
            index += 1
            continue
        if not arg.startswith("--") and any(f"-{char}" in flags for char in _letters(arg, options)):
            return _DENY
        consumed = _long(arg, options) if arg.startswith("--") else _short(arg, options)
        if consumed is None:
            return _DENY
        index += consumed
    return _ALLOW


def _deno(args: Sequence[str]) -> str:
    positionals = 0
    for arg in args:
        if arg == "--":
            return _ALLOW
        if _remote(arg) or _remote(arg.split("=", 1)[-1]):
            return _DENY
        if arg.startswith("-"):
            # Before the subcommand only known-safe global options (fail closed).
            known = arg in DENO_LEADING or arg.startswith("--log-level=")
            if positionals == 0 and not known:
                return _DENY
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


def denied_reason(
    argv: Sequence[str],
    *,
    resolved: Sequence[str] = (),
    inside: Callable[[str], bool] = lambda _path: False,
) -> str | None:
    """Why `argv` is refused, or None. `resolved` adds the resolved program path and
    its realpath, each checked against the same arguments. Exact matching applies only
    to names the workspace chose: a workspace-relative argv[0], and a resolved path
    that `inside` confirms is still in the workspace. Every other name (bare names,
    absolute paths, a workspace link whose target leaves the workspace) is matched
    fail-closed by prefix."""
    if not argv:
        return f"an empty argv is refused; {HINT}"
    exact = workspace_relative(argv[0])
    names = [(argv[0], exact), *((path, exact and inside(path)) for path in resolved)]
    for path, path_exact in names:
        reason = _check(program_name(path, exact=path_exact), argv[1:])
        if reason is not None:
            return reason
    return None


def classify_denial(argv: Sequence[str]) -> str | None:
    """The refusal reason for `argv` from argv alone (what the cloud sees), or None.
    Pure; imported by path by the cloud's behavioural parity test."""
    return denied_reason(list(argv))
