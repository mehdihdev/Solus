"""SOLUSDEV-249 — `.git` reading: dir form, worktree `gitdir:` file form,
missing, unreadable, oversize config, no origin; HEAD → branch + sha via a
loose ref or packed-refs (reported as the 12-hex SHORT sha); detached HEAD.
Never raises."""

import os
import stat
from pathlib import Path

import pytest

from .local_paths import overlay_module  # isort: skip

gitremote = overlay_module("gitremote")

SHA = "a" * 40
OTHER_SHA = "b" * 40
CONFIG = (
    "[core]\n\trepositoryformatversion = 0\n"
    '[remote "origin"]\n\turl = git@github.com:org/rover-fw.git\n'
    "\tfetch = +refs/heads/*:refs/remotes/origin/*\n"
    '[branch "main"]\n\tremote = origin\n'
)


def _git_dir(root: Path, *, branch: str = "main", packed: bool = False) -> Path:
    git = root / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "config").write_text(CONFIG)
    (git / "HEAD").write_text(f"ref: refs/heads/{branch}\n")
    if packed:
        (git / "packed-refs").write_text(
            f"# pack-refs with: peeled fully-peeled sorted\n{SHA} refs/heads/{branch}\n"
            f"^{OTHER_SHA}\n{OTHER_SHA} refs/tags/v1\n"
        )
    else:
        ref = git / "refs" / "heads" / branch
        ref.parent.mkdir(parents=True, exist_ok=True)
        ref.write_text(f"{SHA}\n")
    return git


