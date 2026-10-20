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
- a shell must start with its script: any leading `-`/`+` option is refused.
"""

import os
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
    }
)
#: python `-m` modules that are REPLs or debuggers (matched on the top-level package).
REPL_MODULES: frozenset[str] = frozenset(
    {"code", "pdb", "idlelib", "asyncio", "IPython", "ipdb", "pudb", "ptpython", "bpython"}
)
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


def _python(args: Sequence[str]) -> bool:
    index = 0
    while index < len(args):
        arg = args[index]
        following = args[index + 1] if index + 1 < len(args) else None
        if arg == "--":
            return following is not None and following != "-"
        if arg == "-":
            return False
        if not arg.startswith("-"):
            return True
        if arg.startswith("--"):
            head = arg.split("=", 1)[0]
            if head in deny.PYTHON_LONG_VALUE:
                index += 1 if "=" in arg else 2
                continue
            if head not in deny.PYTHON_LONG_SAFE:
                return False
            index += 1
            continue
        verdict = _python_cluster(arg[1:], following)
        if verdict is not None:
            return verdict
        index += 2 if arg[-1] in deny.PYTHON_VALUE_FLAGS else 1
    return False


def _positional(name: str, arg: str) -> bool:
    return arg not in REPL_SUBCOMMANDS.get(name, frozenset())


def _option(name: str, arg: str, options: deny.Options) -> int | None:
    """Arguments a known, non-REPL option consumes; None refuses."""
    flags = REPL_FLAGS.get(name, frozenset())
    if arg.startswith("--"):
        return None if arg.split("=", 1)[0] in flags else deny._long(arg, options)
    if any(f"-{char}" in flags for char in deny._letters(arg, options)):
        return None
    return deny._short(arg, options)


def _interpreter(name: str, args: Sequence[str]) -> bool:
    options = deny.SAFE_OPTIONS.get(name)
    if options is None:
        return False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            following = args[index + 1] if index + 1 < len(args) else "-"
            return following != "-"
        if arg == "-":
            return False
        if not arg.startswith("-"):
            return _positional(name, arg)
        consumed = _option(name, arg, options)
        if consumed is None:
            return False
        index += consumed
    return False


def _deno(args: Sequence[str]) -> bool:
    for arg in args:
        if arg.startswith("-"):
            if arg not in deny.DENO_LEADING and not arg.startswith("--log-level="):
                return False
            continue
        return _positional("deno", arg)
    return False


def _shell(args: Sequence[str]) -> bool:
    return bool(args) and not args[0].startswith(("-", "+"))


def _runs_given_code(name: str, args: Sequence[str]) -> bool:
    if name in deny.SHELLS:
        return _shell(args)
    if name == "python":
        return _python(args)
    if name == "deno":
        return _deno(args)
    return _interpreter(name, args)


def repl_reason(
    argv: Sequence[str],
    *,
    resolved: Sequence[str] = (),
    inside: Callable[[str], bool] = lambda _path: False,
) -> str | None:
    """Why `argv` may not run interactively (a REPL, debugger or bare shell), or None."""
    if not argv:
        return REPL_REFUSAL
    exact = deny.workspace_relative(argv[0])
    names = [(argv[0], exact), *((path, exact and inside(path)) for path in resolved)]
    for path, path_exact in names:
        name = deny.program_name(path, exact=path_exact)
        if name in REPL_PROGRAMS or os.path.basename(path).casefold() in REPL_PROGRAMS:
            return REPL_REFUSAL
        interpreter = name in deny.INLINE_CODE or name in deny.SHELLS
        if interpreter and not _runs_given_code(name, argv[1:]):
            return REPL_REFUSAL
    return None
