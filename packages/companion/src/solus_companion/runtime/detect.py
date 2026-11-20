"""Interpreter detection — mcp-fork-runtime.md §3 step 1 and the `detect`
subcommand.

Candidates come from PATH, the Windows `py` launcher and PEP 514 registry,
well-known install locations (python.org, Homebrew, pyenv, conda) and the
Solus-managed root. Each is deduped by resolved path and probed argv-only;
nothing found here is trusted until a fork env built from it passes §5."""

import importlib
import ntpath
import os
import posixpath
import re
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from solus_companion.runtime.probe import (
    PROBE_TIMEOUT_SECONDS,
    Verdict,
    is_store_alias,
    judge,
    run_probe,
)
from solus_companion.runtime.proc import Runner, scrubbed_env
from solus_companion.runtime.protocol import CandidateLine

Source = Literal["path", "py_launcher", "registry", "known_location", "managed"]

SUPPORTED_MINORS = ("3.13", "3.12")
_PATH_NAMES = ("python3.13", "python3.12", "python3", "python")
_CONDA_DIRS = ("miniconda3", "anaconda3", "miniforge3")
_XCODE_STUB = "/usr/bin/python3"
_PY_LAUNCHER_LINE = re.compile(r"^\s*-\S+\s+(?:\*\s+)?(.+?\.exe)\s*$", re.IGNORECASE)
_REGISTRY_ROOTS = (r"Software\Python\PythonCore", r"Software\WOW6432Node\Python\PythonCore")


def _no_registry() -> list[str]:
    return []


@dataclass(frozen=True)
class HostView:
    """What detection may look at. `system_root` is `/` on POSIX (tests point
    it into a sandbox) and the Windows directory on win32 (`py.exe` lives there)."""

    platform: str
    env: Mapping[str, str]
    home: Path
    system_root: Path = Path("/")
    registry: Callable[[], list[str]] = field(default=_no_registry)

    @classmethod
    def current(cls) -> "HostView":
        platform: str = sys.platform
        if platform == "win32":
            return cls(
                platform=platform,
                env=dict(os.environ),
                home=Path.home(),
                system_root=Path(os.environ.get("SYSTEMROOT", r"C:\Windows")),
                registry=lambda: windows_registry_pythons(_load_winreg()),
            )
        return cls(platform=platform, env=dict(os.environ), home=Path.home())


@dataclass(frozen=True)
class Candidate:
    path: str
    source: Source
    verdict: Verdict

    def to_line(self) -> CandidateLine:
        return CandidateLine(
            path=self.path,
            version=self.verdict.version,
            implementation=self.verdict.implementation,
            source=self.source,
            supported=self.verdict.supported,
            reason=self.verdict.reason,
        )


def _unprobeable_xcode_stub(path: str, host: HostView) -> bool:
    """Running the stub with no developer tools pops Apple's install dialog."""
    if host.platform != "darwin" or path != _XCODE_STUB:
        return False
    root = host.system_root
    tools = (
        root / "Library" / "Developer" / "CommandLineTools",
        root / "Applications" / "Xcode.app",
    )
    return not any(tool.exists() for tool in tools)


def assess(path: str, source: Source, runner: Runner, host: HostView) -> Candidate:
    if is_store_alias(path):
        return Candidate(path, source, Verdict(False, "python_store_alias", None, "unknown"))
    if _unprobeable_xcode_stub(path, host):
        return Candidate(
            path, source, Verdict(False, "python_unsupported_version", None, "unknown")
        )
    report = run_probe(path, runner, scrubbed_env(host.env, host.platform))
    return Candidate(path, source, judge(report))


def best_candidate(candidates: Sequence[Candidate]) -> Candidate | None:
    """The first supported one, preferring 3.12 (the locks are compiled for it)."""
    supported = [c for c in candidates if c.verdict.supported]
    supported.sort(key=lambda c: not (c.verdict.version or "").startswith("3.12."))
    return supported[0] if supported else None


def parse_py_launcher(output: str) -> list[str]:
    """`py -0p` lines → interpreter paths (both the 3.11+ and the older format)."""
    found = []
    for line in output.splitlines():
        match = _PY_LAUNCHER_LINE.match(line)
        if match is not None:
            found.append(match.group(1))
    return found


def _reg_value(key: Any, winreg: Any, name: str) -> str:
    try:
        value, _kind = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return value if isinstance(value, str) else ""


