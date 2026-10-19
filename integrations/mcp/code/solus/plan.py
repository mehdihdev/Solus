"""`plan` (docs/api/code-environment.md §4): PURE argv assembly + validation.

Every gated tool calls `plan_action` first and executes exactly the argv it
returns — one source of truth for what the approval card shows and what
runs. Nothing here executes; the only I/O is `stat` on workspace paths
(existence, "is a venv", "does not exist yet") and the injected `which`.

Argv conventions (so no absolute machine path ever crosses the bridge):
paths are WORKSPACE-RELATIVE and run with `cwd` = the workspace; the venv
interpreter is `<env>/bin/python` (or `<env>/Scripts/python.exe`); a system
tool is its bare name (`uv`, `python3.12`), which `execute.py` resolves
against its pinned search roots — never the inherited PATH.
"""

import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from . import sandbox
from .profiles import Profile
from .workspace import is_safe_relative, resolve_inside

ACTIONS: tuple[str, ...] = (
    "create_environment",
    "install",
    "run",
    "test",
    "exec",
    "process_start",
    "profile_capture",
)
DEFAULT_ENVIRONMENT = ".venv"
DEFAULT_PYTHON = "3.12"
DEFAULT_TEST_TARGET = "tests"
MAX_PACKAGES = 64
MAX_PACKAGE_CHARS = 128
MAX_RUN_ARGS = 32
MAX_ARG_CHARS = 256
MAX_PATH_CHARS = 512
MAX_TIMEOUT_SECONDS = 600
DEFAULT_TIMEOUT_SECONDS = MAX_TIMEOUT_SECONDS
#: How much of a refused caller value is echoed back in `reason`.
MAX_ECHO = 64
UV = "uv"

_VERSION = re.compile(r"^3\.\d{1,2}$")
_OP = r"(?:===|~=|==|!=|<=|>=|<|>)[A-Za-z0-9.*+!_-]+"
_PACKAGE = re.compile(
    rf"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?(?:\[[A-Za-z0-9._,-]*\])?(?:{_OP}(?:,{_OP})*)?$"
)
_VENV_PYTHONS = ("bin/python", "Scripts/python.exe")
_FORBIDDEN_CHARS = ("\x00", "\n", "\r")

Which = Callable[[str], str | None]
Args = dict[str, Any]


@dataclass(frozen=True)
class Plan:
    """What an action would run. `answer()` is the §4 `plan` wire shape; the
    other fields drive `execute.py`."""

    action: str
    ok: bool
    argv: list[str] = field(default_factory=list)
    reason: str | None = None
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    #: Workspace-relative venv dir the child gets as VIRTUAL_ENV (+ PATH).
    environment: str | None = None
    #: `create_environment` only: the target path.
    path: str | None = None
    #: Workspace-relative working directory (`exec` / `process_start` may set it).
    cwd: str = "."
    #: The sandbox kind every executing action runs in (None only when refused).
    sandbox: str | None = None
    #: The profile applied to the child (`profile_capture`: the `extends` profile).
    profile: Profile | None = None
    #: `process_start`: the label and the runtime bound.
    label: str | None = None
    max_runtime_seconds: int | None = None
    #: `profile_capture`: the profile being captured and its resolved setup file.
    capture_name: str | None = None
    setup_file: str | None = None
    #: §10.1: "workspace" | "system" for an accepted plan, None when refused.
    program_scope: str | None = None

    def answer(self) -> dict[str, Any]:
        """The §2.2 wire shape: the argv plus sandbox, profile and environment."""
        box = None
        if self.ok and self.sandbox is not None:
            box = {
                "kind": self.sandbox,
                "writable": list(sandbox.WRITABLE_LABELS),
                "limitations": sandbox.limitations(self.sandbox),
            }
        profile = (
            {"name": self.profile.name, "digest": self.profile.digest} if self.profile else None
        )
        return {
            "argv": list(self.argv),
            "cwd": self.cwd,
            "ok": self.ok,
            "reason": self.reason,
            "sandbox": box,
            "profile": profile,
            "environment": self.environment,
            "program_scope": self.program_scope if self.ok else None,
        }


def _refuse(action: str, reason: str) -> Plan:
    return Plan(action=action, ok=False, reason=reason)


def _echo(value: object) -> str:
    return str(value)[:MAX_ECHO]


