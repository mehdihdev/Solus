import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.controller import Controller


def test_probe_and_start_preview_do_not_launch(tmp_path):
    controller = Controller(tmp_path)
    probe = controller.probe()
    assert isinstance(probe["available"], bool)
    preview = controller.start(dry_run=True)
    assert preview["dry_run"] is True
    assert controller.status()["state"] == "stopped"
    assert list(tmp_path.iterdir()) == []


def test_stale_session_cannot_stop(tmp_path):
    controller = Controller(tmp_path)
    with pytest.raises(ValueError, match="session"):
        controller.stop("00000000-0000-0000-0000-000000000001", dry_run=False)


def test_closed_controller_refuses_start(tmp_path):
    controller = Controller(tmp_path)
    controller.close()
    with pytest.raises(ValueError):
        controller.start(dry_run=False)


def test_spawn_failure_releases_owned_resources(tmp_path, monkeypatch):
    import subprocess

    def failed_spawn(*args, **kwargs):
        raise OSError("launch denied")

    monkeypatch.setattr(subprocess, "Popen", failed_spawn)
    controller = Controller(tmp_path)
    with pytest.raises(OSError):
        controller.start(dry_run=False)
    assert controller.private is None
    assert controller.session is None
    assert controller.request_fd == controller.reply_fd == -1
