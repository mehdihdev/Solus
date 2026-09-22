"""Bounded execution of a `Plan` (docs/api/code-environment.md §4).

The child runs with `cwd` = the workspace, a SCRUBBED environment (`PATH` =
the venv's bin dir + `/usr/bin:/bin`, `HOME`, `LANG`, `TMPDIR`, `VIRTUAL_ENV`
= the workspace venv — never the inherited one), `start_new_session=True`
so a timeout kills the whole process group, stdin closed, and stdout/stderr
spooled to temp files then TAILED to MAX_TAIL_BYTES each (memory is bounded
by the tail, not by what the child prints). `argv[0]` is resolved here: a
workspace-relative interpreter (`.venv/bin/python`) must live inside the
workspace; a bare tool name (`uv`, `python3.12`) is resolved against the
PINNED search roots below — never the inherited PATH. Never raises.
"""

import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Event
from typing import IO, Any

from .plan import Plan
from .progress import CANCEL_EVENT, OUTPUT_CALLBACK, LineOutput
from .workspace import resolve_inside

logger = logging.getLogger("solus.code.execute")

#: Where bare tool names (`uv`, `python3.12`, `conda`) may resolve from — a
#: fixed, documented list (CLAUDE.md §7 "binaries pinned to expected paths"),
#: NOT the inherited PATH (the launcher pins that to /usr/bin:/bin anyway).
SEARCH_ROOTS: tuple[str, ...] = (
    "/usr/bin",
    "/bin",
    "/usr/local/bin",
    "/opt/homebrew/bin",
    "/opt/conda/bin",
    "/opt/miniconda3/bin",
    "~/.local/bin",
    "~/.cargo/bin",
    "~/miniconda3/bin",
    "~/anaconda3/bin",
    "~/miniforge3/bin",
    "~/mambaforge/bin",
)
#: The child's PATH tail — the venv's bin dir is prepended when there is one.
CHILD_PATH = "/usr/bin:/bin"
#: Names copied from the server's own (already scrubbed) environment.
PASSTHROUGH_NAMES: tuple[str, ...] = ("HOME", "LANG", "TMPDIR")
MAX_TAIL_BYTES = 16 * 1024
_VENV_BIN_DIRS = ("bin", "Scripts")

Which = Callable[[str], str | None]


@dataclass(frozen=True)
class Outcome:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool


Runner = Callable[[list[str], Path, dict[str, str], int], Outcome]


def search_path() -> str:
    return os.pathsep.join(os.path.expanduser(root) for root in SEARCH_ROOTS)


def pinned_which(name: str) -> str | None:
    """`shutil.which` over SEARCH_ROOTS only."""
    return shutil.which(name, path=search_path())


def venv_bin_dir(root: Path, environment: str) -> Path:
    base = root / environment
    for name in _VENV_BIN_DIRS:
        if (base / name).is_dir():
            return base / name
    return base / _VENV_BIN_DIRS[0]


def scrubbed_env(root: Path, environment: str | None) -> dict[str, str]:
    """Exactly the §4 names: PATH, HOME, LANG, TMPDIR, VIRTUAL_ENV."""
    env = {name: os.environ[name] for name in PASSTHROUGH_NAMES if os.environ.get(name)}
    path = CHILD_PATH
    if environment:
        env["VIRTUAL_ENV"] = str(root / environment)
        path = f"{venv_bin_dir(root, environment)}{os.pathsep}{CHILD_PATH}"
    return {**env, "PATH": path}


def _tail(handle: IO[bytes]) -> bytes:
    handle.seek(0, os.SEEK_END)
    handle.seek(max(0, handle.tell() - MAX_TAIL_BYTES))
    return handle.read()


def tail_text(data: bytes) -> str:
    return data[-MAX_TAIL_BYTES:].decode("utf-8", errors="replace")


def _kill_group(proc: subprocess.Popen[bytes]) -> None:
    killpg = getattr(os, "killpg", None)
    try:
        if killpg is None:
            proc.kill()
        else:
            killpg(proc.pid, signal.SIGKILL)
    except OSError:
        proc.kill()


