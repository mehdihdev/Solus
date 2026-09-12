"""`probe_environment` (docs/api/code-environment.md §4): read-only.

Interpreters via `which` over a fixed name list (resolved against the
pinned search roots in `execute.py`, never the inherited PATH), versions via
argv `[exe, "--version"]` with a 10 s timeout, the workspace venv = the
first of `.venv`/`venv`/`env` that carries an interpreter, its packages via
`[venv_python, "-m", "pip", "list", "--format", "json"]`, or
`uv pip list --python <venv_python>` when the venv has no pip (60 s, ≤ 300 +
`truncated`), conda envs via `[conda, "env", "list", "--json"]` (≤ 32
names). Every probe is injectable, every failure reads as null/empty, and
nothing here raises. Interpreter `path`s are absolute (the contract's
shape); the venv is reported by its workspace-relative name.
"""

import json
import logging
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .execute import CHILD_PATH, PASSTHROUGH_NAMES, _kill_group, pinned_which, search_path
from .plan import _relative, venv_python

logger = logging.getLogger("solus.code.probe")

INTERPRETER_NAMES: tuple[str, ...] = ("python3", "python3.12", "python3.11", "python3.10", "python")
VENV_DIR_NAMES: tuple[str, ...] = (".venv", "venv", "env")
MAX_INTERPRETERS = 8
MAX_PACKAGES = 300
MAX_CONDA_ENVS = 32
VERSION_TIMEOUT_SECONDS = 10
PIP_LIST_TIMEOUT_SECONDS = 60
#: Captured stdout is cut here before parsing (pip list of a huge env).
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


def _packages(
    python: str, capture: Capture, uv: str | None
) -> tuple[list[dict[str, str]], bool] | None:
    text = capture([python, "-m", "pip", "list", "--format", "json"], PIP_LIST_TIMEOUT_SECONDS)
    if text is None and uv is not None:
        # A `uv venv` ships no pip: read the same list through uv.
        text = capture(
            [uv, "pip", "list", "--python", python, "--format", "json"], PIP_LIST_TIMEOUT_SECONDS
        )
    try:
        listed = json.loads(text) if text is not None else None
    except ValueError:
        return None
    if not isinstance(listed, list):
        return None
    packages: list[dict[str, str]] = []
    truncated = False
    for item in listed:
        if not isinstance(item, dict):
            return None
        name, version = item.get("name"), item.get("version")
        if not isinstance(name, str) or not isinstance(version, str) or not name or not version:
            return None
        if len(packages) == MAX_PACKAGES:
            return packages, True
        truncated |= len(name) > MAX_WIRE_CHARS or len(version) > MAX_WIRE_CHARS
        packages.append({"name": name[:MAX_WIRE_CHARS], "version": version[:MAX_WIRE_CHARS]})
    return packages, truncated


def _venv(
    root: Path, capture: Capture, uv: str | None, environment: str | None
) -> dict[str, Any] | None:
    if environment is not None and not _relative(environment):
        return None
    for name in VENV_DIR_NAMES if environment is None else (environment,):
        relative = venv_python(root, name)
        if relative is None:
            continue
        python = str(root / relative)
        inventory = _packages(python, capture, uv)
        if inventory is None:
            return None
        packages, truncated = inventory
        return {
            "path": name,
            "python_version": _version(python, capture),
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
        "venv": _guard("venv", lambda: _venv(root, capture, which("uv"), environment), None),
        "conda": _guard("conda", lambda: _conda(which, capture), None),
        "uv": _guard("uv", lambda: _uv(which, capture), None),
    }
