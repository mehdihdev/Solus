"""Linux sandbox helper for the `code` server (docs/api/code-command-execution.md §3).

Run as `<python> -I landlock_exec.py [--env-fd N] --home <HOME> --rw <path> … --
<program> <args…>`: it refuses any `--rw` path that equals or contains HOME or
`HOME/.solus` (or lies inside `HOME/.solus`), then sets
PR_SET_NO_NEW_PRIVS, creates a Landlock ruleset that HANDLES the filesystem write
rights of the best available ABI, grants them beneath each `--rw` path, restricts
itself, then `os.execv`s the program. Reads, exec and network stay unrestricted.
Any failure refuses to exec (exit 126) — never a silent unsandboxed run.

Solus-authored, standard library only (`-I` isolates it from site-packages and
the working directory), no imports from the `solus` package.
"""

import ctypes
import os
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

WRITE_FILE = 1 << 1
REMOVE_DIR = 1 << 4
REMOVE_FILE = 1 << 5
MAKE_CHAR = 1 << 6
MAKE_DIR = 1 << 7
MAKE_REG = 1 << 8
MAKE_SOCK = 1 << 9
MAKE_FIFO = 1 << 10
MAKE_BLOCK = 1 << 11
MAKE_SYM = 1 << 12
REFER = 1 << 13  # ABI 2
TRUNCATE = 1 << 14  # ABI 3
WRITE_V1 = (
    WRITE_FILE
    | REMOVE_DIR
    | REMOVE_FILE
    | MAKE_CHAR
    | MAKE_DIR
    | MAKE_REG
    | MAKE_SOCK
    | MAKE_FIFO
    | MAKE_BLOCK
    | MAKE_SYM
)

# Generic syscall numbers (identical on x86_64 and aarch64).
SYS_CREATE_RULESET = 444
SYS_ADD_RULE = 445
SYS_RESTRICT_SELF = 446
CREATE_RULESET_VERSION = 1 << 0
SCOPE_ABSTRACT_UNIX_SOCKET = 1 << 0  # ABI 6
SCOPE_SIGNAL = 1 << 1  # ABI 6
RULE_PATH_BENEATH = 1
PR_SET_NO_NEW_PRIVS = 38
EXIT_USAGE = 2
EXIT_REFUSED = 126
EXIT_NOT_EXECUTED = 127
MAX_ENV_BYTES = 1024 * 1024
O_PATH = getattr(os, "O_PATH", 0)


def handled_access(abi: int) -> int:
    """The write rights the ruleset handles (everything not granted is denied)."""
    rights = WRITE_V1
    if abi >= 2:
        rights |= REFER
    if abi >= 3:
        rights |= TRUNCATE
    return rights


def file_access(abi: int) -> int:
    """The subset of handled rights a rule on a non-directory may carry."""
    return WRITE_FILE | (TRUNCATE if abi >= 3 else 0)


class Syscalls(Protocol):
    def abi(self) -> int: ...

    def no_new_privs(self) -> None: ...

    def create_ruleset(self, handled: int, scoped: int) -> int: ...

    def add_rule(self, ruleset_fd: int, allowed: int, parent_fd: int) -> None: ...

    def restrict_self(self, ruleset_fd: int) -> None: ...


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _ScopedRulesetAttr(ctypes.Structure):
    """ABI 6 layout. Network rights stay unhandled: network access is allowed by decision."""

    _fields_ = [
        ("handled_access_fs", ctypes.c_uint64),
        ("handled_access_net", ctypes.c_uint64),
        ("scoped", ctypes.c_uint64),
    ]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


class CtypesSyscalls:
    """The real kernel interface via libc `syscall(2)` and `prctl(2)`."""

    def __init__(self) -> None:
        self._libc = ctypes.CDLL(None, use_errno=True)
        self._libc.syscall.restype = ctypes.c_long

    def _check(self, result: int, what: str) -> int:
        if result < 0:
            errno = ctypes.get_errno()
            raise OSError(errno, f"landlock {what} failed: {os.strerror(errno)}")
        return result

    def abi(self) -> int:
        result = self._libc.syscall(SYS_CREATE_RULESET, None, 0, CREATE_RULESET_VERSION)
        return int(self._check(int(result), "abi probe"))

    def no_new_privs(self) -> None:
        self._check(int(self._libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)), "no_new_privs")

    def create_ruleset(self, handled: int, scoped: int) -> int:
        attr: ctypes.Structure = (
            _ScopedRulesetAttr(handled, 0, scoped) if scoped else _RulesetAttr(handled)
        )
        result = self._libc.syscall(SYS_CREATE_RULESET, ctypes.byref(attr), ctypes.sizeof(attr), 0)
        return int(self._check(int(result), "create_ruleset"))

    def add_rule(self, ruleset_fd: int, allowed: int, parent_fd: int) -> None:
        attr = _PathBeneathAttr(allowed, parent_fd)
        result = self._libc.syscall(
            SYS_ADD_RULE, ruleset_fd, RULE_PATH_BENEATH, ctypes.byref(attr), 0
        )
        self._check(int(result), "add_rule")

    def restrict_self(self, ruleset_fd: int) -> None:
        self._check(int(self._libc.syscall(SYS_RESTRICT_SELF, ruleset_fd, 0)), "restrict_self")


