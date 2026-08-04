"""SOLUSDEV-100 T2b — `solus/write/atomic_write.py`: temp-file-in-same-dir +
fsync + os.replace, and no litter left behind on failure."""

import os
import tempfile
from pathlib import Path

import pytest

# The support module's import bootstrap (sys.path + lockfile-dep stubs) must
# run BEFORE any `solus` import — keep this line before the solus.* imports.
from test_overlay_support import SOLUS  # noqa: F401  # isort: skip

from solus.write.atomic_write import atomic_write  # isort: skip


def _entries(directory: Path) -> set[str]:
    return {entry.name for entry in directory.iterdir()}


def test_writes_the_destination_with_the_given_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "board.kicad_sch"
    destination.write_bytes(b"old contents")
    atomic_write(destination, b"new contents")
    assert destination.read_bytes() == b"new contents"


def test_leaves_no_temp_file_behind_on_success(tmp_path: Path) -> None:
    destination = tmp_path / "board.kicad_sch"
    destination.write_bytes(b"old")
    atomic_write(destination, b"new")
    assert _entries(tmp_path) == {"board.kicad_sch"}


def test_creates_the_file_if_it_did_not_exist(tmp_path: Path) -> None:
    destination = tmp_path / "new.kicad_sch"
    atomic_write(destination, b"created")
    assert destination.read_bytes() == b"created"


def test_temp_file_is_created_in_the_same_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`os.replace` is only atomic within one filesystem; assert the temp
    file's parent is the destination's parent by watching mkstemp's `dir`."""
    destination = tmp_path / "board.kicad_sch"
    destination.write_bytes(b"old")
    seen_dirs: list[Path] = []
    original_mkstemp = tempfile.mkstemp

    def _spy_mkstemp(*, dir: Path, prefix: str, suffix: str) -> tuple[int, str]:
        seen_dirs.append(Path(dir))
        return original_mkstemp(dir=dir, prefix=prefix, suffix=suffix)

    monkeypatch.setattr("solus.write.atomic_write.tempfile.mkstemp", _spy_mkstemp)
    atomic_write(destination, b"new")
    assert seen_dirs == [tmp_path]


def test_cleans_up_the_temp_file_when_the_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "board.kicad_sch"
    destination.write_bytes(b"old contents")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr("solus.write.atomic_write.os.fsync", _boom)
    with pytest.raises(OSError, match="simulated fsync failure"):
        atomic_write(destination, b"new contents")

    assert destination.read_bytes() == b"old contents", "destination must be untouched on failure"
    assert _entries(tmp_path) == {"board.kicad_sch"}, "no temp file may survive a failed write"


def test_cleans_up_the_temp_file_when_the_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "board.kicad_sch"
    destination.write_bytes(b"old contents")

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("solus.write.atomic_write.os.replace", _boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        atomic_write(destination, b"new contents")

    assert destination.read_bytes() == b"old contents"
    assert _entries(tmp_path) == {"board.kicad_sch"}


def test_destination_is_untouched_until_the_final_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    destination = tmp_path / "board.kicad_sch"
    destination.write_bytes(b"old contents")
    original_replace = os.replace
    snapshot_before_replace: bytes = b""

    def _spy_replace(src: Path, dst: Path) -> None:
        nonlocal snapshot_before_replace
        snapshot_before_replace = destination.read_bytes()
        original_replace(src, dst)

    monkeypatch.setattr("solus.write.atomic_write.os.replace", _spy_replace)
    atomic_write(destination, b"new contents")
    assert snapshot_before_replace == b"old contents"
