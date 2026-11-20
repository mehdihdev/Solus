"""Building one fork's environment — mcp-fork-runtime.md §3.

Into a temp sibling of `<envs>/<fork>`: `venv --copies` from the accepted base,
a health check that the copy runs and resolves inside the temp dir, a
hash-locked binary-only pip install, then the stamp; only then is the temp
dir swapped into place (the old env is removed after the new one is whole).
Any failure, timeout or cancellation discards the temp dir."""

import logging
import os
import shutil
import tempfile
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from solus_companion.runtime.errors import ErrorCode, RuntimeSetupError
from solus_companion.runtime.forks import ForkInfo
from solus_companion.runtime.ownership import OwnerOnly
from solus_companion.runtime.probe import ProbeReport, judge, run_probe
from solus_companion.runtime.proc import ProcResult, Runner, redact, scrubbed_env
from solus_companion.runtime.protocol import ProgressLine, RuntimeLine, clip
from solus_companion.runtime.roots import env_interpreter
from solus_companion.runtime.stamp import Stamp, StampBase, lock_sha256, write_stamp

logger = logging.getLogger("solus.companion.runtime")

VENV_TIMEOUT_SECONDS = 120.0
PIP_TIMEOUT_SECONDS = 600.0
PYPI_INDEX = "https://pypi.org/simple"
#: pip's defaults (5 retries is the default count, 15 s socket timeout) dropped the
#: KiCad lock's large wheels on ordinary connections; retries apply per request.
PIP_RETRIES = "5"
PIP_SOCKET_TIMEOUT_SECONDS = "60"
OUTPUT_TAIL_CHARS = 64 * 1024

_NETWORK_MARKERS = (
    "failed to establish a new connection",
    "name resolution",
    "nodename nor servname",
    "network is unreachable",
    "connection refused",
    "connecttimeout",
    "read timed out",
    "proxyerror",
    "sslerror",
    "certificate verify failed",
    # Dropped or stalled transfers mid-download (seen live on large wheels).
    "connection timed out",
    "incomplete-download",
    "connection broken",
    "connection reset",
    "remotedisconnected",
)
_HASH_MARKERS = ("do not match the hashes", "hash mismatch")
_WHEEL_MARKERS = ("no matching distribution found", "could not find a version that satisfies")
_DISK_MARKERS = ("no space left on device", "errno 28", "disk quota exceeded")


@dataclass(frozen=True)
class BaseInterpreter:
    path: str
    version: str
    managed: bool


@dataclass(frozen=True)
class ForkOutcome:
    fork: str
    outcome: Literal["ok", "failed", "skipped"]
    error_code: ErrorCode | None = None
    message: str = ""


