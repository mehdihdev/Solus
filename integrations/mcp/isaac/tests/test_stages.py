"""Stage roots (`SOLUS_SIM_ROOTS`), the bounded stage-file scan and fd-relative confinement:
every stage path a tool argument names stays inside a root (the gazebo `worlds.py` shape)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[4]))
from integrations.mcp.isaac.solus.stages import (
    StageFile,
    list_stage_files,
    open_stage_file,
    resolve_stage,
    stage_roots,
    write_stage_file,
)


def test_stage_roots_reads_absolute_existing_dirs_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a = tmp_path / "a"
    a.mkdir()
    monkeypatch.setenv("SOLUS_SIM_ROOTS", f"{a}:rel/dir:{tmp_path / 'gone'}:{a}:")
    assert stage_roots() == (a,)
    monkeypatch.delenv("SOLUS_SIM_ROOTS")
    assert stage_roots() == ()


def test_list_stage_files_finds_usd_variants_and_skips_hidden_links_and_others(
    tmp_path: Path,
) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "arm.usdc").write_bytes(b"PXR-USDC")
    (tmp_path / "bench.usda").write_text("#usda 1.0\n")
    (tmp_path / "pack.usdz").write_bytes(b"PK")
    (tmp_path / "scene.usd").write_bytes(b"PXR-USDC")
    (tmp_path / "notes.txt").write_text("x")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "h.usda").write_text("#usda 1.0\n")
    os.symlink(tmp_path / "bench.usda", tmp_path / "link.usda")
    found = list_stage_files((tmp_path,))
    assert found == [
        StageFile(path="bench.usda", root=tmp_path),
        StageFile(path="nested/arm.usdc", root=tmp_path),
        StageFile(path="pack.usdz", root=tmp_path),
        StageFile(path="scene.usd", root=tmp_path),
    ]


def test_list_stage_files_is_bounded(tmp_path: Path) -> None:
    for i in range(600):
        (tmp_path / f"s{i:04}.usda").write_text("#usda 1.0\n")
    assert len(list_stage_files((tmp_path,))) == 500


@pytest.mark.parametrize(
    "rel",
    ["../secret.usda", "/etc/passwd", "d/../../x.usda", "-flag.usda", "d//w.usda", ".", "d/."],
)
def test_stage_paths_confined_to_stage_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rel: str
) -> None:
    root = tmp_path / "root"
    (root / "d").mkdir(parents=True)
    (root / "d" / "w.usda").write_text("#usda 1.0\n")
    (tmp_path / "secret.usda").write_text("#usda 1.0\n")
    monkeypatch.setenv("SOLUS_SIM_ROOTS", str(root))
    with pytest.raises(ValueError):
        open_stage_file(root, rel)
    with pytest.raises(ValueError):
        resolve_stage(rel)
    assert resolve_stage("d/w.usda") == (root, "d/w.usda")


def test_resolve_stage_refuses_non_stage_suffix_symlinks_and_outside_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.usda").write_text("#usda 1.0\n")
    (root / "notes.txt").write_text("x")
    os.symlink(outside / "secret.usda", root / "leaf.usda")
    os.symlink(outside, root / "dir")
    os.mkfifo(root / "pipe.usda")
    monkeypatch.setenv("SOLUS_SIM_ROOTS", str(root))
    for rel in ("notes.txt", "leaf.usda", "dir/secret.usda", "pipe.usda", "missing.usda"):
        with pytest.raises(ValueError):
            resolve_stage(rel)
    monkeypatch.delenv("SOLUS_SIM_ROOTS")
    with pytest.raises(ValueError, match="SOLUS_SIM_ROOTS"):
        resolve_stage("leaf.usda")


def test_write_stage_file_creates_and_replaces_regular_files_only(tmp_path: Path) -> None:
    (tmp_path / "d").mkdir()
    write_stage_file(tmp_path, "d/new.usda", b"#usda 1.0\n")
    assert (tmp_path / "d" / "new.usda").read_bytes() == b"#usda 1.0\n"
    write_stage_file(tmp_path, "d/new.usda", b"#usda 1.0\nover\n")
    assert (tmp_path / "d" / "new.usda").read_bytes() == b"#usda 1.0\nover\n"
    assert sorted(p.name for p in (tmp_path / "d").iterdir()) == ["new.usda"]
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside / "x.usda", tmp_path / "d" / "link.usda")
    os.symlink(outside, tmp_path / "d" / "dir")
    (tmp_path / "d" / "sub").mkdir()
    for rel in ("d/link.usda", "d/dir/x.usda", "d/sub", "../x.usda", "d/missing/x.usda"):
        with pytest.raises(ValueError):
            write_stage_file(tmp_path, rel, b"x")
    assert list(outside.iterdir()) == []
