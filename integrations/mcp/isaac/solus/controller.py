"""Own one bounded Isaac process and its private control pipe."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import select
import signal
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from uuid import uuid4

from .runtime import MAX_FRAME, RUNTIME, child_environment


class Controller:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve(strict=True)
        self.process: subprocess.Popen[bytes] | None = None
        self.session: str | None = None
        self.closed = False
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.sequence = 0
        self.request_fd = -1
        self.reply_fd = -1
        self.private: tempfile.TemporaryDirectory[str] | None = None
        self.log_tail = bytearray()

    def probe(self) -> dict[str, Any]:
        paths = [
            RUNTIME / "python.sh",
            RUNTIME / "setup_python_env.sh",
            RUNTIME / "VERSION",
            RUNTIME / "kit/python/bin/python3",
        ]
        available = (
            platform.system() == "Linux"
            and platform.machine() == "aarch64"
            and all(p.is_file() for p in paths)
        )
        digest = hashlib.sha256()
        if available:
            for path in paths:
                digest.update(str(path.resolve()).encode())
                digest.update(path.read_bytes())
        return {
            "available": available,
            "platform": platform.system(),
            "architecture": platform.machine(),
            "runtime_fingerprint": digest.hexdigest() if available else None,
        }

    def status(self) -> dict[str, Any]:
        return {
            "state": "running"
            if self.process is not None and self.process.poll() is None
            else "stopped",
            "session_id": self.session,
        }

    def start(self, *, dry_run: bool) -> dict[str, Any]:
        with self.lock:
            if self.closed:
                raise ValueError("controller closed")
            probe = self.probe()
            if self.process is not None:
                raise ValueError("operation busy")
            if not probe["available"]:
                raise ValueError("runtime unavailable")
            if dry_run:
                return {
                    "ok": True,
                    "dry_run": True,
                    "runtime": probe,
                    "preview": [
                        {
                            "label": "Isaac session",
                            "before": "stopped",
                            "after": "Start one owned headless Isaac session; no model loaded",
                        },
                        {"label": "Runtime", "before": None, "after": str(RUNTIME / "python.sh")},
                        {
                            "label": "Owned entrypoint",
                            "before": None,
                            "after": str(Path(__file__).with_name("worker.py").resolve()),
                        },
                        {
                            "label": "Runtime identity",
                            "before": None,
                            "after": ":".join(
                                str(probe["runtime_fingerprint"])[i : i + 16]
                                for i in range(0, 64, 16)
                            ),
                        },
                        {
                            "label": "Configuration",
                            "before": None,
                            "after": (
                                "Headless; private inherited pipes; isolated temporary HOME/cache; "
                                "registry and telemetry disabled; no input model"
                            ),
                        },
                        {
                            "label": "Lifetime",
                            "before": None,
                            "after": (
                                "Startup at most 180 seconds; cleanup only owned process group; "
                                "simulator uses local CPU/GPU"
                            ),
                        },
                    ],
                    "fingerprint": probe["runtime_fingerprint"],
                }
            self._spawn()
            threading.Thread(target=self._drain, daemon=True).start()
            try:
                ready = self._read(180)
                if ready != {"ready": True, "generation": self.session}:
                    raise ValueError("invalid startup reply")
                self.exchange("status", {}, timeout=5)
            except (ValueError, OSError, TimeoutError):
                self._terminate()
                raise
            return {
                "ok": True,
                **self.status(),
                "runtime_fingerprint": probe["runtime_fingerprint"],
            }

    def _spawn(self) -> None:
        try:
            self.private = tempfile.TemporaryDirectory(prefix="solus-isaac-")
            private = Path(self.private.name)
            with ExitStack() as cleanup:
                workspace_fd = os.open(self.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                cleanup.callback(os.close, workspace_fd)
                request_read, self.request_fd = os.pipe()
                cleanup.callback(os.close, request_read)
                os.set_blocking(self.request_fd, False)
                self.reply_fd, reply_write = os.pipe()
                cleanup.callback(os.close, reply_write)
                self.session = str(uuid4())
                self.sequence = 0
                worker = Path(__file__).with_name("worker.py").resolve()
                argv = [
                    str(RUNTIME / "python.sh"),
                    str(worker),
                    str(request_read),
                    str(reply_write),
                    self.session,
                    str(workspace_fd),
                    "--/app/extensions/registryEnabled=false",
                    "--/telemetry/enableNVDF=false",
                    "--/telemetry/enableSentry=false",
                    "--/telemetry/enableAnonymousData=false",
                ]
                self.process = subprocess.Popen(  # noqa: S603 — fixed runtime/worker and owned FDs
                    argv,
                    cwd=private,
                    env=child_environment(private),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    pass_fds=(request_read, reply_write, workspace_fd),
                    start_new_session=True,
                )
        except (OSError, ValueError):
            self._terminate()
            raise

    def _drain(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        while data := process.stdout.read(4096):
            self.log_tail.extend(data)
            del self.log_tail[:-8192]

    def _read(self, timeout: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        data = bytearray()
        while time.monotonic() < deadline:
            if self.cancelled.is_set():
                raise ValueError("controller cancelled")
            if self.process is None or self.process.poll() is not None:
                raise ValueError("worker exited")
            if select.select(
                [self.reply_fd], [], [], min(0.2, max(0, deadline - time.monotonic()))
            )[0]:
                byte = os.read(self.reply_fd, 1)
                if not byte:
                    raise ValueError("worker pipe closed")
                if byte == b"\n":
                    value = json.loads(data)
                    if not isinstance(value, dict):
                        raise ValueError("invalid reply")
                    return value
                data.extend(byte)
                if len(data) > MAX_FRAME:
                    raise ValueError("worker reply too large")
        raise TimeoutError("Isaac operation timed out")

    def exchange(
        self, operation: str, arguments: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                raise ValueError("session unavailable")
            self.sequence += 1
            data = (
                json.dumps(
                    {
                        "operation": operation,
                        "sequence": self.sequence,
                        "generation": self.session,
                        "arguments": arguments,
                    },
                    allow_nan=False,
                    separators=(",", ":"),
                ).encode()
                + b"\n"
            )
            if len(data) > MAX_FRAME:
                raise ValueError("request too large")
            try:
                offset = 0
                write_deadline = time.monotonic() + 5
                while offset < len(data):
                    if self.cancelled.is_set() or time.monotonic() > write_deadline:
                        raise TimeoutError("worker write timed out")
                    if select.select([], [self.request_fd], [], 0.2)[1]:
                        try:
                            offset += os.write(self.request_fd, data[offset:])
                        except BlockingIOError:
                            continue
                response = self._read(timeout)
                if (
                    response.get("generation") != self.session
                    or response.get("sequence") != self.sequence
                ):
                    raise ValueError("stale worker reply")
                return response
            except (OSError, ValueError, TimeoutError):
                self._terminate()
                raise

    def stop(self, session_id: str, *, dry_run: bool) -> dict[str, Any]:
        with self.lock:
            if session_id != self.session or self.process is None:
                raise ValueError("session unavailable")
            if dry_run:
                snapshot = self.exchange("status", {}, timeout=5)["result"]
                fingerprint = hashlib.sha256(
                    json.dumps(
                        {"session_id": session_id, "snapshot": snapshot},
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                return {
                    "ok": True,
                    "dry_run": True,
                    "fingerprint": fingerprint,
                    "session_id": session_id,
                    "preview": [
                        {
                            "label": "Isaac session",
                            "before": session_id,
                            "after": "Stop this owned session and discard its temporary scene",
                        }
                    ],
                }
            self._terminate()
            return {"ok": True, "state": "stopped", "session_id": session_id}

    def _terminate(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        for fd in (self.request_fd, self.reply_fd):
            if fd >= 0:
                os.close(fd)
        self.request_fd = self.reply_fd = -1
        self.process = None
        self.session = None
        if self.private is not None:
            self.private.cleanup()
            self.private = None

    def close(self) -> None:
        self.cancelled.set()
        with self.lock:
            self.closed = True
            self._terminate()
