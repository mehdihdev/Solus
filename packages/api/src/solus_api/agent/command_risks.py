"""Risk badges for a proposed command (SOLUSDEV-317, code-command-execution.md §4).

Pure table lookups. A risk is shown on the approval card; it never denies —
the person decides. Kept apart from the deny table in `command_policy` so the
mirrored, cross-checked part stays small.
"""

from __future__ import annotations

import enum
import posixpath
import re
from collections.abc import Mapping, Sequence
from typing import Final

from solus_api.agent.command_names import INTERPRETERS, normalise


class Risk(enum.StrEnum):
    """Badges on the approval card — never a denial. Order is display order."""

    NETWORK = "network"
    INSTALL = "install"
    DESTRUCTIVE = "destructive"
    HARDWARE = "hardware"
    REMOTE = "remote"
    PROJECT_SCRIPTS = "project_scripts"
    #: Security review 2026-10-18 item 6: an allowed program that runs a shell
    #: or arbitrary code from its arguments or configuration.
    RUNS_SHELL = "runs_shell"


_N, _I, _D, _H, _R, _P, _S = (
    Risk.NETWORK,
    Risk.INSTALL,
    Risk.DESTRUCTIVE,
    Risk.HARDWARE,
    Risk.REMOTE,
    Risk.PROJECT_SCRIPTS,
    Risk.RUNS_SHELL,
)

#: Programs that carry a risk whatever their arguments.
_PROGRAM_RISKS: Final[Mapping[str, frozenset[Risk]]] = {
    **dict.fromkeys(("curl", "wget", "nc", "ncat", "ping", "ftp", "http"), frozenset({_N})),
    **dict.fromkeys(("ssh", "scp", "sftp", "rsync", "telnet", "mosh"), frozenset({_N, _R})),
    **dict.fromkeys(
        ("rm", "rmdir", "dd", "mkfs", "shred", "truncate", "wipefs", "fdisk"), frozenset({_D})
    ),
    **dict.fromkeys(
        (
            "avrdude",
            "esptool",
            "esptool.py",
            "dfu-util",
            "openocd",
            "st-flash",
            "picotool",
            "stm32flash",
            "bossac",
            "teensy_loader_cli",
            "stty",
            "minicom",
            "picocom",
        ),
        frozenset({_H}),
    ),
    **dict.fromkeys(("awk", "gawk", "mawk", "nawk"), frozenset({_S})),
}

#: (program, first positional) pairs.
_SUBCOMMAND_RISKS: Final[Mapping[tuple[str, str], frozenset[Risk]]] = {
    **{(p, s): frozenset({_N, _I}) for p in ("pip", "pip3") for s in ("install", "download")},
    **{
        (p, s): frozenset({_N, _I})
        for p in ("npm", "pnpm", "yarn", "bun")
        for s in ("install", "i", "ci", "add")
    },
    **{(p, s): frozenset({_P}) for p in ("npm", "pnpm", "yarn", "bun") for s in ("run", "exec")},
    **{(p, "install"): frozenset({_N, _I}) for p in ("apt", "apt-get", "brew", "conda", "mamba")},
    **{(p, "install"): frozenset({_N, _I}) for p in ("gem", "cargo", "go", "rosdep")},
    ("go", "get"): frozenset({_N, _I}),
    ("uv", "add"): frozenset({_N, _I}),
    ("uv", "sync"): frozenset({_N, _I}),
    ("uv", "pip"): frozenset({_N, _I}),
    ("docker", "pull"): frozenset({_N}),
    ("docker", "push"): frozenset({_N, _R}),
    ("docker", "run"): frozenset({_P}),
    ("colcon", "build"): frozenset({_P}),
    ("colcon", "test"): frozenset({_P}),
    ("catkin", "build"): frozenset({_P}),
    ("ros2", "launch"): frozenset({_P}),
    ("ros2", "run"): frozenset({_P}),
    ("arduino-cli", "upload"): frozenset({_H}),
    ("arduino-cli", "burn-bootloader"): frozenset({_H}),
}

#: Security review 2026-10-19 (§10.1): system programs that run PROJECT code
#: (tests, build scripts, package scripts, workspace-pinned toolchains) whatever
#: their arguments — `--version`/`--help` included.
_PROJECT_RUNNERS: Final = frozenset(
    {"pytest", "py.test", "tox", "nox", "npm", "npx", "pnpm", "yarn", "bun", "deno"}
    | {"cargo", "go", "make", "gmake", "ninja", "colcon", "catkin", "catkin_make"}
    | {"gradle", "gradlew", "mvn", "rake", "ctest", "meson", "scons", "bazel", "bazelisk"}
    | {"cmake", "hatch"}
    | {"pdm", "rye", "pixi", "rosrun", "roslaunch", "just", "task", "invoke", "pre-commit"}
)
#: Runners that run project code only through one subcommand.
_RUN_SUBCOMMANDS: Final[Mapping[str, frozenset[str]]] = {
    "ros2": frozenset({"run", "launch"}),
    "bundle": frozenset({"exec"}),
    "pipenv": frozenset({"run"}),
    **dict.fromkeys(("pip", "pip3"), frozenset({"install", "download", "wheel"})),
    "uv": frozenset({"sync", "pip", "run", "build", "tool"}),
    "poetry": frozenset({"install", "build", "run"}),
    **dict.fromkeys(("conda", "mamba", "micromamba"), frozenset({"run", "install", "env"})),
    **dict.fromkeys(("pio", "platformio"), frozenset({"run", "test"})),
}
_INFO_ONLY: Final = frozenset({"--version", "-V", "-v", "version", "--help", "-h", "help"})
_INTERPRETER_NAMES: Final = frozenset(INTERPRETERS.values())

