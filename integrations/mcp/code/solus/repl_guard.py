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
- only python-family interpreters may run `-m <module>`, and not a REPL/debugger
  module; other interpreters' module flags (perl -m/-M, ruby -r, node -r) load a
  library and then read code from the terminal, so they are not a script;
- a shell must start with its script: any leading `-`/`+` option is refused;
- the script an interpreter or shell runs (and `deno run`'s module) must be an
  existing regular file inside the workspace (the caller's `script_file` check;
  without one everything is refused);
- no interactive program may name stdin or a device as an argument (`-`, `/dev/*`,
  `/proc/*/fd/*`), so code is never read from the terminal through a path.
"""

import os
import re
from collections.abc import Callable, Sequence

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
    }
)
#: Arguments that name stdin or a device (normalised absolute paths).
STDIN_PATH = re.compile(r"^(/dev/.*|/proc/[^/]+/fd(/.*)?)$")
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
    "deno": frozenset({"repl", "eval"}),
}


#: A scan's verdict: the script to check, True (a python module), or False (refused).
Scan = str | bool
#: Whether a script argument is an existing regular file inside the workspace.
ScriptFile = Callable[[str], bool]


def stdin_like(arg: str) -> bool:
    """`-`, or a path (also an option's `=value`) naming stdin, a tty or a device."""
    for value in (arg, arg.partition("=")[2]):
        if value == "-":
            return True
        if value.startswith("/") and STDIN_PATH.match(os.path.normpath("/" + value.lstrip("/"))):
            return True
    return False


def _python_module(module: str) -> bool:
    return bool(module) and module.split(".", 1)[0] not in REPL_MODULES


def _python_cluster(letters: str, following: str | None) -> bool | None:
    """True/False: the cluster decides (a `-m` module ok or not); None: keep scanning."""
    for position, char in enumerate(letters):
        if char == "i" or (char not in deny.PYTHON_FLAGS and char not in "mWX"):
            return False
        if char == "m":
            return _python_module(letters[position + 1 :] or following or "")
    return None


def _after_dashes(args: Sequence[str], index: int) -> Scan:
    return args[index + 1] if index + 1 < len(args) else False


def _python(args: Sequence[str]) -> Scan:
    index = 0
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
        verdict = _python_cluster(arg[1:], following)
        if verdict is not None:
            return verdict
        index += 2 if arg[-1] in deny.PYTHON_VALUE_FLAGS else 1
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


def _deno(args: Sequence[str]) -> Scan:
    """Known global options, a non-REPL subcommand; `deno run` needs its module file."""
    positionals = [index for index, arg in enumerate(args) if not arg.startswith("-")]
    if not positionals:
        return False
    first = positionals[0]
    for arg in args[:first]:
        if arg not in deny.DENO_LEADING and not arg.startswith("--log-level="):
            return False
    subcommand = args[first]
    if subcommand in REPL_SUBCOMMANDS["deno"]:
        return False
    if subcommand != "run":
        return True
    module = next((arg for arg in args[first + 1 :] if not arg.startswith("-") or arg == "-"), None)
    return module if module is not None else False


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


def _refused_name(path: str, exact: bool, args: Sequence[str], script_file: ScriptFile) -> bool:
    name = deny.program_name(path, exact=exact)
    if name in REPL_PROGRAMS or os.path.basename(path).casefold() in REPL_PROGRAMS:
        return True
    if name not in deny.INLINE_CODE and name not in deny.SHELLS:
        return False
    verdict = _scan(name, args)
    if isinstance(verdict, bool):
        return not verdict
    return stdin_like(verdict) or not script_file(verdict)


def repl_reason(
    argv: Sequence[str],
    *,
    resolved: Sequence[str] = (),
    inside: Callable[[str], bool] = lambda _path: False,
    script_file: ScriptFile = lambda _script: False,
) -> str | None:
    """Why `argv` may not run interactively (a REPL, debugger, bare shell, a script that
    is not a workspace file, or stdin/a device as an argument), or None."""
    if not argv or any(stdin_like(arg) for arg in argv[1:]):
        return REPL_REFUSAL
    exact = deny.workspace_relative(argv[0])
    names = [(argv[0], exact), *((path, exact and inside(path)) for path in resolved)]
    for path, path_exact in names:
        if _refused_name(path, path_exact, argv[1:], script_file):
            return REPL_REFUSAL
    return None
