"""Exercise controller ownership/deadlines over real pipes and a controlled child (the
`children` fixture in conftest.py)."""

import signal
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.controller import Controller
from integrations.mcp.isaac.tests.conftest import Children


def test_start_exchange_and_stop_only_owned_child(tmp_path: Path, children: Children) -> None:
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
def test_failed_startup_cleans_process_and_fds(
    tmp_path: Path, children: Children, monkeypatch: pytest.MonkeyPatch, mode_name: str
) -> None:
    created, mode, signals = children
    mode["value"] = mode_name
    original = Controller._read
    monkeypatch.setattr(Controller, "_read", lambda self, timeout: original(self, 0.1))
    controller = Controller(tmp_path)
    with pytest.raises((ValueError, TimeoutError)):
        controller.start(dry_run=False)
    assert controller.process is None and controller.private is None
    assert controller.request_fd == controller.reply_fd == -1


def test_disconnect_cancels_hung_startup(tmp_path: Path, children: Children) -> None:
    created, mode, signals = children
    mode["value"] = "hang"
    controller = Controller(tmp_path)
    errors: list[str] = []

    def start() -> None:
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


def test_unresponsive_owned_child_gets_bounded_kill(tmp_path: Path, children: Children) -> None:
    created, mode, signals = children
    controller = Controller(tmp_path)
    result = controller.start(dry_run=False)
    created[-1].ignore_term = True
    controller.stop(result["session_id"], dry_run=False)
    assert signals == [signal.SIGTERM, signal.SIGKILL]
    assert controller.private is None