def _drain_output(
    observer: LineOutput, stream: str, reader: IO[bytes], deadline: float, cancelled: Event | None
) -> None:
    """Never follow a descendant's still-growing spool indefinitely after parent exit."""
    for _ in range(32):  # at most 256 KiB scanned per stream after exit
        if observer.callback is None or observer.discard[stream]:
            return
        if time.monotonic() >= deadline or (cancelled is not None and cancelled.is_set()):
            break
        data = reader.read(8192)
        if not data:
            return
        observer.feed(stream, data)
    observer.suppress(stream)


def default_runner(
    argv: list[str], cwd: Path, env: dict[str, str], timeout_seconds: int
) -> Outcome:
    """argv list, no shell, own session, closed stdin, spooled output."""
    # Private spools and independent read descriptors are established before launch.
    # Reading never seeks the child's shared write offset.
    with tempfile.TemporaryDirectory(prefix="solus-command-") as directory:
        with (
            open(Path(directory) / "stdout", "w+b") as out,
            open(Path(directory) / "stderr", "w+b") as err,
            open(Path(directory) / "stdout", "rb") as out_reader,
            open(Path(directory) / "stderr", "rb") as err_reader,
        ):
            cancelled = CANCEL_EVENT.get()
            if cancelled is not None and cancelled.is_set():
                return Outcome(None, b"", b"", True)
            proc = subprocess.Popen(  # noqa: S603 - validated argv, no shell
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                start_new_session=True,
                close_fds=True,
            )
            observer = LineOutput(OUTPUT_CALLBACK.get())
            deadline = time.monotonic() + timeout_seconds
            timed_out = False
            try:
                while proc.poll() is None:
                    observer.feed("stdout", out_reader.read(8192))
                    observer.feed("stderr", err_reader.read(8192))
                    if time.monotonic() >= deadline or (cancelled and cancelled.is_set()):
                        timed_out = True
                        _kill_group(proc)
                        break
                    time.sleep(0.025)
                proc.wait()
                for stream, reader in (("stdout", out_reader), ("stderr", err_reader)):
                    _drain_output(observer, stream, reader, deadline, cancelled)
                observer.finish()
            finally:
                if proc.poll() is None:
                    _kill_group(proc)
                    proc.wait()
            return Outcome(
                None if timed_out else proc.returncode, _tail(out), _tail(err), timed_out
            )


def resolve_executable(root: Path, argv0: str, which: Which = pinned_which) -> str | None:
    """A workspace-relative interpreter must sit inside the workspace (its
    directory is confined; the file itself may be the symlink every venv
    has); a bare name resolves against SEARCH_ROOTS."""
    if "/" not in argv0:
        return which(argv0)
    parent = resolve_inside(str(PurePosixPath(argv0).parent), root)
    candidate = root / argv0
    if parent is None or not candidate.is_file() or not os.access(candidate, os.X_OK):
        return None
    return str(candidate)


def refusal(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "argv": [],
        "cwd": ".",
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "duration_ms": 0,
        "timed_out": False,
        "reason": reason,
    }


def execute_plan(
    root: Path, plan: Plan, *, runner: Runner = default_runner, which: Which = pinned_which
) -> dict[str, Any]:
    """Run EXACTLY `plan.argv` (argv[0] resolved as documented) and answer the
    §4 result shape. Never raises."""
    if not plan.ok:
        return refusal(plan.reason or "refused")
    executable = resolve_executable(root, plan.argv[0], which)
    if executable is None:
        return refusal(f"executable not found: {plan.argv[0][:64]}")
    started = time.monotonic()
    try:
        outcome = runner(
            [executable, *plan.argv[1:]],
            root,
            scrubbed_env(root, plan.environment),
            plan.timeout_seconds,
        )
    except (OSError, ValueError) as exc:
        logger.warning("%s could not start: %s", plan.action, type(exc).__name__)
        return refusal(f"could not start: {type(exc).__name__}")
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "ok": outcome.exit_code == 0 and not outcome.timed_out,
        "argv": list(plan.argv),
        "cwd": ".",
        "exit_code": outcome.exit_code,
        "stdout_tail": tail_text(outcome.stdout),
        "stderr_tail": tail_text(outcome.stderr),
        "duration_ms": duration_ms,
        "timed_out": outcome.timed_out,
        "reason": f"timed out after {plan.timeout_seconds} s" if outcome.timed_out else None,
    }