def _registry_tags(winreg: Any, hive: Any, base: str) -> Iterator[str]:
    try:
        root = winreg.OpenKey(hive, base)
    except OSError:
        return
    with root:
        index = 0
        while True:
            try:
                tag = winreg.EnumKey(root, index)
            except OSError:
                return
            index += 1
            try:
                with winreg.OpenKey(root, tag + "\\InstallPath") as install:
                    executable = _reg_value(install, winreg, "ExecutablePath")
                    folder = _reg_value(install, winreg, "")
            except OSError:
                continue
            if executable:
                yield executable
            elif folder:
                yield ntpath.join(folder, "python.exe")


def windows_registry_pythons(winreg: Any | None) -> list[str]:
    """PEP 514: HKCU and HKLM `Software\\Python\\PythonCore\\<tag>\\InstallPath`."""
    if winreg is None:
        return []
    found: list[str] = []
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for base in _REGISTRY_ROOTS:
            found.extend(p for p in _registry_tags(winreg, hive, base) if p not in found)
    return found


def _load_winreg() -> Any | None:  # pragma: no cover — only importable on Windows
    try:
        return importlib.import_module("winreg")
    except ImportError:
        return None


class Detector:
    def __init__(self, runner: Runner, host: HostView, *, managed_root: Path | None = None):
        self._runner = runner
        self._host = host
        self._managed_root = managed_root

    def detect(self) -> list[Candidate]:
        seen: set[str] = set()
        candidates: list[Candidate] = []
        for path, source in self._raw():
            key = os.path.normcase(os.path.realpath(path))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(assess(path, source, self._runner, self._host))
        return candidates

    def _raw(self) -> Iterator[tuple[str, Source]]:
        yield from ((p, "path") for p in self._on_path())
        if self._host.platform == "win32":
            yield from ((p, "py_launcher") for p in self._py_launcher())
            yield from ((p, "registry") for p in self._host.registry())
        yield from ((str(p), "known_location") for p in self._known() if p.is_file())
        yield from ((str(p), "managed") for p in self._managed() if p.is_file())

    def _on_path(self) -> Iterator[str]:
        windows = self._host.platform == "win32"
        isabs = ntpath.isabs if windows else posixpath.isabs
        entries = self._host.env.get("PATH", "").split(";" if windows else ":")
        # A relative entry (`.`, `bin`) resolves against the cwd: never probe it.
        dirs = [d for d in entries if d and isabs(d)]
        for name in _PATH_NAMES:
            for directory in dirs:
                candidate = Path(directory) / (name + ".exe" if windows else name)
                if candidate.is_file():
                    yield str(candidate)

    def _py_launcher(self) -> list[str]:
        local = self._host.env.get("LOCALAPPDATA", "")
        launchers = [self._host.system_root / "py.exe"]
        if local:
            launchers.append(Path(local) / "Programs" / "Python" / "Launcher" / "py.exe")
        for launcher in launchers:
            if launcher.is_file():
                env = scrubbed_env(self._host.env, self._host.platform)
                result = self._runner(
                    [str(launcher), "-0p"], timeout=PROBE_TIMEOUT_SECONDS, env=env
                )
                return parse_py_launcher(result.stdout) if result.ok else []
        return []

    def _known(self) -> Iterator[Path]:
        host = self._host
        if host.platform == "win32":
            yield from self._known_windows()
            return
        root = host.system_root
        for minor in SUPPORTED_MINORS:
            name = f"python{minor}"
            if host.platform == "darwin":
                yield root / "Library/Frameworks/Python.framework/Versions" / minor / "bin" / name
                yield root / "opt/homebrew/bin" / name
                yield root / "opt/homebrew/opt" / f"python@{minor}" / "bin" / name
            else:
                yield root / "usr/bin" / name
            yield root / "usr/local/bin" / name
            yield from sorted(host.home.glob(f".pyenv/versions/{minor}.*/bin/python3"))
        for conda in _CONDA_DIRS:
            yield host.home / conda / "bin" / "python3"

    def _known_windows(self) -> Iterator[Path]:
        bases = [self._host.env.get(k, "") for k in ("LOCALAPPDATA", "ProgramFiles")]
        for minor in SUPPORTED_MINORS:
            folder = "Python" + minor.replace(".", "")
            if bases[0]:
                yield Path(bases[0]) / "Programs" / "Python" / folder / "python.exe"
            if bases[1]:
                yield Path(bases[1]) / folder / "python.exe"

    def _managed(self) -> Iterator[Path]:
        if self._managed_root is None or not self._managed_root.is_dir():
            return
        relative = "python/python.exe" if self._host.platform == "win32" else "python/bin/python3"
        for release in sorted(self._managed_root.iterdir()):
            if not release.name.startswith("."):
                yield release / relative
