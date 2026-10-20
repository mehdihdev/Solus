"""Interactive mode refuses REPLs, debuggers and bare shells
(docs/api/code-command-execution.md §11.1). Pure.

An interactive process reads its stdin from a terminal SOL can type into, so the
program must be one that runs a given script or module, never one that reads code
from that terminal. Checked on argv[0] and the resolved program (matched like the
deny table) and fail-closed:

- known REPL / debugger / database-shell programs are refused whatever their args;
- an interpreter must reach a non-option positional (its script) through options
  its table knows; an unknown option, a REPL-forcing flag (python `-i`, node `-i`,
  perl `-d`, lua `-i`, php `-a`), stdin (`-`) or no script at all is refused;
- only python-family interpreters may run `-m <module>`, and only a module whose
  top-level package is a workspace package or `.py` file (never stdlib or
  site-packages; the REPL/debugger module list is an extra refusal); other
  interpreters' module flags (perl -m/-M, ruby -r, node -r) load a library and then
  read code from the terminal, so they are not a script;
- deno only as `deno run [known options] <workspace file> [args]`;
- a shell must start with its script: any leading `-`/`+` option is refused;
- the script an interpreter or shell runs (and `deno run`'s module) must be an
  existing regular file inside the workspace (the caller's `script_file` check;
  without one everything is refused);
- no interactive program may take `-` or a `file:` URL as an argument, nor a path-like
  argument (or `=value`) whose realpath (against the planned cwd) is under /dev or a
  /proc/<pid>/fd — except serial ports (`/dev/cu.*`, `/dev/tty.*`, `/dev/ttyUSB*`,
  `/dev/ttyACM*`) — so code is never read from stdin or the terminal through a path.
"""

import os
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from . import command_deny as deny

REPL_REFUSAL = "interactive mode needs a script or program, not a REPL or bare shell"
#: Programs that are REPLs, debuggers or database shells (casefolded basename or
#: normalised name).
REPL_PROGRAMS: frozenset[str] = frozenset(
    {
        "ipython",
        "ptpython",
        "bpython",
        "irb",
        "pry",
        "rails",
        "sqlite",
        "sqlite3",
        "psql",
        "mysql",
        "mongo",
        "mongosh",
        "redis-cli",
        "gdb",
        "lldb",
        "pdb",
        "r",
        "julia",
        "ghci",
        "erl",
        "iex",
        "node-inspect",
        "tclsh",
        "wish",
        # pagers, editors and remote/terminal tools with shell escapes
        "less",
        "more",
        "most",
        "man",
        "vi",
        "vim",
        "nvim",
        "view",
        "ex",
        "ed",
        "emacs",
        "ftp",
        "telnet",
        "ssh",
        "nc",
        "ncat",
        "socat",
        "screen",
        "tmux",
        "script",
        "expect",
    }
)
#: python `-m` modules that are REPLs, debuggers, or run/forward other code (matched on
#: the top-level package).
REPL_MODULES: frozenset[str] = frozenset(
    {
        "code",
        "pdb",
        "idlelib",
        "asyncio",
        "IPython",
        "ipdb",
        "pudb",
        "ptpython",
        "bpython",
        "cProfile",
        "profile",
        "trace",
        "runpy",
        "timeit",
        "xonsh",
        "sqlite3",
        "jupyter",
        "jupyter_console",
        "ptipython",
        "bpdb",
        "web_pdb",
        "rpdb",
        "remote_pdb",
        "ipykernel",
        "_pyrepl",
        "pyrepl",
        "pydoc",
    }
)
#: Paths that are stdin, a terminal or another device (realpaths and normalised spellings).
DEVICE_PATH = re.compile(r"^(/dev(/.*)?|/proc/[^/]+/fd(/.*)?)$")
#: Serial ports a robotics program may be handed as a plain argument.
SERIAL_PORT = re.compile(r"^/dev/(cu\.[^/]+|tty\.[^/]+|ttyUSB[0-9]+|ttyACM[0-9]+)$")
FILE_URL = re.compile(r"^file:", re.IGNORECASE)
#: Leading flags that force an interactive interpreter even with a script.
REPL_FLAGS: dict[str, frozenset[str]] = {
    "node": frozenset({"-i", "--interactive"}),
    "bun": frozenset({"-i", "--interactive"}),
    "perl": frozenset({"-d"}),
    "lua": frozenset({"-i"}),
    "php": frozenset({"-a"}),
}
#: First positionals that are a REPL or debugger subcommand, not a script.
REPL_SUBCOMMANDS: dict[str, frozenset[str]] = {
    "node": frozenset({"inspect", "debug"}),
    "bun": frozenset({"repl"}),
}
_DENO_PERMISSIONS = frozenset(
    {
        "--allow-net",
        "--allow-read",
        "--allow-write",
        "--allow-env",
        "--allow-sys",
        "--allow-run",
        "--allow-ffi",
        "--allow-hrtime",
    }
)
#: `deno run` options: flags, flags that also take `=value`, and options taking a value.
DENO_RUN_FLAGS: frozenset[str] = frozenset(
    {"-A", "--allow-all", "-q", "--quiet", "--no-check", "--unstable", "--no-prompt"}
    | {"--cached-only", "--no-remote", "--no-npm", "--watch", "--check", "--reload", "-r"}
    | _DENO_PERMISSIONS
)
DENO_RUN_EQUALS: frozenset[str] = frozenset(
    {"--no-check", "--watch", "--check", "--reload", "--env-file"} | _DENO_PERMISSIONS
)
DENO_RUN_VALUES: frozenset[str] = frozenset(
    {"--config", "-c", "--import-map", "--lock", "--location", "--seed", "--cert"}
)


