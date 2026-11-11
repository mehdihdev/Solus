"""Which Gazebo family streams on this machine, and from which binary (SOLUSDEV-322 P3-T5).

Binaries resolve ONLY through the directories `SOLUS_GAZEBO_PATH` names (absolute, existing),
never the ambient PATH — the pinned-binary rule (CLAUDE.md §7). The detection chain mirrors the
companion fork's `family_detect.py` (RECON §2, verified on this host 2026-11-09):

- new family  ``gz sim --versions``      → ``8.15.0`` (Garden 7, Harmonic 8, Ionic 9, Jetty 10)
- ignition    ``ign gazebo --versions``  → ``6.16.0`` (Citadel 3, Edifice 5, Fortress 6)
- classic     ``gzserver --version``     → ``Gazebo multi-robot simulator, version 11.x`` on
  stdout with exit 255; the classic ``gazebo`` wrapper is never run (it hangs).

Classic and the new family both ship a ``gz``; classic is the one with ``gzserver`` beside it.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final, Literal

FamilyName = Literal["classic", "ignition", "gz"]
FAMILIES: Final[tuple[FamilyName, ...]] = ("gz", "ignition", "classic")  # newest first

PROBE_TIMEOUT_S: Final = 5.0
_PROBE_ARGV: Final[dict[FamilyName, tuple[str, ...]]] = {
    "gz": ("gz", "sim", "--versions"),
    "ignition": ("ign", "gazebo", "--versions"),
    "classic": ("gzserver", "--version"),
}
_STREAM_EXE: Final[dict[FamilyName, str]] = {"gz": "gz", "ignition": "ign", "classic": "gz"}
_DISK_MARKERS: Final[tuple[tuple[str, FamilyName], ...]] = (
    ("gzserver", "classic"),
    ("ign", "ignition"),
    ("gz", "gz"),
)
_VERSION = re.compile(r"^\s*(\d+)\.\d+\.\d+\s*$", re.MULTILINE)
_CLASSIC_BANNER = re.compile(r"Gazebo multi-robot simulator, version \d+\.\d+\.\d+")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
#: What a simulator child may see of this process's environment: the simulator's own variables
#: and the few a process needs to start. Database URLs, API keys and the rest never cross.
_FORWARDED_NAMES: Final = frozenset(
    {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "DISPLAY",
        "XDG_RUNTIME_DIR",
        "LD_LIBRARY_PATH",
        "SOLUS_GAZEBO_PATH",
        "SOLUS_SIM_ROOTS",
    }
)
_FORWARDED_PREFIXES: Final = ("GZ_", "IGN_", "GAZEBO_")

Runner = Callable[[list[str], float], str | None]


class GazeboNotAvailableError(RuntimeError):
    """No Gazebo binary of the wanted family under `SOLUS_GAZEBO_PATH`."""


def gazebo_bin_dirs(env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Absolute, existing, deduplicated dirs from `SOLUS_GAZEBO_PATH`; never PATH."""
    raw = (os.environ if env is None else env).get("SOLUS_GAZEBO_PATH", "")
    dirs: list[Path] = []
    for entry in raw.split(os.pathsep):
        path = Path(entry)
        if entry and path.is_absolute() and path.is_dir() and path not in dirs:
            dirs.append(path)
    return tuple(dirs)


def _has_exe(bin_dir: Path, name: str) -> bool:
    exe = bin_dir / name
    return exe.is_file() and os.access(exe, os.X_OK)


def _is_family_dir(bin_dir: Path, family: FamilyName) -> bool:
    if not _has_exe(bin_dir, _STREAM_EXE[family]):
        return False
    if family == "ignition":
        return True
    return _has_exe(bin_dir, "gzserver") == (family == "classic")


def find_exe(family: FamilyName, *, env: Mapping[str, str] | None = None) -> Path:
    """The streaming CLI (`gz` / `ign` / classic `gz`) for `family`, from the first search dir
    that holds it."""
    for bin_dir in gazebo_bin_dirs(env):
        if _is_family_dir(bin_dir, family):
            return bin_dir / _STREAM_EXE[family]
    raise GazeboNotAvailableError(
        f"no {family} Gazebo CLI under SOLUS_GAZEBO_PATH — set it to the simulator's bin dir"
    )


def _disk_family(bin_dir: Path) -> FamilyName | None:
    # Classic 11 alone ships `gzserver`; the `ign`/`gz` tool shims its conda/apt deps drop beside
    # it do not make the dir Fortress/Harmonic. ponytail: a dir holding two real families reads as
    # the older one — `detect_family` (subprocess probe) is the tie-breaker for a session.
    return next((f for exe, f in _DISK_MARKERS if _has_exe(bin_dir, exe)), None)


def family_on_disk(env: Mapping[str, str] | None = None) -> FamilyName | None:
    """File-only `detect_family`: the newest family whose CLIs sit under `SOLUS_GAZEBO_PATH`.
    Runs nothing — the `/bench/sources` listing must never spawn a simulator."""
    found = {_disk_family(d) for d in gazebo_bin_dirs(env)}
    return next((f for f in FAMILIES if f in found), None)


def simulator_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """The scrubbed environment every simulator subprocess (probe, topic echo, joint poll) runs
    under: `_FORWARDED_NAMES` plus `GZ_*` / `IGN_*` / `GAZEBO_*`, nothing else."""
    source = os.environ if env is None else env
    return {
        name: value
        for name, value in source.items()
        if name in _FORWARDED_NAMES or name.startswith(_FORWARDED_PREFIXES)
    }


def probe_stdout(argv: list[str], timeout: float) -> str | None:
    """argv list, no shell, scrubbed env, stdout captured whatever the exit status (classic
    exits 255)."""
    try:
        done = subprocess.run(  # noqa: S603 — argv list from the pinned search path, no shell
            argv, capture_output=True, timeout=timeout, check=False, env=simulator_env()
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode("utf-8", "replace")


def _answers(family: FamilyName, stdout: str | None) -> bool:
    if not stdout:
        return False
    pattern = _CLASSIC_BANNER if family == "classic" else _VERSION
    return pattern.search(stdout) is not None


def detect_family(
    *, env: Mapping[str, str] | None = None, run: Runner = probe_stdout
) -> FamilyName | None:
    """The newest installed family whose probe answers, or `None` when nothing does."""
    dirs = gazebo_bin_dirs(env)
    for family in FAMILIES:
        exe, *tail = _PROBE_ARGV[family]
        for bin_dir in dirs:
            if _has_exe(bin_dir, exe) and _answers(
                family, run([str(bin_dir / exe), *tail], PROBE_TIMEOUT_S)
            ):
                return family
    return None


def identifier_or_raise(value: str) -> str:
    """A plain world/model/joint identifier: never option-shaped, never text-format syntax."""
    if _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(f"unsafe name {value[:32]!r}")
    return value


def joint_state_topic(family: FamilyName, world: str, model: str) -> str | None:
    """Where the family publishes a model's joint state; classic has no such topic (it is polled
    through `gz model -i`, see `classic_source.py`)."""
    identifier_or_raise(world)
    identifier_or_raise(model)
    if family == "classic":
        return None
    return f"/world/{world}/model/{model}/joint_state"
