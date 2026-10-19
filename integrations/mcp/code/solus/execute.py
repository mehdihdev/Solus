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

import contextlib
import logging
import os
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Event
from typing import IO, Any

from . import profiles, sandbox
from .plan import Plan
from .process_os import OBSERVE_SECONDS, TreeTracker
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
#: How often a running command's descendant tree is snapshotted.
TREE_SNAPSHOT_SECONDS = OBSERVE_SECONDS
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
    """`shutil.which` over SEARCH_ROOTS only; never a program in the writable set (§9.5)."""
    found = shutil.which(name, path=search_path())
    return None if found is None or sandbox.foreign_writable(found, None) else found


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


def _tail(handle: IO[bytes], tail_bytes: int = MAX_TAIL_BYTES) -> bytes:
    handle.seek(0, os.SEEK_END)
    handle.seek(max(0, handle.tell() - tail_bytes))
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


@dataclass
class _Spools:
    """Private output spools with independent read descriptors (reading never seeks
    the child's shared write offset)."""

    out: IO[bytes]
    err: IO[bytes]
    out_reader: IO[bytes]
    err_reader: IO[bytes]

    def readers(self) -> tuple[tuple[str, IO[bytes]], ...]:
        return (("stdout", self.out_reader), ("stderr", self.err_reader))


@contextlib.contextmanager
def _spools() -> Iterator[_Spools]:
    with tempfile.TemporaryDirectory(prefix="solus-command-") as directory:
        base = Path(directory)
        with (
            open(base / "stdout", "w+b") as out,
            open(base / "stderr", "w+b") as err,
            open(base / "stdout", "rb") as out_reader,
            open(base / "stderr", "rb") as err_reader,
        ):
            yield _Spools(out, err, out_reader, err_reader)


def _spawn(argv: list[str], cwd: Path, env: dict[str, str], spools: _Spools) -> Any:
    return subprocess.Popen(  # noqa: S603 - validated argv, no shell
        argv,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=spools.out,
        stderr=spools.err,
        start_new_session=True,
        close_fds=True,
        pass_fds=sandbox.PASS_FDS.get(),
    )


def _supervise(
    proc: subprocess.Popen[bytes],
    spools: _Spools,
    observer: LineOutput,
    deadline: float,
    cancelled: Event | None,
) -> bool:
    """Stream output and snapshot the descendant tree until the leader exits; kill the
    group on the deadline or a cancel. Then kill whatever it left behind (its group and
    descendants that left the group), so a git metadata check afterwards sees the
    command's final effect. True when it timed out (or was cancelled)."""
    tree = TreeTracker(proc.pid)
    snapshot_at = time.monotonic() + TREE_SNAPSHOT_SECONDS
    timed_out = False
    while proc.poll() is None:
        if time.monotonic() >= snapshot_at:
            tree.observe()
            snapshot_at = time.monotonic() + TREE_SNAPSHOT_SECONDS
        for stream, reader in spools.readers():
            observer.feed(stream, reader.read(8192))
        if time.monotonic() >= deadline or (cancelled is not None and cancelled.is_set()):
            timed_out = True
            _kill_group(proc)
            break
        time.sleep(0.025)
    proc.wait()
    _kill_group(proc)
    tree.kill(signal.SIGKILL)
    for stream, reader in spools.readers():
        _drain_output(observer, stream, reader, deadline, cancelled)
    observer.finish()
    return timed_out


def default_runner(
    argv: list[str],
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
    *,
    tail_bytes: int = MAX_TAIL_BYTES,
) -> Outcome:
    """argv list, no shell, own session, closed stdin, spooled output (last
    `tail_bytes` of each stream kept)."""
    with _spools() as spools:
        cancelled = CANCEL_EVENT.get()
        if cancelled is not None and cancelled.is_set():
            return Outcome(None, b"", b"", True)
        proc = _spawn(argv, cwd, env, spools)
        observer = LineOutput(OUTPUT_CALLBACK.get())
        deadline = time.monotonic() + timeout_seconds
        try:
            timed_out = _supervise(proc, spools, observer, deadline, cancelled)
        finally:
            if proc.poll() is None:
                _kill_group(proc)
                proc.wait()
        return Outcome(
            None if timed_out else proc.returncode,
            _tail(spools.out, tail_bytes),
            _tail(spools.err, tail_bytes),
            timed_out,
        )


def resolve_executable(root: Path, argv0: str, which: Which = pinned_which) -> str | None:
    """An absolute program (already resolved by the planner) must still be an
    executable file; a workspace-relative interpreter must sit inside the
    workspace (its directory is confined; the file itself may be the symlink
    every venv has); a bare name resolves against SEARCH_ROOTS. Whatever it
    resolves to, its realpath may not lie in the writable set outside the
    workspace (§9.5)."""
    found = _locate(root, argv0, which)
    return None if found is None or sandbox.foreign_writable(found, root) else found


def _locate(root: Path, argv0: str, which: Which) -> str | None:
    if os.path.isabs(argv0):
        return argv0 if os.path.isfile(argv0) and os.access(argv0, os.X_OK) else None
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
        "sandbox": None,
        "git_metadata_changed": False,
    }


