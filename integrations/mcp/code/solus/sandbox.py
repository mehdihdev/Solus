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
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from .landlock_exec import Landlock

KIND_MACOS = "sandbox-exec"
KIND_LINUX = "landlock"  # reported as `landlock-abi<N>`
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
#: Launch / AppleEvent tools a sandboxed command may not exec (IPC escapes).
MACOS_DENIED_EXEC: tuple[str, ...] = (
    "/bin/launchctl",
    "/usr/bin/osascript",
    "/usr/bin/open",
    "/usr/bin/osacompile",
    "/usr/bin/automator",
)


def _git_rules(directory: str, pattern: str) -> str:
    """Denials for one protected git directory (`directory` / its escaped `pattern` params)."""
    root = f'(param "{directory}")'
    regex = f'(param "{pattern}")'
    return (
        f"(literal {root})"
        f'(regex (string-append "^" {regex} "/config[^/]*$"))'
        f'(subpath (string-append {root} "/hooks"))'
        f'(subpath (string-append {root} "/info"))'
        f'(regex (string-append "^" {regex} "/modules/.+/config[^/]*$"))'
        f'(regex (string-append "^" {regex} "/modules/(.+/)?hooks(/.*)?$"))'
        f'(regex (string-append "^" {regex} "/worktrees/[^/]+/config[^/]*$"))'
        f'(literal (string-append {root} "/commondir"))'
    )


MACOS_PROFILE = (
    "(version 1)(allow default)(deny file-write*)"
    "(allow file-write*"
    '(subpath (param "WORKSPACE"))(subpath (param "TMP"))'
    '(subpath "/private/tmp")(subpath "/private/var/folders")'
    '(literal "/dev/null")(literal "/dev/zero")(literal "/dev/tty")'
    '(regex #"^/dev/fd/")(regex #"^/dev/cu\\.")(regex #"^/dev/tty\\.")'
    f"{_HOME_RULES})"
    "(deny file-write*"
    '(literal (param "DOTGIT"))'
    f"{_git_rules('GIT_DIR', 'GIT_DIR_RE')}{_git_rules('GIT_COMMON', 'GIT_COMMON_RE')}"
    '(subpath (string-append (param "HOME") "/.solus")))'
    "(deny process-exec" + "".join(f'(literal "{program}")' for program in MACOS_DENIED_EXEC) + ")"
    '(deny mach-lookup (global-name "com.apple.coreservices.appleevents"))'
)
LINUX_TMP: tuple[str, ...] = ("/tmp", "/var/tmp")  # noqa: S108 - the declared writable set
LINUX_DEVICES: tuple[str, ...] = ("/dev/null", "/dev/zero", "/dev/tty")
LINUX_SERIAL_GLOBS: tuple[str, ...] = ("/dev/ttyUSB*", "/dev/ttyACM*")
MAX_GIT_ENTRIES = 4096
MAX_GIT_BYTES = 64 * 1024 * 1024
#: Pruned when looking for submodule config/hooks (bulk git state, not metadata).
GIT_BULK_DIRS: frozenset[str] = frozenset({"objects", "refs", "logs", "lfs"})
_REGEX_SPECIAL = frozenset(".[]{}()\\*+?^$|")
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
            f"GIT_DIR_RE={sbpl_regex_escape(git_dir)}",
            "-D",
            f"GIT_COMMON={common}",
            "-D",
            f"GIT_COMMON_RE={sbpl_regex_escape(common)}",
            *argv,
        ]
    if kind is not None and kind.startswith(KIND_LINUX):
        grants: list[str] = []
        for path in linux_writable(workspace, home, tmpdir):
            grants.extend(("--rw", path))
        return [sys.executable, "-I", str(LANDLOCK_HELPER), *grants, "--", *argv]
    raise ValueError(f"sandbox unavailable: {kind!r}")


def sbpl_regex_escape(path: str) -> str:
    """Escape a path for use inside a sandbox-profile regular expression."""
    return "".join(f"\\{char}" if char in _REGEX_SPECIAL else char for char in path)


def limitations(kind: str | None) -> list[str]:
    """Known gaps of `kind`, shown on the approval card."""
    if kind is None:
        return []
    gaps = ["reads, exec and network are not restricted"]
    if not kind.startswith(KIND_LINUX):
        return gaps
    abi = int(kind.rsplit("abi", 1)[-1]) if kind.rsplit("abi", 1)[-1].isdigit() else 0
    gaps.append("file metadata (chmod/chown/utimes) not confined")
    gaps.append(".git hooks and config are protected by detection only")
    if abi < 3:
        gaps.append("truncate not confined")
    if abi < 6:
        gaps.append("unix-socket/signal scoping unavailable")
    return gaps


