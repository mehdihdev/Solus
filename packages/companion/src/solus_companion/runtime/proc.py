"""Subprocess hygiene for setup — mcp-fork-runtime.md §3.

Argv lists only (never a shell), a child environment built from scratch with a
fixed PATH, a timeout on every call, and stdout/stderr spooled to temp files
of which only the last 64 KiB is ever read back."""

import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import IO, Protocol

OUTPUT_CAP_BYTES = 64 * 1024
POSIX_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"

#: POSIX keeps only what pip needs for its cache and temp files.
_POSIX_KEEP = ("HOME", "TMPDIR", "LANG")
#: Windows keeps only what CPython itself needs to start (SYSTEMROOT is
#: required by the socket/random machinery) and where temp/app data live.
_WINDOWS_KEEP = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "LOCALAPPDATA", "APPDATA")


@dataclass(frozen=True)
class ProcResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    launch_error: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.launch_error


class Runner(Protocol):
    def __call__(
        self, argv: Sequence[str], *, timeout: float, env: Mapping[str, str]
    ) -> ProcResult: ...


def scrubbed_env(source: Mapping[str, str], platform: str) -> dict[str, str]:
    """The child env, from scratch. `PIP_*`, `PYTHON*`, `VIRTUAL_ENV`, `CONDA_*`
    and everything else not allowlisted here never reach a setup child."""
    if platform == "win32":
        upper = {key.upper(): value for key, value in source.items()}
        env = {key: upper[key] for key in _WINDOWS_KEEP if upper.get(key)}
        system_root = env.get("SYSTEMROOT", r"C:\Windows")
        env["SYSTEMROOT"] = system_root
        env["PATH"] = f"{system_root}\\System32;{system_root}"
        return env
    env = {key: source[key] for key in _POSIX_KEEP if source.get(key)}
    env["PATH"] = POSIX_PATH
    return env


def _tail(handle: IO[bytes]) -> str:
    size = handle.seek(0, os.SEEK_END)
    handle.seek(max(0, size - OUTPUT_CAP_BYTES))
    return handle.read(OUTPUT_CAP_BYTES).decode("utf-8", errors="replace")


def run_capped(argv: Sequence[str], *, timeout: float, env: Mapping[str, str]) -> ProcResult:
    """The real Runner. Any interruption (timeout, Cancelled) kills the child
    before propagating — a cancelled setup never leaves pip running."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        try:
            proc = subprocess.Popen(  # noqa: S603 — argv list, no shell, scrubbed env
                list(argv), stdin=subprocess.DEVNULL, stdout=out, stderr=err, env=dict(env)
            )
        except OSError as exc:
            return ProcResult(None, "", type(exc).__name__, launch_error=True)
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        return ProcResult(
            None if timed_out else proc.returncode, _tail(out), _tail(err), timed_out=timed_out
        )


def redact(text: str, home: str) -> str:
    """For stderr logs only: the user's home folder becomes `~`."""
    return text.replace(home, "~") if home else text
