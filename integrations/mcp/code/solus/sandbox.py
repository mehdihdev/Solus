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
import os
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from .git_guard import git_metadata_digest as git_metadata_digest
from .git_guard import protected_git_dirs as protected_git_dirs
from .landlock_exec import MAX_ENV_BYTES, Landlock, holds_home

KIND_MACOS = "sandbox-exec"
KIND_LINUX = "landlock"  # reported as `landlock-abi<N>`
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
LANDLOCK_HELPER = Path(__file__).resolve().with_name("landlock_exec.py")
#: Declared tool caches under HOME — data only (§9.5): nothing here may hold code that
#: later runs outside the sandbox (so no `.local/share/uv`, `.cargo/git`, or the roots of
#: `.gradle`/`.platformio`/`.arduino15`). Adding one is a SECURITY_REVIEW re-review trigger.
HOME_CACHES: tuple[str, ...] = (
    ".cache",
    "Library/Caches",
    ".ros",
    ".npm/_cacache",
    ".pnpm-store",
    ".cargo/registry/cache",
    ".gradle/caches",
    ".platformio/.cache",
    ".arduino15/staging",
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
#: Launch / AppleEvent tools a sandboxed command may not exec (IPC escapes).
MACOS_DENIED_EXEC: tuple[str, ...] = (
    "/bin/launchctl",
    "/usr/bin/osascript",
    "/usr/bin/open",
    "/usr/bin/osacompile",
    "/usr/bin/automator",
)


MACOS_PROFILE = (
    "(version 1)(allow default)(deny file-write*)"
    "(allow file-write*"
    '(subpath (param "WORKSPACE"))(subpath (param "TMP"))'
    '(subpath "/private/tmp")(subpath (param "USER_CACHE"))'
    '(literal "/dev/null")(literal "/dev/zero")(literal "/dev/tty")'
    '(regex #"^/dev/fd/")(regex #"^/dev/cu\\.")(regex #"^/dev/tty\\.")'
    f"{_HOME_RULES})"
    "(deny file-write*"
    '(literal (param "DOTGIT"))(subpath (param "GIT_DIR"))(subpath (param "GIT_COMMON"))'
    '(subpath (string-append (param "HOME") "/.solus")))'
    "(deny process-exec" + "".join(f'(literal "{program}")' for program in MACOS_DENIED_EXEC) + ")"
    "(deny mach-lookup"
    '(global-name "com.apple.coreservices.appleevents")'
    '(global-name "com.apple.coreservices.launchservicesd")'
    '(global-name-regex #"^com\\.apple\\.lsd\\."))'
)
LINUX_TMP: tuple[str, ...] = ("/tmp", "/var/tmp")  # noqa: S108 - the declared writable set
LINUX_DEVICES: tuple[str, ...] = ("/dev/null", "/dev/zero", "/dev/tty")
LINUX_SERIAL_GLOBS: tuple[str, ...] = ("/dev/ttyUSB*", "/dev/ttyACM*")
SMOKE_TIMEOUT_SECONDS = 10

Probe = tuple[str | None, str]
#: Descriptors the spawner must hand to the child (the Linux helper's `--env-fd`).
PASS_FDS: ContextVar[tuple[int, ...]] = ContextVar("code_pass_fds", default=())
HELPER_PATH = "/usr/bin:/bin"


def helper_env(env: Mapping[str, str]) -> dict[str, str]:
    """The Landlock helper's own FIXED environment: nothing a profile or workspace
    could use to load code into it before it restricts itself."""
    fixed = {"PATH": HELPER_PATH}
    if env.get("LANG"):
        fixed["LANG"] = env["LANG"]
    return fixed


def env_descriptor(env: Mapping[str, str]) -> int:
    """An anonymous file holding `env` as NUL-separated `K=V`, rewound, for `--env-fd`."""
    payload = b"".join(
        f"{name}={value}".encode("utf-8", errors="surrogateescape") + b"\0"
        for name, value in env.items()
    )
    if len(payload) > MAX_ENV_BYTES:
        raise ValueError("environment too large for the sandbox helper")
    memfd = getattr(os, "memfd_create", None)
    if memfd is not None:
        descriptor = int(memfd("solus-env"))
    else:
        descriptor, path = tempfile.mkstemp(prefix="solus-env-")
        os.unlink(path)
    try:
        os.write(descriptor, payload)
        os.lseek(descriptor, 0, os.SEEK_SET)
    except OSError:
        os.close(descriptor)
        raise
    return descriptor


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
    return f"{KIND_LINUX}-abi{abi}", "available"


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


def home_conflict(workspace: Path, home: Path | None = None) -> str | None:
    """Why `workspace` may not be written by a sandboxed command (§9.4): its realpath
    equals or contains HOME or ~/.solus, or lies inside ~/.solus (the rule the Linux
    helper applies to every `--rw` path). None when fine."""
    real = Path(_real(workspace))
    if not holds_home(str(real), str(home if home is not None else default_home())):
        return None
    return "the linked folder is (or contains) your home folder or ~/.solus; link a project folder"


def linux_writable(workspace: Path, home: Path, tmpdir: Path) -> list[str]:
    """The existing writable paths, realpath'd and deduplicated (missing ones grant
    nothing). A temp root that contains HOME is never granted (§9.4)."""
    candidates = [_real(workspace), _real(tmpdir), *LINUX_TMP, *LINUX_DEVICES]
    for pattern in LINUX_SERIAL_GLOBS:
        candidates.extend(sorted(glob.glob(pattern)))
    candidates.extend(_real(home / cache) for cache in HOME_CACHES)
    unique: list[str] = []
    for path in candidates:
        if path in unique or not os.path.exists(path) or holds_home(path, str(home)):
            continue
        unique.append(path)
    return unique


#: macOS per-user temp/cache roots live at /private/var/folders/<xx>/<id>/{T,C}.
DARWIN_FOLDERS = "/private/var/folders"


def user_cache_dir(tmpdir: Path, *, folders: str = DARWIN_FOLDERS) -> str:
    """This user's Darwin cache dir (the `C` sibling of `T`), else the temp dir itself.

    Only this user's own temp and cache dirs are writable, never the whole
    /private/var/folders tree.
    """
    real = Path(_real(tmpdir))
    if real.is_relative_to(Path(folders).resolve()) and real.name == "T":
        return str(real.parent / "C")
    return str(real)


#: Temp roots a sandboxed command can write on either platform.
SHARED_TMP: tuple[str, ...] = ("/private/tmp", *LINUX_TMP)


def writable_roots(home: Path | None = None, tmpdir: Path | None = None) -> list[str]:
    """Every directory a sandboxed command may write besides the workspace (realpaths)."""
    home = home if home is not None else default_home()
    tmpdir = tmpdir if tmpdir is not None else default_tmpdir()
    roots = [_real(tmpdir), user_cache_dir(tmpdir), *(_real(path) for path in SHARED_TMP)]
    roots.extend(_real(home / cache) for cache in HOME_CACHES)
    return list(dict.fromkeys(roots))


def foreign_writable(
    path: str, workspace: Path | None, *, home: Path | None = None, tmpdir: Path | None = None
) -> bool:
    """True when `path`'s realpath lies in the sandbox's writable set but outside the
    workspace (§9.5): an earlier sandboxed command could have planted it there, so it
    is never resolved as a program. With no workspace every writable root counts."""
    real = Path(_real(path))
    if workspace is not None and real.is_relative_to(_real(workspace)):
        return False
    return any(real.is_relative_to(root) for root in writable_roots(home, tmpdir))


def wrap(
    kind: str | None,
    argv: Sequence[str],
    *,
    workspace: Path,
    home: Path | None = None,
    tmpdir: Path | None = None,
    env_fd: int | None = None,
) -> list[str]:
    """The final argv that runs `argv` (absolute program first) inside the sandbox."""
    home = home if home is not None else default_home()
    tmpdir = tmpdir if tmpdir is not None else default_tmpdir()
    conflict = home_conflict(workspace, home)
    if conflict is not None:
        raise ValueError(conflict)
    if kind == KIND_MACOS:
        real = _real(workspace)
        git_dir, common = protected_git_dirs(Path(real))
        return [
            SANDBOX_EXEC,
            "-p",
            MACOS_PROFILE,
            "-D",
            f"WORKSPACE={real}",
            "-D",
            f"TMP={_real(tmpdir)}",
            "-D",
            f"HOME={_real(home)}",
            "-D",
            f"DOTGIT={real}/.git",
            "-D",
            f"GIT_DIR={git_dir}",
            "-D",
            f"GIT_COMMON={common}",
            "-D",
            f"USER_CACHE={user_cache_dir(tmpdir)}",
            *argv,
        ]
    if kind is not None and kind.startswith(KIND_LINUX):
        grants: list[str] = ["--env-fd", str(env_fd)] if env_fd is not None else []
        grants.extend(("--home", _real(home)))
        for path in linux_writable(workspace, home, tmpdir):
            grants.extend(("--rw", path))
        return [sys.executable, "-I", str(LANDLOCK_HELPER), *grants, "--", *argv]
    raise ValueError(f"sandbox unavailable: {kind!r}")


def limitations(kind: str | None) -> list[str]:
    """Known gaps of `kind`, shown on the approval card."""
    if kind is None:
        return []
    gaps = [
        "reads, exec and network are not restricted",
        "git operations inside sandboxed commands cannot write the repository",
    ]
    if not kind.startswith(KIND_LINUX):
        return [
            *gaps,
            "launchd job submission not blocked",
            "a descendant that double-forks between process-table snapshots can survive a stop",
        ]
    abi = int(kind.rsplit("abi", 1)[-1]) if kind.rsplit("abi", 1)[-1].isdigit() else 0
    gaps.append("file metadata (chmod/chown/utimes) not confined")
    gaps.append(
        "git metadata protected by detection only; descendants that leave the process group"
        " are not tracked"
    )
    if abi < 3:
        gaps.append("truncate not confined")
    if abi < 6:
        gaps.append("unix-socket/signal scoping unavailable")
    return gaps