def test_dir_form_reads_remote_branch_and_head(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    assert gitremote.git_info(tmp_path) == {
        "remote_url": "git@github.com:org/rover-fw.git",
        "branch": "main",
        "head": SHA[:12],
    }


def test_head_resolves_through_packed_refs(tmp_path: Path) -> None:
    _git_dir(tmp_path, packed=True)
    info = gitremote.git_info(tmp_path)
    assert info is not None and info["head"] == SHA[:12]


def test_loose_ref_wins_over_packed_refs(tmp_path: Path) -> None:
    git = _git_dir(tmp_path, packed=True)
    (git / "refs" / "heads" / "main").write_text(f"{OTHER_SHA}\n")
    info = gitremote.git_info(tmp_path)
    assert info is not None and info["head"] == OTHER_SHA[:12]


def test_branch_with_slashes(tmp_path: Path) -> None:
    git = _git_dir(tmp_path, branch="feature/x")
    assert (git / "refs" / "heads" / "feature" / "x").is_file()
    info = gitremote.git_info(tmp_path)
    assert info is not None and info["branch"] == "feature/x" and info["head"] == SHA[:12]


def test_detached_head_has_no_branch(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text(f"{OTHER_SHA}\n")
    info = gitremote.git_info(tmp_path)
    assert info == {
        "remote_url": "git@github.com:org/rover-fw.git",
        "branch": None,
        "head": OTHER_SHA[:12],
    }


def test_unresolvable_ref_gives_null_head(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "refs" / "heads" / "main").unlink()
    info = gitremote.git_info(tmp_path)
    assert info is not None and info["branch"] == "main" and info["head"] is None


def test_worktree_gitdir_file_form(tmp_path: Path) -> None:
    """`.git` is a FILE `gitdir: <path>` pointing at `<main>/.git/worktrees/<n>`;
    config + refs live in the common dir, HEAD in the worktree dir."""
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    common = _git_dir(main_repo, packed=True)
    wt_git = common / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/main\n")
    (wt_git / "commondir").write_text("../..\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {wt_git}\n")

    assert gitremote.git_info(worktree, home=tmp_path) == {
        "remote_url": "git@github.com:org/rover-fw.git",
        "branch": "main",
        "head": SHA[:12],
    }


def test_worktree_gitdir_relative_path(tmp_path: Path) -> None:
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    common = _git_dir(main_repo)
    wt_git = common / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/main\n")
    (wt_git / "commondir").write_text("../..\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../main/.git/worktrees/wt\n")
    info = gitremote.git_info(worktree, home=tmp_path)
    assert info is not None and info["head"] == SHA[:12]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://user:token@github.com/o/r.git", "https://github.com/o/r.git"),
        ("https://ghp_abc@github.com/o/r.git", "https://github.com/o/r.git"),
        ("ssh://git@github.com/o/r.git", "ssh://github.com/o/r.git"),
        ("oauth2:glpat-x@gitlab.com:o/r.git", "gitlab.com:o/r.git"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
        ("https://github.com/o/r.git", "https://github.com/o/r.git"),
        ("https://github.com/o/r@v2.git", "https://github.com/o/r@v2.git"),
    ],
)
def test_origin_url_never_carries_userinfo_credentials(
    tmp_path: Path, raw: str, expected: str
) -> None:
    git = _git_dir(tmp_path)
    (git / "config").write_text(f'[remote "origin"]\n\turl = {raw}\n')
    info = gitremote.git_info(tmp_path)
    assert info is not None and info["remote_url"] == expected
    assert "token" not in info["remote_url"] and "glpat" not in info["remote_url"]


def test_strip_userinfo_is_pure() -> None:
    assert gitremote.strip_userinfo("https://a:b@h/p") == "https://h/p"
    assert gitremote.strip_userinfo("a:b@h:p") == "h:p"
    assert gitremote.strip_userinfo("a@h:p") == "a@h:p"


def test_worktree_pointer_outside_home_is_none(tmp_path: Path) -> None:
    """A `gitdir:` pointer may only lead under HOME (real worktrees live
    there); anywhere else — even a valid-looking git dir — is refused."""
    main_repo = tmp_path / "main"
    main_repo.mkdir()
    common = _git_dir(main_repo)
    wt_git = common / "worktrees" / "wt"
    wt_git.mkdir(parents=True)
    (wt_git / "HEAD").write_text("ref: refs/heads/main\n")
    (wt_git / "commondir").write_text("../..\n")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {wt_git}\n")
    assert gitremote.git_info(worktree, home=tmp_path / "elsewhere") is None
    assert gitremote.git_info(worktree, home=tmp_path) is not None


def test_gitdir_pointer_to_etc_is_none(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /etc\n")
    assert gitremote.git_info(tmp_path, home=tmp_path) is None
    assert gitremote.git_info(tmp_path) is None


def test_commondir_redirect_outside_root_and_home_is_none(tmp_path: Path) -> None:
    """The directory form can still be redirected through a `commondir`
    file; that target is held to the same rule."""
    outside = tmp_path / "outside"
    outside.mkdir()
    _git_dir(outside)
    root = tmp_path / "root"
    root.mkdir()
    git = root / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "commondir").write_text(str(outside / ".git") + "\n")
    assert gitremote.git_info(root, home=tmp_path / "nowhere") is None
    assert gitremote.git_info(root, home=tmp_path) is not None


def test_missing_git_is_none(tmp_path: Path) -> None:
    assert gitremote.git_info(tmp_path) is None


def test_gitdir_file_pointing_nowhere_is_none(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /nonexistent/definitely/not\n")
    assert gitremote.git_info(tmp_path) is None


def test_garbage_git_file_is_none(tmp_path: Path) -> None:
    (tmp_path / ".git").write_bytes(b"\x00\xff not a pointer")
    assert gitremote.git_info(tmp_path) is None


def test_no_origin_is_none(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "config").write_text('[remote "upstream"]\n\turl = x\n')
    assert gitremote.git_info(tmp_path) is None


def test_missing_config_is_none(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "config").unlink()
    assert gitremote.git_info(tmp_path) is None


def test_oversize_config_is_none(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "config").write_text(CONFIG + "# " + "x" * gitremote.MAX_CONFIG_BYTES + "\n")
    assert gitremote.git_info(tmp_path) is None


def test_malformed_config_is_none(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "config").write_text('[remote "origin"\nurl = = = \n%%%\n[[[')
    assert gitremote.git_info(tmp_path) is None


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file modes")
def test_unreadable_config_is_none(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "config").chmod(0)
    try:
        assert gitremote.git_info(tmp_path) is None
    finally:
        (git / "config").chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_head_is_the_12_char_short_form(tmp_path: Path) -> None:
    _git_dir(tmp_path)
    info = gitremote.git_info(tmp_path)
    assert info is not None and info["head"] == "a" * 12
    assert len(info["head"]) == gitremote.SHORT_SHA_LEN < 40


def test_head_that_is_not_a_sha_is_null(tmp_path: Path) -> None:
    git = _git_dir(tmp_path)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs" / "heads" / "main").write_text("not-a-sha\n")
    info = gitremote.git_info(tmp_path)
    assert info is not None and info["head"] is None


def test_never_raises_even_when_reads_explode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _git_dir(tmp_path)

    def boom(*_args: object, **_kwargs: object) -> bytes:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(gitremote, "_read_bounded", boom)
    assert gitremote.git_info(tmp_path) is None
