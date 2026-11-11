"""Which Gazebo families are installed, and which one a world file wants.

Binaries are looked up ONLY in the directories `SOLUS_GAZEBO_PATH` names (absolute, existing),
never on the ambient PATH. Detection runs one fixed argv per family (RECON §2, verified on this
host 2026-11-09):

- new family:  ``gz sim --versions``        → ``8.15.0`` (major 7 Garden, 8 Harmonic, 9 Ionic,
  10 Jetty)
- ignition:    ``ign gazebo --versions``    → ``6.16.0`` (6 Fortress, 5 Edifice, 3 Citadel)
- classic:     ``gzserver --version``       → banner ``Gazebo multi-robot simulator, version
  11.15.1`` on STDOUT with exit 255. The classic ``gazebo`` wrapper is NEVER run (it hangs), and
  classic ``gz --version`` prints ``Invalid arguments`` on stderr, so it never reads as ``gz``.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

FamilyName = Literal["classic", "ignition", "gz"]

#: ``run(argv, timeout_s)`` → the child's STDOUT text whatever its exit status, or ``None`` when
#: the binary could not be executed or outlived the timeout. A non-zero exit is NOT a failure:
#: classic ``gzserver --version`` exits 255 while printing the banner the detector reads.
Runner = Callable[[list[str], float], str | None]

PROBE_TIMEOUT_S: Final = 5.0
_VERSION = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)\s*$", re.MULTILINE)
_CLASSIC_BANNER = re.compile(r"Gazebo multi-robot simulator, version (\d+\.\d+\.\d+)")
_RANK: Final[dict[str, int]] = {"classic": 0, "ignition": 1, "gz": 2}
_DISTROS: Final[dict[tuple[str, int], str]] = {
    ("gz", 7): "Garden",
    ("gz", 8): "Harmonic",
    ("gz", 9): "Ionic",
    ("gz", 10): "Jetty",
    ("ignition", 3): "Citadel",
    ("ignition", 5): "Edifice",
    ("ignition", 6): "Fortress",
}
#: (exe name, argv tail, family): probed in newest-first order inside every search dir.
_PROBES: Final[tuple[tuple[str, tuple[str, ...], FamilyName], ...]] = (
    ("gz", ("sim", "--versions"), "gz"),
    ("ign", ("gazebo", "--versions"), "ignition"),
    ("gzserver", ("--version",), "classic"),
)
_HINT_MAX_BYTES: Final = 1 << 20
#: Plugin FILENAMES decide before namespaces: Fortress 6.16's stock worlds load
#: ``ignition-gazebo-*`` plugins under ``gz::sim::systems::*`` names (P8 defect E).
_PLUGIN_HINTS: Final[tuple[tuple[re.Pattern[str], FamilyName], ...]] = (
    (re.compile(r"gz-sim\d*-"), "gz"),
    (re.compile(r"ignition-gazebo\d*-"), "ignition"),
    (re.compile(r"ignition::gazebo"), "ignition"),
    (re.compile(r"gz::sim"), "gz"),
    (re.compile(r'filename="lib[A-Za-z0-9_]+\.so"'), "classic"),
)
_SDF_VERSION = re.compile(r'<sdf\s+version="(\d+)\.(\d+)"')


@dataclass(frozen=True)
class Family:
    name: FamilyName
    version: str
    bin_dir: Path
    exe: Path

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])

    @property
    def distro(self) -> str | None:
        """Release name when the family has one (Harmonic, Fortress, …); classic has none."""
        return _DISTROS.get((self.name, self.major))


def gazebo_search_path(env: Mapping[str, str] | None = None) -> tuple[Path, ...]:
    """Absolute, existing, deduplicated dirs from ``SOLUS_GAZEBO_PATH``; never PATH."""
    raw = (os.environ if env is None else env).get("SOLUS_GAZEBO_PATH", "")
    dirs: list[Path] = []
    for entry in raw.split(os.pathsep):
        path = Path(entry)
        if entry and path.is_absolute() and path.is_dir() and path not in dirs:
            dirs.append(path)
    return tuple(dirs)


def subprocess_run(argv: list[str], timeout: float) -> str | None:
    """The production :data:`Runner`: argv list, no shell, stdout captured, stderr dropped."""
    try:
        done = subprocess.run(  # noqa: S603 — argv list from the pinned search path, no shell
            argv, capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode("utf-8", "replace")


def detect_families(search_path: Sequence[Path], run: Runner) -> tuple[Family, ...]:
    """Every family whose pinned binary answers from a search dir, in search order."""
    found: list[Family] = []
    for bin_dir in search_path:
        for exe_name, tail, family in _PROBES:
            exe = bin_dir / exe_name
            if not (exe.is_file() and os.access(exe, os.X_OK)):
                continue
            version = _parse_version(family, run([str(exe), *tail], PROBE_TIMEOUT_S))
            if version is not None:
                found.append(Family(name=family, version=version, bin_dir=bin_dir, exe=exe))
    return tuple(found)


def _parse_version(family: FamilyName, stdout: str | None) -> str | None:
    if not stdout:
        return None
    if family == "classic":
        banner = _CLASSIC_BANNER.search(stdout)
        return banner.group(1) if banner else None
    match = _VERSION.search(stdout)
    if match is None:
        return None
    major = int(match.group(1))
    if (family == "gz" and major < 7) or (family == "ignition" and major >= 7):
        return None
    return f"{match.group(1)}.{match.group(2)}.{match.group(3)}"


def newest(families: Sequence[Family]) -> Family | None:
    """gz over ignition over classic, then the highest version."""
    if not families:
        return None
    return max(families, key=lambda f: (_RANK[f.name], tuple(int(p) for p in f.version.split("."))))


def family_hint(data: bytes) -> FamilyName | None:
    """What the world file itself says: plugin filenames first, then plugin namespaces, then
    an SDF version ≥ 1.10 (gz only). Plain SDF without any is ambiguous → ``None``."""
    text = data[:_HINT_MAX_BYTES].decode("utf-8", "replace")
    for pattern, family in _PLUGIN_HINTS:
        if pattern.search(text):
            return family
    version = _SDF_VERSION.search(text)
    if version and (int(version.group(1)), int(version.group(2))) >= (1, 10):
        return "gz"
    return None


def family_for(world_file: Path, families: Sequence[Family]) -> Family | None:
    """The hinted family when installed, else the newest installed one (the caller reports
    which happened through :func:`family_hint`)."""
    hint = family_hint(_world_file_prefix(world_file))
    for family in families:
        if family.name == hint:
            return family
    return newest(families)


def _world_file_prefix(path: Path) -> bytes:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return b""
    try:
        return os.read(fd, _HINT_MAX_BYTES)
    except OSError:
        return b""
    finally:
        os.close(fd)
