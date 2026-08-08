"""ADR-031 vendored-tree integrity guard for the altium fork (SOLUSDEV-102 ALT-3).

`PROVENANCE.md` records the vendored tree hash of `upstream/`; any byte
change to the vendored tree changes the recompute and mechanically voids the
human sign-offs. The recompute uses the shared pure-Python hasher
(`integrations/mcp/tests/_lib/vendored_tree_hash.py`) so the guard runs on
the git-less CI image. The hasher implementation itself is cross-checked
against real git by the kicad fork's test_tree_hash.py suite; here it is
additionally cross-checked against THIS fork's committed tree wherever a git
binary exists.

Also sanity-checks the `altium_paths` bootstrap module the sibling tests
build on (H9: the bootstrap is Solus-authored support code and gets tested
where it is consumed).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

# The bootstrap module inserts integrations/mcp/tests/_lib on sys.path —
# keep this import first.
from .altium_paths import (  # isort: skip
    FORK_DIR,
    LAUNCH,
    MCP_ROOT,
    PROVENANCE,
    REPO_ROOT,
    UPSTREAM_DIR,
    find_repo_root,
)
from vendored_tree_hash import git_tree_hash  # isort: skip

GIT = shutil.which("git")


def _recorded_tree_hash() -> str:
    text = PROVENANCE.read_text(encoding="utf-8")
    match = re.search(r"Vendored tree hash:\*\*\s*`([0-9a-f]{40})`", text)
    assert match, "PROVENANCE.md must record the vendored tree hash as a 40-hex `code` span"
    return match.group(1)


# --- the PROVENANCE guard -------------------------------------------------------


def test_provenance_tree_hash_matches_a_recompute_of_upstream() -> None:
    assert _recorded_tree_hash() == git_tree_hash(UPSTREAM_DIR), (
        "PROVENANCE tree hash is stale — upstream/ changed without updating it "
        "(this mechanically voids the sign-offs)"
    )


@pytest.mark.skipif(GIT is None, reason="no git binary to cross-check against")
def test_recompute_matches_git_rev_parse_on_the_committed_tree() -> None:
    assert GIT is not None
    from_git = subprocess.run(
        [GIT, "rev-parse", "HEAD:integrations/mcp/altium/upstream"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert git_tree_hash(UPSTREAM_DIR) == from_git


# --- the altium_paths bootstrap itself -------------------------------------------


def test_repo_root_discovery_finds_the_workspace_root() -> None:
    assert (REPO_ROOT / ".git").exists() or (REPO_ROOT / "pyproject.toml").is_file()
    assert find_repo_root() == REPO_ROOT
    assert MCP_ROOT.is_dir()
    assert FORK_DIR.is_dir()
    assert UPSTREAM_DIR.is_dir()


def test_repo_root_discovery_refuses_an_unrooted_tree(tmp_path: Path) -> None:
    orphan = tmp_path / "orphan" / "deep"
    orphan.mkdir(parents=True)
    probe = orphan / "probe.py"
    probe.write_text("", encoding="utf-8")
    if any((parent / ".git").exists() for parent in (orphan, *orphan.parents)):
        pytest.skip("tmp_path lives under a git checkout; the walk-up would legitimately find it")
    with pytest.raises(FileNotFoundError):
        find_repo_root(probe)


def test_launch_paths_point_inside_the_fork() -> None:
    assert LAUNCH == FORK_DIR / "bin" / "launch"
    assert LAUNCH.resolve().is_relative_to(MCP_ROOT.resolve())