@dataclass(frozen=True)
class Module:
    """A python `-m` target."""

    name: str


#: A scan's verdict: the script to check, a python module, or True/False (decided).
Scan = str | Module | bool
#: Whether a script / a module's top-level name is a workspace file / package.
ScriptFile = Callable[[str], bool]


@dataclass(frozen=True)
class Workspace:
    """The caller's workspace checks; the defaults refuse everything (fail closed)."""

    script_file: ScriptFile = lambda _script: False
    module_file: ScriptFile = lambda _module: False
    cwd: str = "/"
    #: The applied environment leaves python's module search to the cwd (no
    #: PYTHONSAFEPATH, no PYTHONPATH entry outside the workspace).
    module_path_ok: bool = False


def _device(path: str) -> bool:
    return DEVICE_PATH.match(path) is not None and SERIAL_PORT.match(path) is None


def _values(arg: str) -> list[str]:
    """The argument, its `=value`, and a short option's attached value (`-f/dev/x`)."""
    values = [arg, arg.partition("=")[2]]
    if arg.startswith("-") and not arg.startswith("--") and len(arg) > 2 and arg[1].isalpha():
        values.append(arg[2:])
    return values


def unsafe_argument(arg: str, cwd: str = "/") -> bool:
    """`-`, a `file:` URL, or a path-like value naming stdin, a terminal or a device."""
    for value in _values(arg):
        if value == "-" or FILE_URL.match(value):
            return True
        if "/" not in value:
            continue
        spelled = os.path.normpath(os.path.join(cwd, value))
        if _device(spelled) or _device(os.path.realpath(spelled)):
            return True
    return False


#: python flags that change where `-m` finds modules (isolation, safe path, no env).
PATH_CHANGING_FLAGS = frozenset("IPE")


@dataclass(frozen=True)
class Cluster:
    """One short-option cluster: a decided verdict, or arguments consumed."""

    verdict: Scan | None
    consumed: int = 1
    path_changing: bool = False


def _python_cluster(letters: str, following: str | None, path_changed: bool) -> Cluster:
    for position, char in enumerate(letters):
        if char == "i" or (char not in deny.PYTHON_FLAGS and char not in "mWX"):
            return Cluster(False)
        path_changed = path_changed or char in PATH_CHANGING_FLAGS
        if char == "m":
            module = letters[position + 1 :] or following or ""
            return Cluster(Module(module) if module and not path_changed else False)
        if char in deny.PYTHON_VALUE_FLAGS:  # the rest, or the next argument, is its value
            return Cluster(None, 2 if position == len(letters) - 1 else 1, path_changed)
    return Cluster(None, 1, path_changed)


def _after_dashes(args: Sequence[str], index: int) -> Scan:
    return args[index + 1] if index + 1 < len(args) else False


