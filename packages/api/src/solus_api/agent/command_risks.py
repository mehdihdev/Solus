"""Risk badges for a proposed command (SOLUSDEV-317, code-command-execution.md §4).

Pure table lookups. A risk is shown on the approval card; it never denies —
the person decides. Kept apart from the deny table in `command_policy` so the
mirrored, cross-checked part stays small.
"""

from __future__ import annotations

import enum
import re
from collections.abc import Mapping, Sequence
from typing import Final


class Risk(enum.StrEnum):
    """Badges on the approval card — never a denial. Order is display order."""

    NETWORK = "network"
    INSTALL = "install"
    DESTRUCTIVE = "destructive"
    HARDWARE = "hardware"
    REMOTE = "remote"
    PROJECT_SCRIPTS = "project_scripts"


_N, _I, _D, _H, _R, _P = (
    Risk.NETWORK,
    Risk.INSTALL,
    Risk.DESTRUCTIVE,
    Risk.HARDWARE,
    Risk.REMOTE,
    Risk.PROJECT_SCRIPTS,
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
    **dict.fromkeys(("make", "gmake", "ninja", "catkin_make", "gradle"), frozenset({_P})),
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
    ("git", "clone"): frozenset({_N}),
    ("git", "fetch"): frozenset({_N}),
    ("git", "pull"): frozenset({_N}),
    ("git", "ls-remote"): frozenset({_N}),
    ("git", "submodule"): frozenset({_N}),
    ("git", "push"): frozenset({_N, _R}),
    ("git", "clean"): frozenset({_D}),
    ("git", "rm"): frozenset({_D}),
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

_DEVICE: Final = re.compile(r"(?:^|[=:])/dev/(?:tty|cu\.|ttyUSB|ttyACM|serial)")
_REMOTE_TARGET: Final = re.compile(r"^[A-Za-z0-9._-]+@?[A-Za-z0-9._-]*:")


def _first_positional(args: Sequence[str]) -> str | None:
    return next((arg for arg in args if not arg.startswith("-")), None)


def _argument_risks(name: str, args: Sequence[str]) -> set[Risk]:
    risks: set[Risk] = set()
    if any(_DEVICE.search(arg) for arg in args):
        risks.add(_H)
    if name in ("scp", "rsync") and any(_REMOTE_TARGET.match(arg) for arg in args):
        risks.add(_R)
    if name == "git" and "reset" in args and "--hard" in args:
        risks.add(_D)
    if name == "cmake" and "--build" in args:
        risks.add(_P)
    if name in ("pio", "platformio") and "upload" in args:
        risks.add(_H)
    if name == "find" and any(arg in ("-delete", "-exec", "-execdir") for arg in args):
        risks.add(_D)
    return risks


def risks_for(name: str, argv: Sequence[str]) -> tuple[Risk, ...]:
    """Badges for `argv` whose program name is `name` (see `program_name`)."""
    program, args = argv[0], argv[1:]
    risks: set[Risk] = set(_PROGRAM_RISKS.get(name, frozenset()))
    sub = _first_positional(args)
    if sub is not None:
        risks |= _SUBCOMMAND_RISKS.get((name, sub), frozenset())
    risks |= _argument_risks(name, args)
    if "/" in program and not program.startswith("/"):
        risks.add(_P)  # a workspace-relative executable is project code
    return tuple(risk for risk in Risk if risk in risks)
