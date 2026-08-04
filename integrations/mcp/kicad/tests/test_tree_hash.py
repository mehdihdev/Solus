"""The pure-Python git tree hasher must agree with git itself.

`tree_hash.git_tree_hash` exists so the ADR-031 vendored-tree guard runs in an
environment with no `git` binary (the CI python image has none). Its whole value
depends on producing the SAME id `git rev-parse HEAD:<path>` prints, so these
tests build real git repositories and compare, covering the cases where a naive
reimplementation diverges: executable bits, symlinks, nested trees, empty
directories, and git's directory-sorts-as-`name/` ordering rule.

Where git is unavailable the cross-checks skip (they cannot run) but the
structural tests — litter immunity and determinism — still execute, and the
production guards in the sibling test modules keep enforcing the hash.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tree_hash import IGNORED_NAMES, git_tree_hash  # isort: skip

GIT = shutil.which("git")
requires_git = pytest.mark.skipif(GIT is None, reason="no git binary to cross-check against")


def _git(repo: Path, *args: str) -> str:
    assert GIT is not None
    return subprocess.run(
        [GIT, *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_SYSTEM": "/dev/null",
            "PATH": "/usr/bin:/bin",
        },
    ).stdout.strip()


def _committed_tree_hash(repo: Path, subdir: str) -> str:
    """What `git` says the subtree's hash is, from a real commit."""
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=T", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=T", "commit", "-qm", "fixture")
    return _git(repo, "rev-parse", f"HEAD:{subdir}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tree").mkdir()
    return tmp_path


# --- cross-checks against real git --------------------------------------------


@requires_git
def test_matches_git_for_a_flat_tree(repo: Path) -> None:
    root = repo / "tree"
    (root / "a.txt").write_bytes(b"alpha\n")
    (root / "b.txt").write_bytes(b"")  # empty blob is a real case
    assert git_tree_hash(root) == _committed_tree_hash(repo, "tree")


@requires_git
def test_matches_git_for_executable_bits(repo: Path) -> None:
    root = repo / "tree"
    script = root / "launch"
    script.write_bytes(b"#!/bin/sh\nexec true\n")
    script.chmod(0o755)
    (root / "plain.txt").write_bytes(b"x\n")
    assert git_tree_hash(root) == _committed_tree_hash(repo, "tree")


@requires_git
def test_matches_git_for_symlinks(repo: Path) -> None:
    root = repo / "tree"
    (root / "real.txt").write_bytes(b"real\n")
    (root / "link.txt").symlink_to("real.txt")
    assert git_tree_hash(root) == _committed_tree_hash(repo, "tree")


@requires_git
def test_matches_git_for_nested_trees(repo: Path) -> None:
    root = repo / "tree"
    (root / "pkg").mkdir()
    (root / "pkg" / "__init__.py").write_bytes(b"")
    (root / "pkg" / "deep").mkdir()
    (root / "pkg" / "deep" / "mod.py").write_bytes(b"x = 1\n")
    (root / "top.py").write_bytes(b"import pkg\n")
    assert git_tree_hash(root) == _committed_tree_hash(repo, "tree")


@requires_git
def test_matches_git_for_the_directory_sort_rule(repo: Path) -> None:
    """git compares a directory as if its name ended in `/`, so `foo.txt` sorts
    BEFORE `foo/` — the opposite of a raw byte compare (`.` = 0x2E < `/` = 0x2F
    puts `foo.txt` first only once the slash is appended to the dir)."""
    root = repo / "tree"
    (root / "foo").mkdir()
    (root / "foo" / "inner.txt").write_bytes(b"i\n")
    (root / "foo.txt").write_bytes(b"f\n")
    (root / "foo-bar.txt").write_bytes(b"b\n")
    assert git_tree_hash(root) == _committed_tree_hash(repo, "tree")


@requires_git
def test_matches_git_when_an_empty_directory_is_present(repo: Path) -> None:
    """git cannot represent an empty directory; the hasher must skip it rather
    than invent an entry."""
    root = repo / "tree"
    (root / "kept.txt").write_bytes(b"k\n")
    (root / "empty").mkdir()
    assert git_tree_hash(root) == _committed_tree_hash(repo, "tree")


@requires_git
def test_matches_git_on_the_real_vendored_upstream_tree() -> None:
    """The load-bearing case: the actual committed fork tree this guard pins."""
    repo_root = Path(__file__).resolve().parents[4]
    upstream = repo_root / "integrations" / "mcp" / "kicad" / "upstream"
    from_git = subprocess.run(
        [str(GIT), "rev-parse", "HEAD:integrations/mcp/kicad/upstream"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert git_tree_hash(upstream) == from_git


# --- structural behavior (runs with or without git) ----------------------------


def test_ignores_tool_litter(repo: Path) -> None:
    """A gitignored cache directory must not perturb the hash — the exact bug
    that broke this guard once before."""
    root = repo / "tree"
    (root / "a.txt").write_bytes(b"alpha\n")
    before = git_tree_hash(root)

    litter = root / ".ruff_cache" / "0.15.0"
    litter.mkdir(parents=True)
    (litter / "cachefile").write_bytes(b"junk")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\x00")
    (root / "mod.pyc").write_bytes(b"\x00")

    assert git_tree_hash(root) == before


def test_every_ignored_name_is_skipped(repo: Path) -> None:
    root = repo / "tree"
    (root / "a.txt").write_bytes(b"alpha\n")
    before = git_tree_hash(root)
    for name in IGNORED_NAMES:
        litter = root / name
        litter.mkdir()
        (litter / "x").write_bytes(b"junk")
    assert git_tree_hash(root) == before


def test_is_deterministic_and_content_sensitive(repo: Path) -> None:
    root = repo / "tree"
    (root / "a.txt").write_bytes(b"alpha\n")
    first = git_tree_hash(root)
    assert first == git_tree_hash(root)
    assert len(first) == 40 and int(first, 16) >= 0

    (root / "a.txt").write_bytes(b"beta\n")
    assert git_tree_hash(root) != first


def test_refuses_a_missing_or_empty_tree(repo: Path) -> None:
    with pytest.raises(FileNotFoundError):
        git_tree_hash(repo / "nope")
    (repo / "hollow").mkdir()
    with pytest.raises(ValueError):
        git_tree_hash(repo / "hollow")


def test_mode_detection_ignores_os_access_root_quirk(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: running as root (every CI container) `os.access(p, X_OK)`
    reports success for files with NO execute bits, which hashed every vendored
    file as 100755 and broke this guard in CI only. Mode must come from the
    owner-execute BIT, so a patched always-true os.access changes nothing."""
    root = repo / "tree"
    (root / "plain.txt").write_bytes(b"p\n")
    (root / "plain.txt").chmod(0o644)
    expected = git_tree_hash(root)

    monkeypatch.setattr("os.access", lambda *_args, **_kwargs: True)
    assert git_tree_hash(root) == expected


def test_mode_detection_honors_a_real_owner_execute_bit(repo: Path) -> None:
    root = repo / "tree"
    script = root / "run.sh"
    script.write_bytes(b"#!/bin/sh\n")
    script.chmod(0o644)
    non_exec = git_tree_hash(root)
    script.chmod(0o755)
    assert git_tree_hash(root) != non_exec
