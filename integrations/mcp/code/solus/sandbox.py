"""The OS sandbox for every executing `code` tool (docs/api/code-command-execution.md §3).

Writes are confined to the workspace, the temporary directories, a few device
nodes and the declared tool caches under HOME; reads, exec and network are not
restricted. macOS wraps the argv in the root-owned `/usr/bin/sandbox-exec` with a
constant Solus profile (which also denies `.git/hooks`, `.git/config` and
`~/.solus`). Linux runs the dependency-free `landlock_exec.py` helper, which
grants only — so the `.git` denial is enforced there by detection: the executor
compares `git_metadata_digest` before and after and reports a change. Any other
platform, or a failed probe, refuses to run anything.
"""

import functools
import glob
import hashlib
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .landlock_exec import Landlock

KIND_MACOS = "sandbox-exec"
KIND_LINUX = "landlock"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
LANDLOCK_HELPER = Path(__file__).resolve().with_name("landlock_exec.py")
#: Declared tool caches under HOME. Adding one is a SECURITY_REVIEW re-review trigger.
HOME_CACHES: tuple[str, ...] = (
    ".cache",
    "Library/Caches",
    ".ros",
    ".npm",
    ".pnpm-store",
    ".local/share/pnpm",
    ".local/share/uv",
    ".cargo/registry",
    ".cargo/git",
    ".platformio",
    ".arduino15",
    ".gradle",
    ".colcon",
)
#: What the plan answer shows (no absolute machine paths).
WRITABLE_LABELS: tuple[str, ...] = (
    "<workspace>",
    "<tmp>",
    "<devices>",
    *(f"~/{cache}" for cache in HOME_CACHES),
)
_HOME_RULES = "".join(f'(subpath (string-append (param "HOME") "/{c}"))' for c in HOME_CACHES)
MACOS_PROFILE = (
    "(version 1)(allow default)(deny file-write*)"
    "(allow file-write*"
    '(subpath (param "WORKSPACE"))(subpath (param "TMP"))'
    '(subpath "/private/tmp")(subpath "/private/var/folders")'
    '(literal "/dev/null")(literal "/dev/zero")(literal "/dev/tty")'
    '(regex #"^/dev/fd/")(regex #"^/dev/cu\\.")(regex #"^/dev/tty\\.")'
    f"{_HOME_RULES})"
    "(deny file-write*"
    '(subpath (string-append (param "WORKSPACE") "/.git/hooks"))'
    '(literal (string-append (param "WORKSPACE") "/.git/config"))'
    '(subpath (string-append (param "HOME") "/.solus")))'
)
LINUX_TMP: tuple[str, ...] = ("/tmp", "/var/tmp")  # noqa: S108 - the declared writable set
LINUX_DEVICES: tuple[str, ...] = ("/dev/null", "/dev/zero", "/dev/tty")
LINUX_SERIAL_GLOBS: tuple[str, ...] = ("/dev/ttyUSB*", "/dev/ttyACM*")
MAX_GIT_ENTRIES = 512
MAX_GIT_FILE_BYTES = 1024 * 1024
SMOKE_TIMEOUT_SECONDS = 10

Probe = tuple[str | None, str]