def _has(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def classify_pip_failure(stderr: str) -> ErrorCode:
    """Bounded inspection of pip's (already 64 KiB-capped) stderr."""
    text = stderr[-OUTPUT_TAIL_CHARS:].lower()
    if _has(text, _DISK_MARKERS):
        return "disk_full"
    if _has(text, _HASH_MARKERS):
        return "hash_mismatch"
    if _has(text, _NETWORK_MARKERS):
        return "network_unreachable"
    if _has(text, _WHEEL_MARKERS):
        return "wheel_unavailable"
    return "pip_failed"


def count_requirements(lock: Path) -> int:
    """Pinned requirements in a hash-locked file (continuation lines excluded)."""
    try:
        lines = lock.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    return sum(1 for line in lines if line and not line[0].isspace() and line[0] not in "#-")


def venv_argv(base: str, target: Path) -> list[str]:
    return [base, "-I", "-m", "venv", "--copies", str(target)]


def pip_argv(python: Path, lock: Path) -> list[str]:
    return [
        str(python), "-I", "-m", "pip", "--isolated", "install", "--require-hashes",
        "--only-binary=:all:", "--no-deps", "--no-input", "--disable-pip-version-check",
        "--retries", PIP_RETRIES, "--timeout", PIP_SOCKET_TIMEOUT_SECONDS,
        "--index-url", PYPI_INDEX, "-r", str(lock),
    ]  # fmt: skip


class EnvBuilder:
    def __init__(
        self,
        *,
        envs_root: Path,
        runner: Runner,
        policy: OwnerOnly,
        emit: Callable[[RuntimeLine], object],
        platform: str,
        env_source: Mapping[str, str],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._envs = envs_root
        self._runner = runner
        self._policy = policy
        self._emit = emit
        self._platform = platform
        self._child_env = scrubbed_env(env_source, platform)
        self._home = env_source.get("HOME", "")
        self._now = now

    def build(self, fork: ForkInfo, base: BaseInterpreter) -> ForkOutcome:
        if fork.unavailable is not None:
            return ForkOutcome(fork.name, "skipped", message=clip(fork.unavailable))
        self._sweep(fork.name)
        tmp = Path(tempfile.mkdtemp(prefix=f".{fork.name}.build-", dir=self._envs))
        try:
            self._policy.ensure(tmp)
            python = self._create(fork.name, base, tmp)
            self._install(fork, python)
            self._stamp(fork, base, tmp)
            self._swap(fork.name, tmp)
        except RuntimeSetupError as failure:
            logger.warning("fork %s setup failed: %s", fork.name, failure.code)
            return ForkOutcome(fork.name, "failed", failure.code, clip(failure.message))
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        return ForkOutcome(fork.name, "ok")

    def _progress(self, fork: str, step: str, done: int, total: int | None) -> None:
        self._emit(ProgressLine(fork=fork, step=step, done=done, total=total))  # type: ignore[arg-type]

    def _run(self, argv: list[str], timeout: float) -> ProcResult:
        return self._runner(argv, timeout=timeout, env=self._child_env)

    def _log_failure(self, what: str, result: ProcResult) -> None:
        logger.warning(
            "%s failed (rc=%s): %s",
            what,
            result.returncode,
            redact(result.stderr[-2000:], self._home),
        )

    def _create(self, fork: str, base: BaseInterpreter, tmp: Path) -> Path:
        self._progress(fork, "venv", 0, None)
        result = self._run(venv_argv(base.path, tmp), VENV_TIMEOUT_SECONDS)
        if not result.ok:
            self._log_failure("venv", result)
            if result.timed_out:
                raise RuntimeSetupError("timeout")
            disk = _has(result.stderr.lower(), _DISK_MARKERS)
            raise RuntimeSetupError("disk_full" if disk else "venv_failed")
        python = env_interpreter(tmp, self._platform)
        if not self._healthy(python, tmp):
            raise RuntimeSetupError("venv_copies_unhealthy")
        self._progress(fork, "check", 1, 1)
        return python

    def _healthy(self, python: Path, tmp: Path) -> bool:
        """The copy starts in isolated mode, imports the stdlib (the probe uses
        json/platform), is a supported CPython, and RESOLVES inside the temp dir."""
        if python.is_symlink() or not python.is_file():
            return False
        report: ProbeReport | None = run_probe(str(python), self._runner, self._child_env)
        if report is None or not judge(report, allow_venv=True).supported:
            return False
        inside = tmp.resolve()
        return all(
            Path(os.path.realpath(p)).is_relative_to(inside) for p in (python, report.executable)
        )

    def _install(self, fork: ForkInfo, python: Path) -> None:
        total = count_requirements(fork.lock)
        self._progress(fork.name, "install", 0, total)
        result = self._run(pip_argv(python, fork.lock), PIP_TIMEOUT_SECONDS)
        if not result.ok:
            self._log_failure("pip install", result)
            raise RuntimeSetupError(
                "timeout"
                if result.timed_out
                else classify_pip_failure(result.stderr + "\n" + result.stdout)
            )
        self._progress(fork.name, "install", total, total)

    def _stamp(self, fork: ForkInfo, base: BaseInterpreter, tmp: Path) -> None:
        stamp = Stamp(
            schema_version=1,
            fork=fork.name,
            lock_sha256=lock_sha256(fork.lock),
            base=StampBase(
                path=base.path,
                version=base.version,
                implementation="cpython",
                managed=base.managed,
            ),
            created_at=self._now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        write_stamp(tmp, stamp)
        self._progress(fork.name, "stamp", 1, 1)

    def _swap(self, fork: str, tmp: Path) -> None:
        """Replace whole, never patch: the old env moves aside, the new one
        takes its name, then the old one is deleted."""
        dest = self._envs / fork
        old: Path | None = None
        if dest.exists() or dest.is_symlink():
            old = self._envs / f".{fork}.old-{uuid.uuid4().hex[:8]}"
            os.replace(dest, old)
        os.replace(tmp, dest)
        if old is not None:
            remove_path(old)

    def _sweep(self, fork: str) -> None:
        """Leftovers from a crashed or killed earlier run of THIS fork."""
        for prefix in (f".{fork}.build-", f".{fork}.old-"):
            for stale in self._envs.glob(prefix + "*"):
                remove_path(stale)


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    else:
        shutil.rmtree(path, ignore_errors=True)
