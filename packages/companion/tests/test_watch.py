"""Saved source and Git metadata changes wake the local freshness gate."""

import os
from pathlib import Path

import pytest
from solus_companion.watch import fingerprint


def test_saved_python_and_dependencies_trigger(tmp_path: Path) -> None:
    before = fingerprint(tmp_path)
    (tmp_path / "robot.py").write_text("pass")
    assert fingerprint(tmp_path) != before
    before = fingerprint(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]")
    assert fingerprint(tmp_path) != before


def test_git_branch_only_triggers(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main")
    before = fingerprint(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/feature")
    assert fingerprint(tmp_path) != before


def test_build_venv_and_symlink_targets_do_not_trigger(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "linked").symlink_to(outside, target_is_directory=True)
    before = fingerprint(root)
    for name in ("build", ".venv", "node_modules"):
        target = root / name
        target.mkdir()
        (target / "board.kicad_sch").write_text("generated")
    (outside / "private.kicad_sch").write_text("private")
    assert fingerprint(root) == before


def test_worktree_common_refs_trigger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    common = tmp_path / "repo" / ".git"
    metadata = common / "worktrees" / "wt"
    metadata.mkdir(parents=True)
    (metadata / "commondir").write_text("../..")
    (metadata / "HEAD").write_text("ref: refs/heads/main")
    refs = common / "refs" / "heads"
    refs.mkdir(parents=True)
    branch_ref = refs / "main"
    branch_ref.write_text("a" * 40)
    root = tmp_path / "wt"
    root.mkdir()
    (root / ".git").write_text(f"gitdir: {metadata}")
    before = fingerprint(root)
    previous = branch_ref.stat()
    branch_ref.write_text("b" * 40)
    # Same-size writes can share an mtime on CI filesystems; advance it explicitly.
    os.utime(branch_ref, ns=(previous.st_atime_ns, previous.st_mtime_ns + 2_000_000_000))
    assert fingerprint(root) != before


def test_irrelevant_entries_are_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import solus_companion.watch as watch

    monkeypatch.setattr(watch, "MAX_ENTRIES", 3)
    for index in range(20):
        (tmp_path / f"unrelated{index}.bin").write_bytes(b"")
    assert len(list(watch._bounded_files(tmp_path))) == 3
