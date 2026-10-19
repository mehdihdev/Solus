"""SOLUSDEV-317 — FIFO-safe reads of workspace files: a named pipe planted where the
probe, the git-metadata digest or the profile store expects a file never blocks the
server (O_NONBLOCK + regular-file check)."""

import os
import threading
from pathlib import Path
from typing import Any

import pytest

from code_paths import overlay_module  # isort: skip
from venv_fixture import fake_venv  # isort: skip

safe_read = overlay_module("safe_read")
probe = overlay_module("probe")
git_guard = overlay_module("git_guard")
profiles = overlay_module("profiles")


def _bounded(call: Any, seconds: float = 5.0) -> Any:
    """Run `call` in a daemon thread; fail (instead of hanging) when it blocks."""
    box: list[Any] = []
    worker = threading.Thread(target=lambda: box.append(call()), daemon=True)
    worker.start()
    worker.join(seconds)
    assert not worker.is_alive(), "blocked on a FIFO"
    return box[0]


def test_read_regular_skips_fifos_symlinks_and_bounds_bytes(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / "pipe")
    (tmp_path / "file").write_bytes(b"abcdef")
    (tmp_path / "link").symlink_to(tmp_path / "file")
    assert _bounded(lambda: safe_read.read_regular(tmp_path / "pipe", 10)) is None
    assert _bounded(lambda: safe_read.read_regular(tmp_path / "pipe", 10, follow=True)) is None
    assert safe_read.read_regular(tmp_path / "file", 3) == b"abc"
    assert safe_read.read_regular(tmp_path / "link", 10) is None
    assert safe_read.read_regular(tmp_path / "link", 10, follow=True) == b"abcdef"
    assert safe_read.read_regular(tmp_path / "missing", 10) is None


def test_probe_never_blocks_on_fifo_metadata_or_pyvenv_cfg(tmp_path: Path) -> None:
    fake_venv(tmp_path, ".venv")
    site = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
    (site / "pipe-1.dist-info").mkdir(parents=True)
    os.mkfifo(site / "pipe-1.dist-info" / "METADATA")
    (tmp_path / ".venv" / "pyvenv.cfg").unlink()
    os.mkfifo(tmp_path / ".venv" / "pyvenv.cfg")
    # pyvenv.cfg as a FIFO is not a venv marker; METADATA as a FIFO is skipped.
    result = _bounded(
        lambda: probe.probe_environment(tmp_path, which=lambda _n: None, capture=lambda *_: None)
    )
    assert result["venv"] is None
    (tmp_path / ".venv" / "pyvenv.cfg").unlink()
    (tmp_path / ".venv" / "pyvenv.cfg").write_text("version = 3.12.1\n")
    venv = _bounded(
        lambda: probe.probe_environment(tmp_path, which=lambda _n: None, capture=lambda *_: None)
    )["venv"]
    assert venv["packages"] == [] and venv["truncated"] is True


@pytest.mark.parametrize("where", ["hooks/pre-commit", "config", "commondir", "info/exclude"])
def test_git_digest_and_dirs_never_block_on_a_fifo(tmp_path: Path, where: str) -> None:
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".git" / "info").mkdir()
    os.mkfifo(tmp_path / ".git" / where)
    first = _bounded(lambda: git_guard.git_metadata_digest(tmp_path))
    assert first == _bounded(lambda: git_guard.git_metadata_digest(tmp_path))
    assert _bounded(lambda: git_guard.protected_git_dirs(tmp_path))


def test_gitfile_pointing_at_a_fifo_commondir_never_blocks(tmp_path: Path) -> None:
    target = tmp_path / "real-git"
    target.mkdir()
    os.mkfifo(target / "commondir")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / ".git").write_text(f"gitdir: {target}\n")
    git_dir, common = _bounded(lambda: git_guard.protected_git_dirs(ws))
    assert git_dir == common == os.path.realpath(target)


def test_profile_store_fifo_is_unreadable_not_blocking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    ws = tmp_path / "ws"
    ws.mkdir()
    store = profiles.store_dir(ws)
    store.mkdir(parents=True)
    os.mkfifo(store / "ros.json")
    assert "unreadable" in _bounded(lambda: profiles.load(ws, "ros"))
