"""Bounded owned processes and a closed Linux execution sandbox."""

from __future__ import annotations

import hashlib
import json
import os
import selectors
import signal
import stat
import subprocess
import time
from contextvars import ContextVar
from pathlib import Path
from threading import Event, Lock
from typing import Any

from .arduino_toolchain import ArduinoError
from .progress import OUTPUT_CALLBACK, LineOutput

HARD_OUTPUT_BYTES = 1024 * 1024
TAIL_BYTES = 16 * 1024
BWRAP = Path("/usr/bin/bwrap")
_CLI_IMAGES: dict[str, int] = {}
_CLI_IMAGE_LOCK = Lock()
CANCEL_EVENT: ContextVar[Event | None] = ContextVar("arduino_cancel_event", default=None)


def cancelled() -> bool:
    event = CANCEL_EVENT.get()
    return event is not None and event.is_set()


def check_deadline(deadline: float) -> None:
    if cancelled() or time.monotonic() >= deadline:
        raise ArduinoError("resource_limit")


def closed_environment(root: Path) -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(root / "home"),
        "TMPDIR": str(root / "tmp"),
        "LANG": "C",
        "LC_ALL": "C",
    }


def sandbox_argv(
    cli: Path,
    writable: Path,
    argv: tuple[str, ...],
    *,
    packages: Path | None = None,
    writable_fd: int | None = None,
    packages_fd: int | None = None,
    device_fd: int | None = None,
    upload: bool = False,
    preview: bool = False,
) -> tuple[str, ...]:
    try:
        info = BWRAP.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ArduinoError("toolchain_unavailable")
        if not os.access(BWRAP, os.X_OK):
            raise ArduinoError("toolchain_unavailable")
    except OSError:
        raise ArduinoError("toolchain_unavailable") from None
    if not preview and writable_fd is None:
        raise ArduinoError("toolchain_unavailable")
    descriptor = "<verified-cli-fd>" if preview else str(sealed_cli(cli))
    writable_source = "<held-job-fd>" if preview else str(writable_fd)
    command = [
        str(BWRAP),
        "--unshare-all",
        "--die-with-parent",
        "--cap-drop",
        "ALL",
        "--dir",
        "/usr",
        "--ro-bind",
        "/usr/bin",
        "/usr/bin",
        "--dir",
        "/usr/lib",
        "--ro-bind",
        "/usr/lib/aarch64-linux-gnu",
        "/usr/lib/aarch64-linux-gnu",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/bin",
        "/bin",
        "--symlink",
        "aarch64-linux-gnu/ld-linux-aarch64.so.1",
        "/usr/lib/ld-linux-aarch64.so.1",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",  # noqa: S108 — private sandbox tmpfs
        "--perms",
        "0555",
        "--ro-bind-data",
        descriptor,
        str(cli),
        "--bind-fd",
        writable_source,
        str(writable),
    ]
    if packages is not None:
        if not preview and packages_fd is None:
            raise ArduinoError("toolchain_unavailable")
        package_source = "<verified-packages-fd>" if preview else str(packages_fd)
        command.extend(["--ro-bind-fd", package_source, str(writable / "data/packages")])
    if upload:
        if not preview and (device_fd is None or not stat.S_ISCHR(os.fstat(device_fd).st_mode)):
            raise ArduinoError("device_unavailable")
        source = "<held-device-fd>" if preview else str(device_fd)
        command.extend(["--dev-bind", f"/proc/self/fd/{source}", "/dev/solus-upload"])
    elif device_fd is not None:
        raise ArduinoError("invalid_arguments")
    command.extend(["--chdir", str(writable), "--", *argv])
    return tuple(command)


def sealed_cli(cli: Path) -> int:
    """Bind execution to immutable verified bytes, not a replaceable filesystem path."""
    import fcntl

    from .arduino_install import read_bounded
    from .arduino_toolchain import CLI_SHA256, _regular_digest

    if _regular_digest(cli) != CLI_SHA256:
        raise ArduinoError("cli_unavailable")
    with _CLI_IMAGE_LOCK:
        if CLI_SHA256 in _CLI_IMAGES:
            return _CLI_IMAGES[CLI_SHA256]
        if len(_CLI_IMAGES) >= 4:
            raise ArduinoError("resource_limit")
        body = read_bounded(cli, 64 * 1024**2)
        if hashlib.sha256(body).hexdigest() != CLI_SHA256:
            raise ArduinoError("cli_unavailable")
        descriptor = os.memfd_create("solus-arduino-cli", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        try:
            view = memoryview(body)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fchmod(descriptor, 0o555)
            fcntl.fcntl(
                descriptor,
                fcntl.F_ADD_SEALS,
                fcntl.F_SEAL_SEAL | fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK,
            )
            _CLI_IMAGES[CLI_SHA256] = descriptor
            return descriptor
        except BaseException:
            os.close(descriptor)
            raise


def _device_descriptor(source: str, destination: str) -> int:
    prefix = "/proc/self/fd/"
    if not source.startswith(prefix) or not source[len(prefix) :].isdecimal():
        raise ArduinoError("device_unavailable")
    descriptor = int(source[len(prefix) :])
    if not stat.S_ISCHR(os.fstat(descriptor).st_mode) or destination != "/dev/solus-upload":
        raise ArduinoError("device_unavailable")
    return descriptor


def _sandbox_descriptors(argv: list[str]) -> tuple[tuple[int, ...], list[int]]:
    """Allocate independent read positions for sealed byte inputs; never share offsets."""
    if not argv or argv[0] != str(BWRAP):
        return (), []
    descriptors: set[int] = set()
    copies: list[int] = []
    try:
        for index, argument in enumerate(argv[:-1]):
            if argument == "--dev-bind":
                descriptors.add(_device_descriptor(argv[index + 1], argv[index + 2]))
                continue
            if argument not in {"--bind-fd", "--ro-bind-fd", "--ro-bind-data"}:
                continue
            value = argv[index + 1]
            if not value.isdecimal():
                raise ArduinoError("toolchain_unavailable")
            descriptor = int(value)
            os.fstat(descriptor)
            if argument == "--ro-bind-data":
                if descriptor not in _CLI_IMAGES.values():
                    raise ArduinoError("cli_unavailable")
                descriptor = os.open(f"/proc/self/fd/{descriptor}", os.O_RDONLY | os.O_CLOEXEC)
                copies.append(descriptor)
                argv[index + 1] = str(descriptor)
            descriptors.add(descriptor)
        return tuple(sorted(descriptors)), copies
    except BaseException:
        for descriptor in copies:
            os.close(descriptor)
        raise


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=3)