def _macos_smoke() -> bool:
    """`sandbox-exec` can actually apply a profile here (it cannot inside some sandboxes)."""
    try:
        result = subprocess.run(  # noqa: S603 - constant argv
            [SANDBOX_EXEC, "-p", "(version 1)(allow default)", "/usr/bin/true"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=SMOKE_TIMEOUT_SECONDS,
            env={"PATH": "/usr/bin:/bin"},
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _probe_macos(stat_fn: Callable[[str], Any], smoke: Callable[[], bool]) -> Probe:
    try:
        info = stat_fn(SANDBOX_EXEC)
    except OSError:
        return None, f"{SANDBOX_EXEC} not found"
    if info.st_uid != 0:
        return None, f"{SANDBOX_EXEC} is not root-owned"
    if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH) or not stat.S_ISREG(info.st_mode):
        return None, f"{SANDBOX_EXEC} is group/world writable or not a regular file"
    if not smoke():
        return None, f"{SANDBOX_EXEC} cannot apply a profile on this machine"
    return KIND_MACOS, "available"


def _probe_linux(landlock_abi: Callable[[], int]) -> Probe:
    try:
        abi = landlock_abi()
    except OSError as exc:
        return None, f"landlock is not supported by this kernel ({exc.strerror or exc})"
    if abi < 1:
        return None, "landlock is not enabled on this kernel"
    if not LANDLOCK_HELPER.is_file():
        return None, "landlock helper missing"
    return KIND_LINUX, f"available (ABI {abi})"


def probe(
    platform: str = sys.platform,
    *,
    stat_fn: Callable[[str], Any] = os.stat,
    smoke: Callable[[], bool] = _macos_smoke,
    landlock_abi: Callable[[], int] | None = None,
) -> Probe:
    """`(kind, reason)`; kind is None when nothing may run."""
    if platform == "darwin":
        return _probe_macos(stat_fn, smoke)
    if platform.startswith("linux"):
        return _probe_linux(landlock_abi or (lambda: Landlock().abi()))
    return None, f"unsupported platform: {platform[:32]}"


@functools.cache
def available() -> Probe:
    """The probe, cached for the server's lifetime."""
    return probe()


def default_home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def default_tmpdir() -> Path:
    return Path(tempfile.gettempdir())


def _real(path: Path | str) -> str:
    return os.path.realpath(path)


def linux_writable(workspace: Path, home: Path, tmpdir: Path) -> list[str]:
    """The existing writable paths, realpath'd and deduplicated (missing ones grant nothing)."""
    candidates = [_real(workspace), _real(tmpdir), *LINUX_TMP, *LINUX_DEVICES]
    for pattern in LINUX_SERIAL_GLOBS:
        candidates.extend(sorted(glob.glob(pattern)))
    candidates.extend(_real(home / cache) for cache in HOME_CACHES)
    unique: list[str] = []
    for path in candidates:
        if path not in unique and os.path.exists(path):
            unique.append(path)
    return unique


def wrap(
    kind: str | None,
    argv: Sequence[str],
    *,
    workspace: Path,
    home: Path | None = None,
    tmpdir: Path | None = None,
) -> list[str]:
    """The final argv that runs `argv` (absolute program first) inside the sandbox."""
    home = home if home is not None else default_home()
    tmpdir = tmpdir if tmpdir is not None else default_tmpdir()
    if kind == KIND_MACOS:
        return [
            SANDBOX_EXEC,
            "-p",
            MACOS_PROFILE,
            "-D",
            f"WORKSPACE={_real(workspace)}",
            "-D",
            f"TMP={_real(tmpdir)}",
            "-D",
            f"HOME={_real(home)}",
            *argv,
        ]
    if kind == KIND_LINUX:
        grants: list[str] = []
        for path in linux_writable(workspace, home, tmpdir):
            grants.extend(("--rw", path))
        return [sys.executable, "-I", str(LANDLOCK_HELPER), *grants, "--", *argv]
    raise ValueError(f"sandbox unavailable: {kind!r}")


def _hash_file(digest: Any, path: str) -> None:
    try:
        with open(path, "rb") as handle:
            digest.update(handle.read(MAX_GIT_FILE_BYTES))
    except OSError:
        digest.update(b"unreadable")


def _hash_entry(digest: Any, path: str, label: str) -> None:
    try:
        info = os.lstat(path)
    except OSError:
        digest.update(f"{label}:absent\0".encode())
        return
    digest.update(f"{label}:{info.st_mode}:{info.st_size}\0".encode())
    if stat.S_ISLNK(info.st_mode):
        digest.update(os.readlink(path).encode(errors="replace"))
    elif stat.S_ISREG(info.st_mode):
        _hash_file(digest, path)


def git_metadata_digest(workspace: Path) -> str:
    """A digest of `.git/config` and everything under `.git/hooks` (bounded)."""
    digest = hashlib.sha256()
    git_dir = os.path.join(workspace, ".git")
    _hash_entry(digest, os.path.join(git_dir, "config"), "config")
    hooks = os.path.join(git_dir, "hooks")
    _hash_entry(digest, hooks, "hooks")
    seen = 0
    for directory, dirs, files in os.walk(hooks, followlinks=False):
        dirs.sort()
        for name in sorted([*dirs, *files]):
            seen += 1
            if seen > MAX_GIT_ENTRIES:
                digest.update(b"overflow")
                return digest.hexdigest()
            path = os.path.join(directory, name)
            _hash_entry(digest, path, os.path.relpath(path, hooks))
    return digest.hexdigest()