_DEVICE: Final = re.compile(r"(?:^|[=:])/dev/(?:tty|cu\.|ttyUSB|ttyACM|serial)")
_REMOTE_TARGET: Final = re.compile(r"^[A-Za-z0-9._-]+@?[A-Za-z0-9._-]*:")


#: `python -m <module>` risks (security review item 5).
_PYTHON_MODULES: Final[Mapping[str, frozenset[Risk]]] = {
    "pip": frozenset({_N, _I}),
    "pip3": frozenset({_N, _I}),
    "venv": frozenset({_I}),
    "virtualenv": frozenset({_I}),
    "ensurepip": frozenset({_I}),
    "http.server": frozenset({_N}),
}
_FIND_EXEC: Final = frozenset({"-exec", "-execdir", "-ok", "-okdir"})
_SED_EXEC: Final = re.compile(
    r"(?:^|[;{}\n0-9$/]\s*)e(?:\s|;|$)|^s(.)(?:\\.|(?!\1).)*\1(?:\\.|(?!\1).)*\1[A-Za-z0-9]*e"
)


def _first_positional(args: Sequence[str]) -> str | None:
    return next((arg for arg in args if not arg.startswith("-")), None)


def _sed_runs_shell(args: Sequence[str]) -> bool:
    scripts = [arg for arg in args if not arg.startswith("-")]
    scripts += [args[i + 1] for i, a in enumerate(args[:-1]) if a in ("-e", "--expression")]
    return any(_SED_EXEC.search(script) for script in scripts)


def _info_only(args: Sequence[str]) -> bool:
    return bool(args) and all(arg in _INFO_ONLY for arg in args)


def _runs_project_code(name: str, args: Sequence[str]) -> bool:
    """An interpreter given a script/module/file, a project runner (even for
    `--version`/`--help`: plugins and toolchains load from workspace files), or
    a subcommand-gated tool's running subcommand."""
    if name in _PROJECT_RUNNERS:
        return True
    if name in _INTERPRETER_NAMES:
        return not _info_only(args) and (
            "-m" in args or any(not arg.startswith("-") for arg in args)
        )
    sub = _first_positional(args)
    return sub is not None and sub in _RUN_SUBCOMMANDS.get(name, frozenset())


def _runs_shell(name: str, args: Sequence[str]) -> bool:
    if name == "find":
        return any(arg in _FIND_EXEC for arg in args)
    return name in ("sed", "gsed") and _sed_runs_shell(args)


def _argument_risks(name: str, args: Sequence[str]) -> set[Risk]:
    risks: set[Risk] = set()
    if any(_DEVICE.search(arg) for arg in args):
        risks.add(_H)
    if name in ("scp", "rsync") and any(_REMOTE_TARGET.match(arg) for arg in args):
        risks.add(_R)
    if _runs_project_code(name, args):
        risks.add(_P)
    if name in ("pio", "platformio") and "upload" in args:
        risks.add(_H)
    if name == "find" and "-delete" in args:
        risks.add(_D)
    if name == "python" and "-m" in args[:-1]:
        risks |= _PYTHON_MODULES.get(args[args.index("-m") + 1], frozenset())
    if _runs_shell(name, args):
        risks.add(_S)
    return risks


def _risks_named(name: str, args: Sequence[str]) -> set[Risk]:
    risks: set[Risk] = set(_PROGRAM_RISKS.get(name, frozenset()))
    sub = _first_positional(args)
    if sub is not None:
        risks |= _SUBCOMMAND_RISKS.get((name, sub), frozenset())
    return risks | _argument_risks(name, args)


def risks_for(argv: Sequence[str]) -> tuple[Risk, ...]:
    """Badges for `argv`, judged under both the literal (lower-cased) basename
    and its normalised spelling (`pip3.12` → `pip`, `RM` → `rm`)."""
    program, args = argv[0], argv[1:]
    risks: set[Risk] = set()
    for name in {posixpath.basename(program).lower(), normalise(program)}:
        risks |= _risks_named(name, args)
    if "/" in program and not program.startswith("/"):
        risks.add(_P)  # a workspace-relative executable is project code
    return tuple(risk for risk in Risk if risk in risks)
