"""`probe_environment` (docs/api/code-environment.md §4): read-only.

System interpreters via `which` over a fixed name list (resolved against the
pinned search roots in `execute.py`, never the inherited PATH), versions via
argv `[exe, "--version"]` with a 10 s timeout, the workspace venv = the
first of `.venv`/`venv`/`env` that is a real venv, conda envs via
`[conda, "env", "list", "--json"]` (≤ 32 names).

The workspace venv is NEVER executed (docs/api/code-command-execution.md §9.1):
its interpreter, pip and `uv pip list` would import workspace content (`.pth`
files, `sitecustomize`). Its packages are read from
`site-packages/*.dist-info/METADATA` (Name/Version headers; bounded entries,
bytes and ≤ 300 packages + `truncated`) and its Python version from
`pyvenv.cfg`. Every probe is injectable, every failure reads as null/empty, and
nothing here raises. Interpreter `path`s are absolute (the contract's shape);
the venv is reported by its workspace-relative name.
"""

import json
import logging
import os
import re
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .execute import CHILD_PATH, PASSTHROUGH_NAMES, _kill_group, pinned_which, search_path
from .plan import _relative, venv_python
from .workspace import resolve_inside

logger = logging.getLogger("solus.code.probe")

INTERPRETER_NAMES: tuple[str, ...] = ("python3", "python3.12", "python3.11", "python3.10", "python")
VENV_DIR_NAMES: tuple[str, ...] = (".venv", "venv", "env")
MAX_INTERPRETERS = 8
MAX_PACKAGES = 300
MAX_CONDA_ENVS = 32
VERSION_TIMEOUT_SECONDS = 10
#: site-packages directory entries scanned per venv (all site dirs together).
MAX_SITE_ENTRIES = 4096
#: Site-packages directories considered (`lib/python3.X/site-packages`, `Lib/…`).
MAX_SITE_DIRS = 4
#: Bytes read from one METADATA / pyvenv.cfg file (headers come first).
MAX_METADATA_BYTES = 64 * 1024
#: Captured stdout is cut here before parsing (conda env list, --version).
MAX_CAPTURE_BYTES = 1024 * 1024
#: Under the cloud's 40-char entropic-redaction threshold.
MAX_WIRE_CHARS = 39
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")

Which = Callable[[str], str | None]
Capture = Callable[[list[str], int], str | None]


def _probe_env() -> dict[str, str]:
    env = {name: os.environ[name] for name in PASSTHROUGH_NAMES if os.environ.get(name)}
    return {**env, "PATH": f"{search_path()}{os.pathsep}{CHILD_PATH}"}