def run_bounded(
    argv: list[str] | tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    deadline: float,
    expect_json_success: bool = False,
) -> dict[str, Any]:
    """Run an owned argv; drain both pipes and kill the group on every interrupted path."""
    if deadline <= time.monotonic() or cancelled():
        is_timeout = not cancelled()
        return {
            **_result(
                None,
                [bytearray(), bytearray()],
                [0, 0],
                "deadline_exceeded" if is_timeout else "cancelled",
                is_timeout,
            ),
            "started": False,
        }
    tails = [bytearray(), bytearray()]
    counts = [0, 0]
    reason: str | None = None
    timed_out = False
    command = list(argv)
    descriptors, copies = _sandbox_descriptors(command)
    try:
        process = subprocess.Popen(  # noqa: S603 — caller supplies fixed owned argv, never shell
            command,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,
            pass_fds=descriptors,
        )
    except OSError:
        raise ArduinoError("toolchain_unavailable") from None
    finally:
        for descriptor in copies:
            os.close(descriptor)
    try:
        assert process.stdout is not None and process.stderr is not None
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, 0)
            selector.register(process.stderr, selectors.EVENT_READ, 1)
            reason, timed_out = _drain(selector, tails, counts, deadline)

        if reason:
            _terminate(process)
            return _result(None, tails, counts, reason, timed_out)
        code, reason, timed_out = _wait_closed_pipes(process, deadline)
        return _result(code, tails, counts, reason, timed_out, expect_json_success)
    except BaseException:
        _terminate(process)
        raise
    finally:
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()


def _wait_closed_pipes(
    process: subprocess.Popen[bytes], deadline: float
) -> tuple[int | None, str | None, bool]:
    while process.poll() is None:
        if cancelled() or time.monotonic() >= deadline:
            is_timeout = not cancelled()
            _terminate(process)
            return None, "deadline_exceeded" if is_timeout else "cancelled", is_timeout
        time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
    return process.returncode, None if process.returncode == 0 else "command_failed", False


def _drain(
    selector: selectors.BaseSelector, tails: list[bytearray], counts: list[int], deadline: float
) -> tuple[str | None, bool]:
    output = LineOutput(OUTPUT_CALLBACK.get())
    while selector.get_map():
        if cancelled():
            return "cancelled", False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "deadline_exceeded", True
        for key, _ in selector.select(min(0.1, remaining)):
            chunk = os.read(key.fd, 8192)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            index = int(key.data)
            output.feed("stdout" if index == 0 else "stderr", chunk)
            counts[index] += len(chunk)
            tails[index].extend(chunk)
            if counts[index] > HARD_OUTPUT_BYTES:
                return "resource_limit", False
    output.finish()
    return None, False


def _result(
    code: int | None,
    tails: list[bytearray],
    counts: list[int],
    reason: str | None,
    timed_out: bool,
    expect_json_success: bool = False,
) -> dict[str, Any]:
    if code == 0 and reason is None and expect_json_success and not _successful_json(tails[0]):
        reason = "compilation_unverified"
    return {
        "ok": code == 0 and reason is None,
        "started": True,
        "exit_code": code,
        "reason": reason,
        "stdout_tail": tails[0][-TAIL_BYTES:].decode("utf-8", errors="replace"),
        "stderr_tail": tails[1][-TAIL_BYTES:].decode("utf-8", errors="replace"),
        "stdout_truncated": counts[0] > min(TAIL_BYTES, HARD_OUTPUT_BYTES),
        "stderr_truncated": counts[1] > min(TAIL_BYTES, HARD_OUTPUT_BYTES),
        "timed_out": timed_out,
    }


def _successful_json(body: bytearray) -> bool:
    """Validate the complete hard-capped report without returning its private contents."""
    try:
        report = json.loads(body)
    except (ValueError, RecursionError):
        return False
    return isinstance(report, dict) and report.get("success") is True