def _gitfile_target(dot_git: Path) -> str | None:
    try:
        with open(dot_git, "rb") as handle:
            text = handle.read(4096).decode("utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    target = text[len("gitdir:") :].strip()
    return _real(dot_git.parent / target) if target else None


def _commondir(git_dir: str) -> str:
    try:
        with open(os.path.join(git_dir, "commondir"), "rb") as handle:
            target = handle.read(4096).decode("utf-8", errors="replace").strip()
    except OSError:
        return git_dir
    return _real(os.path.join(git_dir, target)) if target else git_dir


def protected_git_dirs(workspace: Path) -> tuple[str, str]:
    """`(git dir, common dir)` whose metadata is protected: `.git` itself, or the
    target of a `gitdir:` file and the `commondir` it names."""
    dot_git = Path(workspace) / ".git"
    default = str(dot_git)
    if dot_git.is_file() and not dot_git.is_symlink():
        target = _gitfile_target(dot_git)
        if target is None:
            return default, default
        return target, _commondir(target)
    if dot_git.is_dir():
        return default, _commondir(default)
    return default, default


class _OverflowError(Exception):
    """A digest cap was hit: the answer must compare as changed."""


class _Digest:
    def __init__(self) -> None:
        self.hash = hashlib.sha256()
        self.entries = 0
        self.bytes = 0

    def _count(self, size: int) -> None:
        self.entries += 1
        self.bytes += size
        if self.entries > MAX_GIT_ENTRIES or self.bytes > MAX_GIT_BYTES:
            raise _OverflowError

    def entry(self, path: str) -> None:
        try:
            info = os.lstat(path)
        except OSError:
            self.hash.update(f"{path}:absent\0".encode(errors="replace"))
            return
        size = 0 if stat.S_ISDIR(info.st_mode) else info.st_size
        self._count(size)
        self.hash.update(f"{path}:{info.st_mode}:{size}\0".encode(errors="replace"))
        if stat.S_ISLNK(info.st_mode):
            self.hash.update(os.readlink(path).encode(errors="replace"))
        elif stat.S_ISREG(info.st_mode):
            self._stream(path)

    def _stream(self, path: str) -> None:
        try:
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    self.hash.update(block)
        except OSError:
            self.hash.update(b"unreadable")

    def tree(self, root: str, keep: Callable[[str], bool] | None = None) -> None:
        """Every entry under `root`; with `keep`, bulk dirs are pruned and only kept
        entries are hashed (the rest still count against the caps)."""
        self.entry(root)
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = sorted(name for name in dirs if keep is None or name not in GIT_BULK_DIRS)
            for name in sorted([*dirs, *files]):
                path = os.path.join(directory, name)
                if keep is None or keep(os.path.relpath(path, root)):
                    self.entry(path)
                else:
                    self._count(0)


def _module_metadata(relative: str) -> bool:
    parts = relative.split(os.sep)
    return "hooks" in parts or parts[-1].startswith("config")


def _digest_git_dir(digest: _Digest, git_dir: str) -> None:
    digest.entry(git_dir)
    for path in sorted(glob.glob(os.path.join(glob.escape(git_dir), "config*"))):
        digest.entry(path)
    digest.entry(os.path.join(git_dir, "commondir"))
    digest.tree(os.path.join(git_dir, "hooks"))
    digest.tree(os.path.join(git_dir, "info"))
    digest.tree(os.path.join(git_dir, "modules"), _module_metadata)
    worktrees = os.path.join(git_dir, "worktrees")
    digest.entry(worktrees)
    for path in sorted(glob.glob(os.path.join(glob.escape(worktrees), "*"))):
        digest.entry(path)
        for config in sorted(glob.glob(os.path.join(glob.escape(path), "config*"))):
            digest.entry(config)


def git_metadata_digest(workspace: Path) -> str:
    """A digest of every protected git metadata path (full contents and modes).
    Past any cap it answers a unique sentinel, which always compares as changed."""
    digest = _Digest()
    try:
        digest.entry(os.path.join(workspace, ".git"))
        for git_dir in dict.fromkeys(protected_git_dirs(workspace)):
            _digest_git_dir(digest, git_dir)
    except _OverflowError:
        return f"overflow:{uuid.uuid4().hex}"
    return digest.hash.hexdigest()