def _string(args: Args, key: str, default: str | None) -> str | None:
    value = args.get(key, default)
    return value if isinstance(value, str) else None


def _relative(value: str | None) -> bool:
    """A workspace-relative, traversal-free path that is not option-shaped."""
    return (
        isinstance(value, str)
        and len(value) <= MAX_PATH_CHARS
        and not value.startswith("-")
        and not any(char in value for char in _FORBIDDEN_CHARS)
        and is_safe_relative(value)
    )


def _timeout(args: Args) -> int | None:
    value = args.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if value is None:
        return DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if 1 <= value <= MAX_TIMEOUT_SECONDS else None


def venv_python(root: Path, environment: str) -> str | None:
    """The workspace-relative interpreter of `environment`, or None when the
    directory is missing, escapes the workspace, or is not a REAL venv.

    Security review C1/H2 (SOLUSDEV-250): a directory that merely contains
    `bin/python` is workspace content — a cloned repo can commit an executable
    there — so it is never run. A venv is recognised by its `pyvenv.cfg` AND
    by its interpreter resolving OUTSIDE the workspace (every venv links or
    copies the base interpreter; a planted script resolves inside)."""
    base = resolve_inside(environment, root)
    if base is None or not base.is_dir() or not (base / "pyvenv.cfg").is_file():
        return None
    for candidate in _VENV_PYTHONS:
        exe = base / candidate
        if not exe.exists():
            continue
        if Path(os.path.realpath(exe)).is_relative_to(root.resolve()):
            return None
        return f"{environment}/{candidate}"
    return None


def _environment(root: Path, args: Args) -> tuple[str, str] | str:
    """`(environment, venv_python)` or a refusal reason."""
    environment = _string(args, "environment", DEFAULT_ENVIRONMENT)
    if not _relative(environment):
        return "environment must be a relative path inside the linked folder"
    assert environment is not None  # narrowed by _relative
    python = venv_python(root, environment)
    if python is None:
        return f"no virtualenv found at {_echo(environment)} (create_environment first)"
    return environment, python


def validate_packages(value: object) -> list[str] | str:
    """The `install` package list, or a refusal reason: PEP 508
    name[extras][specifier] only — no `-` options, URLs, paths, whitespace."""
    if not isinstance(value, list) or not value:
        return "packages must be a non-empty list"
    if len(value) > MAX_PACKAGES:
        return f"at most {MAX_PACKAGES} packages per install"
    for item in value:
        if not isinstance(item, str):
            return "every package must be a string"
        if item.startswith("-"):
            return f"package may not start with '-': {_echo(item)}"
        if "://" in item:
            return f"URLs are not accepted as packages: {_echo(item)}"
        if "/" in item or "\\" in item:
            return f"paths are not accepted as packages: {_echo(item)}"
        if any(char.isspace() for char in item):
            return f"package may not contain whitespace: {_echo(item)}"
        if len(item) > MAX_PACKAGE_CHARS or _PACKAGE.match(item) is None:
            return f"not a PEP 508 name[extras][specifier]: {_echo(item)}"
    return list(value)


def _run_args(value: object) -> list[str] | str:
    if value is None:
        return []
    if not isinstance(value, list):
        return "args must be a list of strings"
    if len(value) > MAX_RUN_ARGS:
        return f"at most {MAX_RUN_ARGS} args"
    for item in value:
        if not isinstance(item, str) or len(item) > MAX_ARG_CHARS:
            return "every arg must be a string of at most 256 chars"
        if any(char in item for char in _FORBIDDEN_CHARS):
            return "args may not contain NUL or newline characters"
    return list(value)


def _plan_create(root: Path, args: Args, which: Which) -> Plan:
    action = "create_environment"
    path = _string(args, "path", DEFAULT_ENVIRONMENT)
    python = _string(args, "python", DEFAULT_PYTHON)
    if not _relative(path):
        return _refuse(action, "path must be a relative path inside the linked folder")
    assert path is not None
    if python is None or _VERSION.match(python) is None:
        return _refuse(action, "python must be a 3.X version")
    target = root / path
    if target.exists() or target.is_symlink():
        return _refuse(action, f"{_echo(path)} already exists")
    parent = str(PurePosixPath(path).parent)
    if parent != "." and resolve_inside(parent, root) is None:
        return _refuse(action, "path must be inside an existing folder of the linked folder")
    if which(UV) is not None:
        argv = [UV, "venv", "--python", python, path]
    else:
        interpreter = f"python{python}"
        if which(interpreter) is None:
            return _refuse(action, f"python {python} is not installed (no uv, no {interpreter})")
        argv = [interpreter, "-m", "venv", path]
    return Plan(action=action, ok=True, argv=argv, environment=path, path=path)


