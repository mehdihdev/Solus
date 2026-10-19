"""Planning `exec`, `process_start` and `profile_capture`
(docs/api/code-command-execution.md §2.1–2.4). Pure apart from `stat`/`realpath`
and reading a stored profile.

`argv[0]` resolves, first match wins and never via the inherited PATH:
(1) a relative path containing `/` → an executable regular file inside the
workspace; (2) an absolute path → only when its parent directory is one of the
roots below; (3) a bare name → `<environment>/bin`, then (4) the profile's
absolute PATH entries, then (5) `execute.SEARCH_ROOTS`. The deny table is checked
on the proposed name, the resolved program and its realpath.
"""

import os
import shutil
from collections.abc import Callable, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from . import command_deny, execute, profiles, sandbox
from .plan import Args, Plan, Which, _echo, _refuse, _relative, venv_python
from .workspace import resolve_inside

MAX_ARGV = 64
MAX_ARGV_CHARS = 1024
DEFAULT_EXEC_TIMEOUT_SECONDS = 120
MAX_EXEC_TIMEOUT_SECONDS = 600
MIN_RUNTIME_SECONDS = 60
MAX_RUNTIME_SECONDS = 14400
DEFAULT_RUNTIME_SECONDS = 3600
MAX_LABEL_CHARS = 64
EXEC_KEYS = frozenset({"argv", "cwd", "environment", "profile", "timeout_seconds"})
PROCESS_KEYS = frozenset({"argv", "cwd", "environment", "profile", "name", "max_runtime_seconds"})
CAPTURE_KEYS = frozenset({"name", "setup_file", "extends"})
_FORBIDDEN = ("\x00", "\n", "\r")
SCRIPT_REFUSAL = "script must be an existing .sh/.bash file inside the linked folder"
WORKSPACE_SCOPE = "workspace"
SYSTEM_SCOPE = "system"


def _bounded_int(args: Args, key: str, default: int, low: int, high: int) -> int | None:
    value = args.get(key, default)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        return None
    return value


def validate_argv(value: object) -> list[str] | str:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_ARGV:
        return f"argv must be a list of 1 to {MAX_ARGV} strings"
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item) <= MAX_ARGV_CHARS:
            return f"every argv item must be a string of 1 to {MAX_ARGV_CHARS} chars"
        if any(char in item for char in _FORBIDDEN):
            return "argv items may not contain NUL, CR or LF"
    return list(value)


def _cwd(root: Path, args: Args) -> str | None:
    value = args.get("cwd", ".")
    if value in (None, "."):
        return "."
    if not isinstance(value, str) or not _relative(value):
        return None
    resolved = resolve_inside(value, root)
    return value if resolved is not None and resolved.is_dir() else None


def _environment(root: Path, args: Args) -> tuple[str | None, str | None] | str:
    """`(environment, its bin dir)`; both None when not requested."""
    environment = args.get("environment")
    if environment is None:
        return None, None
    if not isinstance(environment, str) or not _relative(environment):
        return "environment must be a relative path inside the linked folder"
    if venv_python(root, environment) is None:
        return f"no virtualenv found at {_echo(environment)} (create_environment first)"
    return environment, str(execute.venv_bin_dir(root, environment))


def _profile(root: Path, value: object) -> profiles.Profile | None | str:
    if value is None:
        return None
    return profiles.load(root, value)


def profile_path_dirs(profile: profiles.Profile | None) -> list[str]:
    if profile is None:
        return []
    path = dict(profile.variables).get("PATH", "")
    return [
        entry for entry in path.split(os.pathsep) if os.path.isabs(entry) and os.path.isdir(entry)
    ]