def child_env(root: Path, plan: Plan) -> dict[str, str]:
    """The scrubbed environment, overlaid with the plan's profile when it has one."""
    env = scrubbed_env(root, plan.environment)
    if plan.profile is not None:
        venv_bin = str(venv_bin_dir(root, plan.environment)) if plan.environment else None
        env = profiles.apply(env, plan.profile.variables, venv_bin)
    return {name: value for name, value in env.items() if name not in profiles.LOADER_NAMES}


@dataclass(frozen=True)
class Prepared:
    """The sandboxed argv, working directory and environments of an ok plan. `env`
    is what the spawned program gets (the Linux helper's fixed environment);
    `child_env` is what the command itself runs with; `pass_fds` must be inherited
    by the spawned program and closed by the caller afterwards (`close`)."""

    argv: list[str]
    cwd: Path
    env: dict[str, str]
    child_env: dict[str, str]
    pass_fds: tuple[int, ...] = ()

    def close(self) -> None:
        for descriptor in self.pass_fds:
            with contextlib.suppress(OSError):
                os.close(descriptor)

    @contextlib.contextmanager
    def handing_over(self) -> Iterator[None]:
        """Within this block the spawners pass `pass_fds`; afterwards they are closed."""
        token = sandbox.PASS_FDS.set(self.pass_fds)
        try:
            yield
        finally:
            sandbox.PASS_FDS.reset(token)
            self.close()


@dataclass(frozen=True)
class Ran:
    outcome: Outcome
    duration_ms: int
    git_metadata_changed: bool
    env: dict[str, str]


PROGRAM_CHANGED = "the program changed after it was planned"


def _program_changed(root: Path, plan: Plan, executable: str) -> bool:
    """True when the program about to run is not the one the plan described: its
    realpath or its scope differs. The planned path itself still runs (a venv
    interpreter must be started through its link). Plans not made by `plan_action`
    carry no scope and are not compared."""
    if plan.program_scope is None:
        return False
    from .command_plan import program_scope

    scope = program_scope(root, plan.argv, executable, plan.setup_file)
    return os.path.realpath(executable) != plan.program_realpath or scope != plan.program_scope


def prepare(root: Path, plan: Plan, which: Which = pinned_which) -> Prepared | str:
    """Resolve argv[0], wrap in the sandbox, or say why nothing may run."""
    if not plan.ok:
        return plan.reason or "refused"
    if plan.sandbox is None:
        return "sandbox unavailable: the plan carries no sandbox"
    executable = resolve_executable(root, plan.argv[0], which)
    if executable is None:
        return f"executable not found: {plan.argv[0][:64]}"
    if _program_changed(root, plan, executable):
        return PROGRAM_CHANGED
    cwd = root if plan.cwd == "." else resolve_inside(plan.cwd, root)
    if cwd is None:
        return "cwd is no longer inside the linked folder"
    env = child_env(root, plan)
    program = [executable, *plan.argv[1:]]
    if not plan.sandbox.startswith(sandbox.KIND_LINUX):
        try:
            return Prepared(sandbox.wrap(plan.sandbox, program, workspace=root), cwd, env, env)
        except ValueError as exc:
            return str(exc)
    try:
        descriptor = sandbox.env_descriptor(env)
    except (ValueError, OSError) as exc:
        return str(exc)
    try:
        wrapped = sandbox.wrap(plan.sandbox, program, workspace=root, env_fd=descriptor)
    except ValueError as exc:
        os.close(descriptor)
        return str(exc)
    return Prepared(wrapped, cwd, sandbox.helper_env(env), env, (descriptor,))


def run_sandboxed(
    root: Path, plan: Plan, *, runner: Runner = default_runner, which: Which = pinned_which
) -> Ran | str:
    """Run the prepared plan; detect git metadata changes around it."""
    prepared = prepare(root, plan, which)
    if isinstance(prepared, str):
        return prepared
    before = sandbox.git_metadata_digest(root)
    started = time.monotonic()
    try:
        with prepared.handing_over():
            outcome = runner(prepared.argv, prepared.cwd, prepared.env, plan.timeout_seconds)
    except (OSError, ValueError) as exc:
        logger.warning("%s could not start: %s", plan.action, type(exc).__name__)
        return f"could not start: {type(exc).__name__}"
    duration_ms = int((time.monotonic() - started) * 1000)
    changed = sandbox.git_metadata_digest(root) != before
    if changed:
        logger.warning("%s changed .git/hooks or .git/config", plan.action)
    return Ran(outcome, duration_ms, changed, prepared.child_env)


def execute_plan(
    root: Path, plan: Plan, *, runner: Runner = default_runner, which: Which = pinned_which
) -> dict[str, Any]:
    """Run EXACTLY `plan.argv` (argv[0] resolved as documented) inside the
    sandbox and answer the §4 result shape. Never raises."""
    ran = run_sandboxed(root, plan, runner=runner, which=which)
    if isinstance(ran, str):
        return refusal(ran)
    outcome = ran.outcome
    return {
        "ok": outcome.exit_code == 0 and not outcome.timed_out,
        "argv": list(plan.argv),
        "cwd": plan.cwd,
        "exit_code": outcome.exit_code,
        "stdout_tail": tail_text(outcome.stdout),
        "stderr_tail": tail_text(outcome.stderr),
        "duration_ms": ran.duration_ms,
        "timed_out": outcome.timed_out,
        "reason": f"timed out after {plan.timeout_seconds} s" if outcome.timed_out else None,
        "sandbox": plan.sandbox,
        "git_metadata_changed": ran.git_metadata_changed,
    }