class Landlock:
    """Builds and applies the write-confining ruleset."""

    def __init__(self, syscalls: Syscalls | None = None) -> None:
        self._syscalls = syscalls if syscalls is not None else CtypesSyscalls()

    def abi(self) -> int:
        return self._syscalls.abi()

    def restrict(self, paths: Sequence[str]) -> None:
        """Grant handled rights beneath `paths` (missing ones grant nothing), then restrict."""
        abi = self._syscalls.abi()
        if abi < 1:
            raise OSError("landlock is not available on this kernel")
        self._syscalls.no_new_privs()
        handled = handled_access(abi)
        scoped = SCOPE_ABSTRACT_UNIX_SOCKET | SCOPE_SIGNAL if abi >= 6 else 0
        ruleset = self._syscalls.create_ruleset(handled, scoped)
        for path in paths:
            try:
                fd = os.open(path, O_PATH | os.O_CLOEXEC)
            except OSError:
                continue
            try:
                is_dir = stat.S_ISDIR(os.fstat(fd).st_mode)
                allowed = handled if is_dir else file_access(abi)
                self._syscalls.add_rule(ruleset, allowed, fd)
            finally:
                os.close(fd)
        self._syscalls.restrict_self(ruleset)


@dataclass(frozen=True)
class Invocation:
    paths: list[str]
    command: list[str]
    env_fd: int | None
    home: str


def _parse(argv: Sequence[str]) -> Invocation | None:
    paths: list[str] = []
    env_fd: int | None = None
    home: str | None = None
    index = 0
    while index + 1 < len(argv) and argv[index] in ("--rw", "--env-fd", "--home"):
        option, value = argv[index], argv[index + 1]
        if option == "--rw":
            paths.append(value)
        elif option == "--home" and home is None and os.path.isabs(value):
            home = value
        elif option == "--env-fd" and value.isdigit():
            env_fd = int(value)
        else:
            return None
        index += 2
    if home is None or index >= len(argv) or argv[index] != "--":
        return None
    command = list(argv[index + 1 :])
    if not command or not os.path.isabs(command[0]):
        return None
    return Invocation(paths, command, env_fd, home)


def holds_home(path: str, home: str) -> bool:
    """`path` equals or contains HOME or HOME/.solus, or lies inside HOME/.solus."""
    real = Path(os.path.realpath(path))
    real_home = Path(os.path.realpath(home))
    solus = real_home / ".solus"
    return (
        real_home.is_relative_to(real) or solus.is_relative_to(real) or real.is_relative_to(solus)
    )


def read_env(fd: int) -> dict[str, str] | None:
    """NUL-separated `K=V` from `fd` (closed afterwards); None when oversized or malformed."""
    data = b""
    try:
        while len(data) <= MAX_ENV_BYTES:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
    finally:
        os.close(fd)
    if len(data) > MAX_ENV_BYTES:
        return None
    env: dict[str, str] = {}
    for entry in data.split(b"\0"):
        if not entry:
            continue
        name, separator, value = entry.partition(b"=")
        if not separator or not name:
            return None
        env[name.decode("utf-8", errors="surrogateescape")] = value.decode(
            "utf-8", errors="surrogateescape"
        )
    return env


Execve = Callable[[str, list[str], dict[str, str]], object]


def main(
    argv: Sequence[str],
    *,
    landlock: Landlock | None = None,
    execve: Execve = os.execve,
) -> int:
    """The helper runs with a minimal fixed environment; the child's environment
    arrives over `--env-fd` and is applied only by the final `execve`."""
    parsed = _parse(argv)
    if parsed is None:
        sys.stderr.write(
            "solus landlock: usage: [--env-fd N] --home HOME --rw PATH ... -- /abs/program [args]\n"
        )
        return EXIT_USAGE
    if any(holds_home(path, parsed.home) for path in parsed.paths):
        sys.stderr.write("solus landlock: refused: a writable path holds HOME or ~/.solus\n")
        return EXIT_REFUSED
    env: dict[str, str] | None = dict(os.environ)
    if parsed.env_fd is not None:
        try:
            env = read_env(parsed.env_fd)
        except OSError:
            env = None
    if env is None:
        sys.stderr.write("solus landlock: refused: unreadable or oversized environment\n")
        return EXIT_REFUSED
    try:
        (landlock or Landlock()).restrict(parsed.paths)
    except OSError as exc:
        sys.stderr.write(f"solus landlock: sandbox unavailable: {exc}\n")
        return EXIT_REFUSED
    try:
        execve(parsed.command[0], parsed.command, env)
    except OSError as exc:
        sys.stderr.write(f"solus landlock: could not exec: {exc.strerror}\n")
        return EXIT_NOT_EXECUTED
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the real-Landlock test
    sys.exit(main(sys.argv[1:]))