def _executable_file(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def resolve_program(root: Path, name: str, roots: Sequence[str]) -> str | None:
    """The absolute program for `name` per the documented order, or None. A program
    whose realpath is in the sandbox's writable set outside the workspace is never
    resolved (§9.5)."""
    found = _locate(root, name, roots)
    return None if found is None or sandbox.foreign_writable(found, root) else found


def _locate(root: Path, name: str, roots: Sequence[str]) -> str | None:
    if "/" in name and not os.path.isabs(name):
        inside = resolve_inside(name, root) if _relative(name) else None
        return str(inside) if inside is not None and _executable_file(str(inside)) else None
    if os.path.isabs(name):
        parent = os.path.normpath(os.path.dirname(name))
        allowed = {os.path.normpath(entry) for entry in roots}
        program = os.path.normpath(name)
        return program if parent in allowed and _executable_file(program) else None
    return shutil.which(name, path=os.pathsep.join(roots))


def _search_roots(env_bin: str | None, profile: profiles.Profile | None) -> list[str]:
    pinned = [os.path.expanduser(entry) for entry in execute.SEARCH_ROOTS]
    return [*([env_bin] if env_bin else []), *profile_path_dirs(profile), *pinned]


def _command(root: Path, args: Args, action: str, keys: frozenset[str]) -> Plan | str:
    """The shared part of `exec` and `process_start`: a Plan or a refusal reason."""
    unknown = sorted(set(args) - keys)
    if unknown:
        return f"unexpected argument: {_echo(unknown[0])}"
    argv = validate_argv(args.get("argv"))
    if isinstance(argv, str):
        return argv
    denied = command_deny.denied_reason(argv)
    if denied is not None:
        return denied
    cwd = _cwd(root, args)
    if cwd is None:
        return "cwd must be an existing directory inside the linked folder"
    environment = _environment(root, args)
    if isinstance(environment, str):
        return environment
    profile = _profile(root, args.get("profile"))
    if isinstance(profile, str):
        return profile
    program = resolve_program(root, argv[0], _search_roots(environment[1], profile))
    if program is None:
        return f"program not found in the allowed locations: {_echo(argv[0])}"
    resolved = (program, os.path.realpath(program))
    denied = command_deny.denied_reason(
        argv, resolved=resolved, inside=lambda path: _within(root, path)
    )
    if denied is not None:
        return denied
    if command_deny.shell_script(argv) and not _script_file(root, cwd, argv[1]):
        return SCRIPT_REFUSAL
    return Plan(
        action=action,
        ok=True,
        argv=[program, *argv[1:]],
        cwd=cwd,
        environment=environment[0],
        profile=profile,
    )


def _script_file(root: Path, cwd: str, script: str) -> bool:
    """§10.2: the shell's script (relative to `cwd`) is a regular file in the workspace."""
    resolved = resolve_inside(os.path.normpath(os.path.join(cwd, script)), root)
    return resolved is not None and resolved.is_file()


#: §10.1: programs that run project code whatever their arguments (except info-only
#: `--version`/`--help`). A denylist: anything not listed is judged by path and profile.
PROJECT_RUNNERS: frozenset[str] = frozenset(
    {
        "pytest",
        "py.test",
        "tox",
        "nox",
        "npm",
        "npx",
        "pnpm",
        "yarn",
        "bun",
        "deno",
        "cargo",
        "go",
        "make",
        "gmake",
        "ninja",
        "cmake",
        "ctest",
        "meson",
        "scons",
        "bazel",
        "bazelisk",
        "colcon",
        "catkin",
        "catkin_make",
        "rosrun",
        "roslaunch",
        "gradle",
        "gradlew",
        "mvn",
        "rake",
        "pdm",
        "rye",
        "pixi",
        "hatch",
        "just",
        "task",
        "invoke",
        "pre-commit",
    }
)
_CONDA = frozenset({"run", "install", "env"})
#: ...and programs that do so through one of these subcommands.
SUBCOMMAND_RUNNERS: dict[str, frozenset[str]] = {
    "ros2": frozenset({"run", "launch"}),
    "bundle": frozenset({"exec"}),
    "pip": frozenset({"install", "download", "wheel"}),
    "uv": frozenset({"sync", "pip", "run", "build", "tool"}),
    "poetry": frozenset({"install", "build", "run"}),
    "pipenv": frozenset({"run"}),
    "conda": _CONDA,
    "mamba": _CONDA,
    "micromamba": _CONDA,
    "platformio": frozenset({"run"}),
    "pio": frozenset({"run"}),
}
#: The only interpreter arguments that run no script or module.
INFO_FLAGS: frozenset[str] = frozenset({"--version", "-V", "-VV", "--help", "-h", "-v"})
#: Runner invocations made only of these print a version or help (`-v` is verbose for many).
RUNNER_INFO_FLAGS: frozenset[str] = frozenset({"--version", "-V", "--help", "-h"})
#: Profile variables whose entries decide what code a program loads (§10.1).
SEARCH_PATH_VARIABLES: frozenset[str] = frozenset(
    {
        "PATH",
        "PYTHONPATH",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "AMENT_PREFIX_PATH",
        "COLCON_PREFIX_PATH",
        "CMAKE_PREFIX_PATH",
        "ROS_PACKAGE_PATH",
        "NODE_PATH",
        "GEM_PATH",
        "PERL5LIB",
        "RUBYLIB",
        "CLASSPATH",
    }
)


def planned_program(root: Path, argv0: str, which: Which) -> str | None:
    """The path that will be executed for `argv0` (not following its final link)."""
    if os.path.isabs(argv0):
        return argv0
    if "/" in argv0:
        return os.path.normpath(os.path.join(root, argv0))
    return which(argv0)


def _runs_project_code(path: str, args: Sequence[str]) -> bool:
    name = command_deny.program_name(path, exact=True)
    if name in command_deny.INLINE_CODE:
        return not all(arg in INFO_FLAGS for arg in args)
    # Runners match their normalised name (`cmake3`, `pip3.12`) or exact basename (`ros2`).
    candidates = (name, os.path.basename(path).casefold())
    if any(candidate in PROJECT_RUNNERS for candidate in candidates):
        return not (args and all(arg in RUNNER_INFO_FLAGS for arg in args))
    return any(arg in SUBCOMMAND_RUNNERS.get(c, ()) for c in candidates for arg in args)


def _profile_reaches_workspace(root: Path, profile: profiles.Profile | None) -> bool:
    """A search-path variable of the applied profile has an entry in the workspace. An
    empty or relative entry means the working directory, which is in the workspace."""
    if profile is None:
        return False
    for name, value in profile.variables:
        if name not in SEARCH_PATH_VARIABLES:
            continue
        for entry in value.split(os.pathsep):
            if not os.path.isabs(entry) or _within(root, entry):
                return True
    return False


def program_scope(root: Path, planned: Plan, program: str | None) -> str:
    """§10.1: "workspace" when what runs is project code — the program's path (before
    or after following links) is in the workspace (any workspace venv's bin included);
    an explicit workspace venv or a profile search path into the workspace is applied;
    it is a §10.2 shell script, an interpreter given a script or module, a project
    runner, or a capture of a workspace setup file. Otherwise "system"."""
    argv = planned.argv
    names = [argv[0]]
    if program is not None:
        if _within(root, os.path.dirname(program)) or _within(root, program):
            return WORKSPACE_SCOPE
        names.append(os.path.realpath(program))
    uses_venv = planned.environment is not None and planned.action != "create_environment"
    setup = planned.setup_file
    if (
        uses_venv
        or _profile_reaches_workspace(root, planned.profile)
        or (setup is not None and _within(root, setup))
        or command_deny.shell_script(argv)
        or any(_runs_project_code(name, argv[1:]) for name in names)
    ):
        return WORKSPACE_SCOPE
    return SYSTEM_SCOPE


def _finish(action: str, planned: Plan | str, **fields: Any) -> Plan:
    if isinstance(planned, str):
        return _refuse(action, planned)
    return replace(planned, **fields)


def plan_exec(root: Path, args: Args, _which: Which) -> Plan:
    timeout = _bounded_int(
        args, "timeout_seconds", DEFAULT_EXEC_TIMEOUT_SECONDS, 1, MAX_EXEC_TIMEOUT_SECONDS
    )
    if timeout is None:
        return _refuse("exec", "timeout_seconds must be an integer from 1 to 600")
    return _finish("exec", _command(root, args, "exec", EXEC_KEYS), timeout_seconds=timeout)


def _label(value: object) -> str | None | bool:
    """The label, None when absent, False when invalid."""
    if value is None:
        return None
    if isinstance(value, str) and 1 <= len(value) <= MAX_LABEL_CHARS and value.isprintable():
        return value
    return False


def plan_process_start(root: Path, args: Args, _which: Which) -> Plan:
    action = "process_start"
    runtime = _bounded_int(
        args,
        "max_runtime_seconds",
        DEFAULT_RUNTIME_SECONDS,
        MIN_RUNTIME_SECONDS,
        MAX_RUNTIME_SECONDS,
    )
    if runtime is None:
        return _refuse(action, "max_runtime_seconds must be an integer from 60 to 14400")
    label = _label(args.get("name"))
    if label is False:
        return _refuse(action, "name must be 1 to 64 printable characters")
    planned = _command(root, args, action, PROCESS_KEYS)
    return _finish(action, planned, max_runtime_seconds=runtime, label=label or None)


def plan_profile_capture(root: Path, args: Args, _which: Which) -> Plan:
    action = "profile_capture"
    unknown = sorted(set(args) - CAPTURE_KEYS)
    if unknown:
        return _refuse(action, f"unexpected argument: {_echo(unknown[0])}")
    name = args.get("name")
    error = profiles.name_error(name)
    if error is not None:
        return _refuse(action, error)
    setup = profiles.resolve_setup_file(root, args.get("setup_file"))
    if isinstance(setup, profiles.Refusal):
        return _refuse(action, setup.reason)
    extends = _profile(root, args.get("extends"))
    if isinstance(extends, str):
        return _refuse(action, extends)
    return Plan(
        action=action,
        ok=True,
        argv=profiles.capture_argv(setup),
        timeout_seconds=profiles.CAPTURE_TIMEOUT_SECONDS,
        profile=extends,
        capture_name=str(name),
        setup_file=setup,
    )


COMMAND_PLANNERS: dict[str, Callable[[Path, Args, Which], Plan]] = {
    "exec": plan_exec,
    "process_start": plan_process_start,
    "profile_capture": plan_profile_capture,
}


def _within(root: Path, path: str) -> bool:
    """True when `path`'s realpath is the workspace or beneath it, judged by
    (st_dev, st_ino) ancestry so a case-insensitive filesystem cannot fool it.
    Missing trailing components are skipped (their existing ancestor decides)."""
    try:
        target = os.stat(root)
    except OSError:
        return False
    current = Path(os.path.realpath(path))
    for candidate in (current, *current.parents):
        try:
            info = os.stat(candidate)
        except FileNotFoundError:
            continue  # a not-yet-built path is judged by its nearest existing ancestor
        except OSError:
            return False
        if (info.st_dev, info.st_ino) == (target.st_dev, target.st_ino):
            return True
    return False