def _python(args: Sequence[str]) -> Scan:
    index, path_changed = 0, False
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return _after_dashes(args, index)
        if not arg.startswith("-") or arg == "-":
            return arg
        if arg.startswith("--"):
            head = arg.split("=", 1)[0]
            if head in deny.PYTHON_LONG_VALUE:
                index += 1 if "=" in arg else 2
                continue
            if head not in deny.PYTHON_LONG_SAFE:
                return False
            index += 1
            continue
        following = args[index + 1] if index + 1 < len(args) else None
        cluster = _python_cluster(arg[1:], following, path_changed)
        if cluster.verdict is not None:
            return cluster.verdict
        path_changed = cluster.path_changing
        index += cluster.consumed
    return False


def _positional(name: str, arg: str) -> Scan:
    return False if arg in REPL_SUBCOMMANDS.get(name, frozenset()) else arg


def _option(name: str, arg: str, options: deny.Options) -> int | None:
    """Arguments a known, non-REPL option consumes; None refuses."""
    flags = REPL_FLAGS.get(name, frozenset())
    if arg.startswith("--"):
        return None if arg.split("=", 1)[0] in flags else deny._long(arg, options)
    if any(f"-{char}" in flags for char in deny._letters(arg, options)):
        return None
    return deny._short(arg, options)


def _interpreter(name: str, args: Sequence[str]) -> Scan:
    options = deny.SAFE_OPTIONS.get(name)
    if options is None:
        return False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return _after_dashes(args, index)
        if not arg.startswith("-") or arg == "-":
            return _positional(name, arg)
        consumed = _option(name, arg, options)
        if consumed is None:
            return False
        index += consumed
    return False


def _deno_run_option(arg: str) -> int | None:
    """Arguments a known `deno run` option consumes; None refuses."""
    head, equals, _ = arg.partition("=")
    if equals:
        return 1 if head in DENO_RUN_EQUALS or head in DENO_RUN_VALUES else None
    if arg in DENO_RUN_FLAGS:
        return 1
    return 2 if arg in DENO_RUN_VALUES else None


def _deno(args: Sequence[str]) -> Scan:
    """Only `deno [known globals] run [known options] <module> [args]`."""
    index = 0
    while index < len(args) and args[index].startswith("-") and args[index] != "-":
        if args[index] not in deny.DENO_LEADING:
            return False
        index += 1
    if index >= len(args) or args[index] != "run":
        return False
    index += 1
    while index < len(args) and args[index].startswith("-") and args[index] != "-":
        consumed = _deno_run_option(args[index])
        if consumed is None:
            return False
        index += consumed
    return args[index] if index < len(args) else False


def _shell(args: Sequence[str]) -> Scan:
    return args[0] if args and not args[0].startswith(("-", "+")) else False


def _scan(name: str, args: Sequence[str]) -> Scan:
    if name in deny.SHELLS:
        return _shell(args)
    if name == "python":
        return _python(args)
    if name == "deno":
        return _deno(args)
    return _interpreter(name, args)


def _accepted(verdict: Scan, workspace: Workspace) -> bool:
    if isinstance(verdict, bool):
        return verdict
    if isinstance(verdict, Module):
        top = verdict.name.split(".", 1)[0]
        return (
            top not in REPL_MODULES
            and workspace.module_path_ok
            and workspace.module_file(verdict.name)
        )
    return workspace.script_file(verdict)


def _refused_name(path: str, exact: bool, args: Sequence[str], workspace: Workspace) -> bool:
    name = deny.program_name(path, exact=exact)
    if name in REPL_PROGRAMS or os.path.basename(path).casefold() in REPL_PROGRAMS:
        return True
    if name not in deny.INLINE_CODE and name not in deny.SHELLS:
        return False
    return not _accepted(_scan(name, args), workspace)


def repl_reason(
    argv: Sequence[str],
    *,
    resolved: Sequence[str] = (),
    inside: Callable[[str], bool] = lambda _path: False,
    workspace: Workspace | None = None,
) -> str | None:
    """Why `argv` may not run interactively (a REPL, debugger, bare shell, a script or
    module outside the workspace, or stdin/a device as an argument), or None."""
    checks = workspace if workspace is not None else Workspace()
    if not argv or any(unsafe_argument(arg, checks.cwd) for arg in argv[1:]):
        return REPL_REFUSAL
    exact = deny.workspace_relative(argv[0])
    names = [(argv[0], exact), *((path, exact and inside(path)) for path in resolved)]
    for path, path_exact in names:
        if _refused_name(path, path_exact, argv[1:], checks):
            return REPL_REFUSAL
    return None
