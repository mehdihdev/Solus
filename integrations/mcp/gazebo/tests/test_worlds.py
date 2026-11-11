"""World roots, the bounded world-file scan and the fd-relative confinement."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from integrations.mcp.gazebo.solus.worlds import (
    WorldFile,
    confined_open,
    confined_write,
    list_world_files,
    model_dir,
    read_confined,
    sim_roots,
)


def test_sim_roots_reads_absolute_existing_dirs_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    a.mkdir()
    monkeypatch.setenv("SOLUS_SIM_ROOTS", f"{a}:rel/dir:{tmp_path / 'gone'}:{a}:")
    assert sim_roots() == (a,)
    monkeypatch.delenv("SOLUS_SIM_ROOTS")
    assert sim_roots() == ()


def test_list_world_files_finds_sdf_and_world_with_hints(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "shapes.sdf").write_text('<sdf version="1.11"/>')
    (tmp_path / "empty.world").write_text('<sdf version="1.5"><world name="default"/></sdf>')
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "h.sdf").write_text("<sdf/>")
    os.symlink(tmp_path / "empty.world", tmp_path / "link.sdf")
    found = list_world_files((tmp_path,))
    assert found == [
        WorldFile(path="empty.world", root=tmp_path, family_hint=None),
        WorldFile(path="nested/shapes.sdf", root=tmp_path, family_hint="gz"),
    ]


def test_list_world_files_is_bounded(tmp_path: Path) -> None:
    for i in range(600):
        (tmp_path / f"w{i:04}.sdf").write_text("<sdf/>")
    assert len(list_world_files((tmp_path,))) == 500


def test_confined_open_reads_a_regular_file_under_root(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "w.sdf").write_bytes(b"<sdf/>")
    fd = confined_open(tmp_path, "d/w.sdf")
    try:
        assert os.read(fd, 100) == b"<sdf/>"
    finally:
        os.close(fd)
    assert read_confined(tmp_path, "d/w.sdf", 1024) == b"<sdf/>"
    with pytest.raises(ValueError):
        read_confined(tmp_path, "d/w.sdf", 3)


@pytest.mark.parametrize(
    "rel",
    ["../escape.sdf", "/etc/passwd", "a/../../b.sdf", "d/./w.sdf", "", "bad name.sdf", "-flag.sdf"],
)
def test_paths_refuse_traversal_symlink_and_outside_roots(tmp_path: Path, rel: str) -> None:
    (tmp_path / "d").mkdir()
    (tmp_path / "d" / "w.sdf").write_bytes(b"<sdf/>")
    with pytest.raises(ValueError):
        confined_open(tmp_path, rel)


def test_confined_open_refuses_symlinked_leaf_dir_and_fifo(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.sdf").write_text("x")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside / "secret.sdf", root / "leaf.sdf")
    os.symlink(outside, root / "dir")
    os.mkfifo(root / "pipe.sdf")
    (root / "sub").mkdir()
    for rel in ("leaf.sdf", "dir/secret.sdf", "pipe.sdf", "sub"):
        with pytest.raises(ValueError):
            confined_open(root, rel)
    with pytest.raises(ValueError):
        confined_open(root / "missing-root", "leaf.sdf")


def test_model_dir_is_under_the_workspace_and_needs_a_sha256(tmp_path: Path) -> None:
    digest = "a" * 64
    assert model_dir(tmp_path, digest) == tmp_path / ".solus" / "sim" / "models" / digest
    for bad in ("A" * 64, "a" * 63, "../x", "a" * 64 + "/.."):
        with pytest.raises(ValueError):
            model_dir(tmp_path, bad)


def test_confined_write_creates_and_replaces_regular_files_only(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    confined_write(tmp_path, "d/new.sdf", b"<sdf/>")
    assert (tmp_path / "d" / "new.sdf").read_bytes() == b"<sdf/>"
    confined_write(tmp_path, "d/new.sdf", b"<sdf version='1.10'/>")
    assert (tmp_path / "d" / "new.sdf").read_bytes() == b"<sdf version='1.10'/>"
    assert sorted(p.name for p in (tmp_path / "d").iterdir()) == ["new.sdf"]  # no temp left
    big = b"x" * (3 * 1024 * 1024)
    confined_write(tmp_path, "big.sdf", big)
    assert (tmp_path / "big.sdf").read_bytes() == big


def test_confined_write_refuses_symlinked_parent_leaf_dir_and_escapes(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target.sdf").write_text("keep")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "dir")
    os.symlink(outside / "target.sdf", root / "leaf.sdf")
    (root / "sub").mkdir()
    for rel in ("dir/w.sdf", "leaf.sdf", "sub", "../w.sdf", "/abs.sdf", "-x.sdf", "a/../b", ""):
        with pytest.raises(ValueError):
            confined_write(root, rel, b"<sdf/>")
    assert (outside / "target.sdf").read_text() == "keep"
    assert sorted(p.name for p in outside.iterdir()) == ["target.sdf"]
    assert sorted(p.name for p in root.iterdir()) == ["dir", "leaf.sdf", "sub"]
    with pytest.raises(ValueError):
        confined_write(root / "missing", "w.sdf", b"<sdf/>")