def run_capture(argv: list[str], timeout_seconds: int) -> str | None:
    """stdout of a successful argv run (bounded), else None. Never raises.
    A timeout kills the whole process group (own session), not just the child."""
    try:
        proc = subprocess.Popen(  # noqa: S603 - fixed argv over probed absolute binaries
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=_probe_env(),
            start_new_session=True,
            close_fds=True,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    try:
        stdout, _ = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        proc.communicate()
        return None
    if proc.returncode != 0:
        return None
    return stdout[:MAX_CAPTURE_BYTES].decode("utf-8", errors="replace")


def _version(executable: str, capture: Capture) -> str | None:
    text = capture([executable, "--version"], VERSION_TIMEOUT_SECONDS)
    match = _VERSION.search(text or "")
    return match.group() if match else None


def _interpreters(which: Which, capture: Capture) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in INTERPRETER_NAMES:
        if len(found) == MAX_INTERPRETERS:
            break
        path = which(name)
        if path is None:
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        version = _version(path, capture)
        if version is None:
            continue
        seen.add(real)
        found.append({"path": path, "version": version})
    return found


def _read_small(path: Path) -> str | None:
    """A regular, non-symlinked file's first MAX_METADATA_BYTES as text, else None."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        return os.read(descriptor, MAX_METADATA_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return None
    finally:
        os.close(descriptor)


def _headers(text: str) -> dict[str, str]:
    """The first `Name`/`Version` of an RFC 822 header block (stops at the body)."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            break
        key, separator, value = line.partition(":")
        key = key.strip().casefold()
        if separator and key in ("name", "version") and key not in found:
            found[key] = value.strip()
    return found


def _site_dirs(base: Path) -> list[Path]:
    """`lib/python*/site-packages` and `Lib/site-packages`, real dirs inside `base`."""
    candidates = sorted(base.glob("lib/python*/site-packages")) + [base / "Lib" / "site-packages"]
    found: list[Path] = []
    for candidate in candidates[:MAX_SITE_DIRS]:
        if not candidate.is_symlink() and candidate.is_dir():
            if Path(os.path.realpath(candidate)).is_relative_to(base):
                found.append(candidate)
    return found


def _dist_infos(sites: list[Path]) -> tuple[list[Path], bool]:
    """`*.dist-info` directories (never via a symlink), and whether the scan was cut."""
    infos: list[Path] = []
    scanned = 0
    for site in sites:
        try:
            entries = sorted(os.scandir(site), key=lambda entry: entry.name)
        except OSError:
            continue
        for entry in entries:
            scanned += 1
            if scanned > MAX_SITE_ENTRIES:
                return infos, True
            if entry.name.endswith(".dist-info") and entry.is_dir(follow_symlinks=False):
                infos.append(Path(entry.path))
    return infos, False


def _packages(base: Path) -> tuple[list[dict[str, str]], bool]:
    """The venv's installed distributions read from disk; `truncated` when the list
    is cut, shortened, or a distribution's metadata is unreadable."""
    infos, truncated = _dist_infos(_site_dirs(base))
    found: dict[str, dict[str, str]] = {}
    for info in infos:
        headers = _headers(_read_small(info / "METADATA") or "")
        name, version = headers.get("name"), headers.get("version")
        if not name or not version:
            truncated = True
            continue
        truncated |= len(name) > MAX_WIRE_CHARS or len(version) > MAX_WIRE_CHARS
        found.setdefault(
            name.casefold(), {"name": name[:MAX_WIRE_CHARS], "version": version[:MAX_WIRE_CHARS]}
        )
    packages = [found[key] for key in sorted(found)]
    if len(packages) > MAX_PACKAGES:
        return packages[:MAX_PACKAGES], True
    return packages, truncated


def _cfg_version(base: Path) -> str | None:
    """`version` / `version_info` from `pyvenv.cfg` (never by running the interpreter)."""
    for line in (_read_small(base / "pyvenv.cfg") or "").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip().casefold() in ("version", "version_info"):
            match = _VERSION.match(value.strip())
            if match:
                return match.group()
    return None


def _venv(root: Path, environment: str | None) -> dict[str, Any] | None:
    if environment is not None and not _relative(environment):
        return None
    for name in VENV_DIR_NAMES if environment is None else (environment,):
        if venv_python(root, name) is None:
            continue
        base = resolve_inside(name, root)
        if base is None:
            return None
        packages, truncated = _packages(base)
        return {
            "path": name,
            "python_version": _cfg_version(base),
            "packages": packages,
            "truncated": truncated,
        }
    return None


def _conda(which: Which, capture: Capture) -> dict[str, Any] | None:
    path = which("conda")
    if path is None:
        return None
    text = capture([path, "env", "list", "--json"], VERSION_TIMEOUT_SECONDS)
    try:
        listed = json.loads(text or "{}")
    except ValueError:
        listed = {}
    envs = listed.get("envs") if isinstance(listed, dict) else None
    names = [
        Path(item).name[:MAX_WIRE_CHARS]
        for item in (envs if isinstance(envs, list) else [])
        if isinstance(item, str) and item
    ]
    return {"path": path, "envs": names[:MAX_CONDA_ENVS]}


def _uv(which: Which, capture: Capture) -> dict[str, str] | None:
    path = which("uv")
    if path is None:
        return None
    version = _version(path, capture)
    return {"path": path, "version": version} if version else None


def empty_probe() -> dict[str, Any]:
    return {"python": None, "interpreters": [], "venv": None, "conda": None, "uv": None}


def _guard(name: str, body: Callable[[], Any], fallback: Any) -> Any:
    try:
        return body()
    except Exception as exc:  # noqa: BLE001 - a failing probe reads as "not there"
        logger.warning("probe %s failed: %s", name, type(exc).__name__)
        return fallback


def probe_environment(
    root: Path,
    *,
    environment: str | None = None,
    which: Which = pinned_which,
    capture: Capture = run_capture,
) -> dict[str, Any]:
    """The §4 `probe_environment` shape. Never raises."""
    interpreters = _guard("interpreters", lambda: _interpreters(which, capture), [])
    return {
        "python": interpreters[0] if interpreters else None,
        "interpreters": interpreters,
        "venv": _guard("venv", lambda: _venv(root, environment), None),
        "conda": _guard("conda", lambda: _conda(which, capture), None),
        "uv": _guard("uv", lambda: _uv(which, capture), None),
    }