def _plan_install(root: Path, args: Args, which: Which) -> Plan:
    action = "install"
    packages = validate_packages(args.get("packages"))
    if isinstance(packages, str):
        return _refuse(action, packages)
    environment = _environment(root, args)
    if isinstance(environment, str):
        return _refuse(action, environment)
    env_dir, python = environment
    if which(UV) is not None:
        argv = [UV, "pip", "install", "--python", python, "--", *packages]
    else:
        argv = [python, "-m", "pip", "install", "--", *packages]
    return Plan(action=action, ok=True, argv=argv, environment=env_dir)


def _plan_run(root: Path, args: Args, _which: Which) -> Plan:
    action = "run"
    script = _string(args, "script", None)
    if not _relative(script):
        return _refuse(action, "script must be a relative path inside the linked folder")
    assert script is not None
    resolved = resolve_inside(script, root)
    if resolved is None or not resolved.is_file():
        return _refuse(action, f"script not found inside the linked folder: {_echo(script)}")
    run_args = _run_args(args.get("args"))
    if isinstance(run_args, str):
        return _refuse(action, run_args)
    timeout = _timeout(args)
    if timeout is None:
        return _refuse(
            action, f"timeout_seconds must be an integer from 1 to {MAX_TIMEOUT_SECONDS}"
        )
    environment = _environment(root, args)
    if isinstance(environment, str):
        return _refuse(action, environment)
    env_dir, python = environment
    return Plan(
        action=action,
        ok=True,
        argv=[python, script, *run_args],
        timeout_seconds=timeout,
        environment=env_dir,
    )


def _plan_test(root: Path, args: Args, _which: Which) -> Plan:
    action = "test"
    target = _string(args, "target", DEFAULT_TEST_TARGET)
    if not _relative(target):
        return _refuse(action, "target must be a relative path inside the linked folder")
    assert target is not None
    if resolve_inside(target, root) is None:
        return _refuse(action, f"target not found inside the linked folder: {_echo(target)}")
    timeout = _timeout(args)
    if timeout is None:
        return _refuse(
            action, f"timeout_seconds must be an integer from 1 to {MAX_TIMEOUT_SECONDS}"
        )
    environment = _environment(root, args)
    if isinstance(environment, str):
        return _refuse(action, environment)
    env_dir, python = environment
    return Plan(
        action=action,
        ok=True,
        argv=[python, "-m", "pytest", "-q", "--", target],
        timeout_seconds=timeout,
        environment=env_dir,
    )


_PLANNERS: dict[str, Callable[[Path, Args, Which], Plan]] = {
    "create_environment": _plan_create,
    "install": _plan_install,
    "run": _plan_run,
    "test": _plan_test,
}


def _planner(action: str) -> Callable[[Path, Args, Which], Plan] | None:
    if action in _PLANNERS:
        return _PLANNERS[action]
    # Imported lazily: command planning resolves programs against execute's roots.
    from .command_plan import COMMAND_PLANNERS

    return COMMAND_PLANNERS.get(action)


def plan_action(root: Path, action: object, args: object, *, which: Which) -> Plan:
    """The plan for `action` over untrusted `args`. Never raises on shape. Every
    executing action is refused unless an OS sandbox is available (§3), and when
    the workspace holds HOME or ~/.solus (§9.4)."""
    planner = _planner(action) if isinstance(action, str) else None
    if planner is None:
        return _refuse(_echo(action), f"unknown action; expected one of {', '.join(ACTIONS)}")
    assert isinstance(action, str)
    conflict = sandbox.home_conflict(root)
    if conflict is not None:
        return _refuse(action, conflict)
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return _refuse(action, "args must be an object")
    planned = planner(root, args, which)
    if not planned.ok:
        return planned
    kind, why = sandbox.available()
    if kind is None:
        return _refuse(action, f"sandbox unavailable: {why}")
    from .command_plan import program_scope

    return replace(planned, sandbox=kind, program_scope=program_scope(root, planned))
