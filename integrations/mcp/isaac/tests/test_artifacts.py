import json
import os
import sys
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.artifacts import RevisionStore


def test_revision_is_readable_immutable_and_confined(tmp_path):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        store = RevisionStore(fd, str(UUID(int=1)))
        result = store.publish(1, {"model": {"asset": "so101_new_calib_v1"}})
        assert (
            json.loads((tmp_path / result["relative_path"]).read_text())["model"]["asset"]
            == "so101_new_calib_v1"
        )
        with pytest.raises(FileExistsError):
            store.publish(1, {"different": True})
    finally:
        os.close(fd)


def test_symlink_artifact_directory_refused(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / ".solus").symlink_to(outside)
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError):
            RevisionStore(fd, str(UUID(int=1))).publish(1, {"ok": True})
        assert list(outside.iterdir()) == []
    finally:
        os.close(fd)


def test_bounded_revision_and_content(tmp_path):
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        store = RevisionStore(fd, str(UUID(int=1)))
        with pytest.raises(ValueError):
            store.publish(33, {})
        with pytest.raises(ValueError):
            store.publish(1, {"huge": "x" * 131072})
        assert list(tmp_path.iterdir()) == []
    finally:
        os.close(fd)


@pytest.mark.parametrize("target", [".solus", ".solus/isaac"])
def test_replaced_directory_never_returns_a_saved_external_path(tmp_path, monkeypatch, target):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    original = os.fsync
    replaced = False

    def replace(descriptor):
        nonlocal replaced
        original(descriptor)
        if not replaced:
            replaced = True
            directory = root / target
            directory.rename(root / "old")
            directory.symlink_to(outside, target_is_directory=True)

    monkeypatch.setattr(os, "fsync", replace)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with pytest.raises(OSError):
            RevisionStore(fd, str(UUID(int=1))).publish(1, {"verified": True})
        assert list(outside.iterdir()) == []
    finally:
        os.close(fd)
