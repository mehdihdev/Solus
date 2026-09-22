"""Exercise controller ownership/deadlines over real pipes and a controlled child."""

import io
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.controller import Controller


class Child:
    def __init__(self, created, mode, argv, **kwargs):
        from integrations.mcp.isaac.solus.worker import serve_frames

        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        assert set(kwargs["env"]) == {"HOME", "PATH", "LANG", "TMPDIR"}
        assert argv[1].endswith("/solus/worker.py")
        self.pid = 43210
        self.finished = threading.Event()
        self.stop_event = threading.Event()
        self.ignore_term = False
        self.stdout = io.BytesIO(b"x" * 16384 + b"bounded-tail")
        request = os.dup(int(argv[2]))
        reply = os.dup(int(argv[3]))
        generation = argv[4]

        class Engine:
            generation = 0

            def status(self):
                return {"loaded": False}

            def dispatch(self, *args):
                raise ValueError("refused")

        def run():
            with (
                os.fdopen(request, "rb", buffering=0) as reader,
                os.fdopen(reply, "wb", buffering=0) as writer,
            ):
                try:
                    if mode["value"] == "eof":
                        return
                    if mode["value"] == "hang":
                        self.stop_event.wait(3)
                        return
                    if mode["value"] == "bad_ready":
                        writer.write(b'{"ready":true,"generation":"foreign"}\n')
                        self.stop_event.wait(3)
                        return
                    serve_frames(reader, writer, generation, Engine())
                finally:
                    self.finished.set()

        self.thread = threading.Thread(target=run, daemon=True)
        created.append(self)
        self.thread.start()

    def poll(self):
        return 0 if self.finished.is_set() else None

    def wait(self, timeout):
        if self.ignore_term and not self.stop_event.is_set():
            raise subprocess.TimeoutExpired("owned worker", timeout)
        if not self.finished.wait(timeout):
            raise subprocess.TimeoutExpired("owned worker", timeout)
        return 0


@pytest.fixture
def children(monkeypatch):
    created = []
    mode = {"value": "normal"}
    signals = []

    def child_factory(argv, **kwargs):
        return Child(created, mode, argv, **kwargs)

    def kill(pid, sig):
        assert created and pid == created[-1].pid
        signals.append(sig)
        if sig == signal.SIGTERM and created[-1].ignore_term:
            return
        created[-1].stop_event.set()
        created[-1].finished.set()

    monkeypatch.setattr(subprocess, "Popen", child_factory)
    monkeypatch.setattr(os, "killpg", kill)
    yield created, mode, signals
    for child in created:
        child.stop_event.set()
        child.thread.join(timeout=1)


def test_start_exchange_and_stop_only_owned_child(tmp_path, children):
    created, mode, signals = children
    controller = Controller(tmp_path)
    result = controller.start(dry_run=False)
    assert result["state"] == "running"
    assert controller.exchange("status", {}, timeout=1)["result"] == {"loaded": False}
    preview = controller.stop(result["session_id"], dry_run=True)
    assert len(preview["fingerprint"]) == 64
    assert not signals
    controller.stop(result["session_id"], dry_run=False)
    assert signals == [signal.SIGTERM]
    assert controller.status()["state"] == "stopped" and controller.private is None
    assert len(controller.log_tail) <= 8192


@pytest.mark.parametrize("mode_name", ["bad_ready", "eof", "hang"])
def test_failed_startup_cleans_process_and_fds(tmp_path, children, monkeypatch, mode_name):
    created, mode, signals = children
    mode["value"] = mode_name
    original = Controller._read
    monkeypatch.setattr(Controller, "_read", lambda self, timeout: original(self, 0.1))
    controller = Controller(tmp_path)
    with pytest.raises((ValueError, TimeoutError)):
        controller.start(dry_run=False)
    assert controller.process is None and controller.private is None
    assert controller.request_fd == controller.reply_fd == -1


def test_disconnect_cancels_hung_startup(tmp_path, children):
    created, mode, signals = children
    mode["value"] = "hang"
    controller = Controller(tmp_path)
    errors = []

    def start():
        try:
            controller.start(dry_run=False)
        except ValueError as error:
            errors.append(str(error))

    thread = threading.Thread(target=start)
    thread.start()
    # Wait for the controlled child to exist; never wait for a native runtime.
    import time

    deadline = time.monotonic() + 2
    while not created and time.monotonic() < deadline:
        time.sleep(0.001)
    assert created
    controller.close()
    thread.join(timeout=2)
    assert not thread.is_alive() and errors
    assert controller.private is None and controller.closed


def test_unresponsive_owned_child_gets_bounded_kill(tmp_path, children):
    created, mode, signals = children
    controller = Controller(tmp_path)
    result = controller.start(dry_run=False)
    created[-1].ignore_term = True
    controller.stop(result["session_id"], dry_run=False)
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert controller.private is None
