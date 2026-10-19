"""Confined Git observations and reviewed staged-only commits in disposable repositories."""

import subprocess
from pathlib import Path
from typing import cast

import pytest

from code_paths import overlay_module  # isort: skip
from sandbox_fixture import pinned_sandbox_probe, test_writable_roots  # noqa: F401  # isort: skip

git = overlay_module("git_operations")


def command(root: Path, *args: str) -> str:
    return subprocess.check_output(["/usr/bin/git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    command(tmp_path, "init", "-b", "main")
    command(tmp_path, "config", "user.name", "Fixture Author")
    command(tmp_path, "config", "user.email", "fixture@example.invalid")
    (tmp_path / "a.txt").write_text("initial\n")
    command(tmp_path, "add", "a.txt")
    command(tmp_path, "commit", "-m", "Initial")
    return tmp_path


def test_status_log_and_diff(repo: Path) -> None:
    (repo / "a.txt").write_text("second\n")
    command(repo, "add", "a.txt")
    (repo / "a.txt").write_text("unstaged\n")
    state = git.git_status(repo)
    assert state["branch"] == "main"
    assert state["staged"] == ["a.txt"] and state["unstaged"] == ["a.txt"]
    assert "+second" in git.git_diff(repo, "staged")["diff"]
    assert git.git_log(repo)["commits"][0]["subject"] == "Initial"


def test_commit_preview_changes_nothing_and_commit_preserves_unstaged(repo: Path) -> None:
    (repo / "a.txt").write_text("staged\n")
    command(repo, "add", "a.txt")
    (repo / "a.txt").write_text("unstaged\n")
    state = git.git_status(repo)
    before = {
        str(p.relative_to(repo)): p.read_bytes() for p in (repo / ".git").rglob("*") if p.is_file()
    }
    args = dict(
        message="Reviewed staged change",
        expected_head=state["head"],
        expected_index_fingerprint=state["index_fingerprint"],
    )
    plan = git.git_commit(repo, **args, dry_run=True)
    assert any("+staged" in (row["after"] or "") for row in plan["preview"])
    assert before == {
        str(p.relative_to(repo)): p.read_bytes() for p in (repo / ".git").rglob("*") if p.is_file()
    }
    result = git.git_commit(repo, **args)
    assert result["changed"] and not result["uncertain"]
    assert command(repo, "show", "HEAD:a.txt") == "staged"
    assert (repo / "a.txt").read_text() == "unstaged\n"
    with pytest.raises(git.GitOperationError, match="stale_state"):
        git.git_commit(repo, **args)


@pytest.mark.parametrize(
    "name,value",
    [
        ("core.hooksPath", "/tmp/unsafe"),
        ("core.fsmonitor", "unsafe"),
        ("filter.custom.clean", "unsafe"),
        ("credential.helper", "unsafe"),
        ("include.path", "/tmp/unsafe"),
    ],
)
def test_implicit_execution_config_refused(repo: Path, name: str, value: str) -> None:
    command(repo, "config", name, value)
    with pytest.raises(git.GitOperationError, match="unsafe_config"):
        git.git_status(repo)


def test_paths_and_unknown_fields_refused(repo: Path) -> None:
    for path in ["../a", ".git/config", "-a", "a/../b"]:
        with pytest.raises(git.GitOperationError):
            git.git_diff(repo, "staged", [path])
    with pytest.raises(ValueError):
        git.GitLogArgs.model_validate({"limit": 2, "command": "bad"})


def test_production_push_does_not_execute_credentials(repo: Path) -> None:
    command(repo, "remote", "add", "origin", "https://example.invalid/repo.git")
    with pytest.raises(git.GitOperationError, match="authentication_unavailable"):
        git.git_push(repo, "origin", "main", command(repo, "rev-parse", "HEAD"), None, True)


def test_commit_refuses_oversize_preview_and_stale_index(repo: Path) -> None:
    state = git.git_status(repo)
    (repo / "a.txt").write_text("x" * 17000)
    command(repo, "add", "a.txt")
    with pytest.raises(git.GitOperationError, match="stale_state"):
        git.git_commit(repo, "Change", state["head"], state["index_fingerprint"], True)
    state = git.git_status(repo)
    with pytest.raises(git.GitOperationError, match="preview_too_large"):
        git.git_commit(repo, "Change", state["head"], state["index_fingerprint"], True)


def test_existing_ref_lock_refuses_commit(repo: Path) -> None:
    (repo / "a.txt").write_text("changed\n")
    command(repo, "add", "a.txt")
    state = git.git_status(repo)
    (repo / ".git/refs/heads/main.lock").write_text("")
    with pytest.raises(git.GitOperationError, match="repository_busy"):
        git.git_commit(repo, "Change", state["head"], state["index_fingerprint"], True)


def test_submodule_index_refused_even_for_read(repo: Path) -> None:
    command(
        repo,
        "update-index",
        "--add",
        "--cacheinfo",
        "160000," + command(repo, "rev-parse", "HEAD") + ",nested",
    )
    with pytest.raises(git.GitOperationError, match="unsupported_repository"):
        git.git_status(repo)


def test_preview_binds_repository_identity(repo: Path, tmp_path: Path) -> None:
    (repo / "a.txt").write_text("changed\n")
    command(repo, "add", "a.txt")
    state = git.git_status(repo)
    first = git.git_commit(repo, "Change", state["head"], state["index_fingerprint"], True)
    import shutil

    # Same content at a replacement repository cannot preserve the approval fingerprint.
    backup = tmp_path.parent / (tmp_path.name + "-backup")
    repo.rename(backup)
    shutil.copytree(backup, repo)
    second = git.git_commit(repo, "Change", state["head"], state["index_fingerprint"], True)
    assert first["fingerprint"] != second["fingerprint"]


@pytest.mark.parametrize(
    "url",
    [
        "git@evil.invalid:a/b.git",
        "ssh://git@github.com:2222/a/b.git",
        "git@github.com:../secret",
        "ext::command",
        "file:///tmp/repo",
    ],
)
def test_push_host_and_transport_allowlist(repo: Path, url: str) -> None:
    command(repo, "remote", "add", "origin", url)
    with pytest.raises(git.GitOperationError, match="unsupported_transport"):
        git.git_push(repo, "origin", "main", command(repo, "rev-parse", "HEAD"), None, True)


def test_disposable_push_and_moved_remote_refusal(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = repo.parent / (repo.name + "-remote.git")
    subprocess.check_call(
        ["/usr/bin/git", "init", "--bare", str(remote)], stdout=subprocess.DEVNULL
    )
    original_run = git.Repository.run

    def fixture_run(
        self: object, args: list[str], *, network: bool = False, **kwargs: object
    ) -> bytes:
        if network:
            assert args[0] in ("ls-remote", "push")
            # Only this fixture injects its own local transport; production rejects file URLs.
            return subprocess.check_output(
                ["/usr/bin/git", *args], cwd=repo, stderr=subprocess.DEVNULL
            )
        return cast(bytes, original_run(self, args, **kwargs))

    monkeypatch.setattr(git.Repository, "run", fixture_run)
    monkeypatch.setattr(git, "_remote", lambda *_: (str(remote), "fixture/repository"))
    head = command(repo, "rev-parse", "HEAD")
    preview = git.git_push(repo, "origin", "main", head, None, True)
    assert preview["dry_run"]
    result = git.git_push(repo, "origin", "main", head, None)
    assert result["remote_head"] == head and result["uncertain"] is False
    with pytest.raises(git.GitOperationError, match="stale_remote"):
        git.git_push(repo, "origin", "main", head, None, True)


def test_binary_change_preview_contains_complete_patch(repo: Path) -> None:
    (repo / "binary.bin").write_bytes(b"\x00fixture payload")
    command(repo, "add", "binary.bin")
    state = git.git_status(repo)
    preview = git.git_commit(repo, "Binary", state["head"], state["index_fingerprint"], True)
    patch = "".join(
        row["after"]
        for row in preview["preview"]
        if row["label"].startswith("Complete staged diff")
    )
    assert "GIT binary patch" in patch
    result = git.git_commit(repo, "Binary", state["head"], state["index_fingerprint"])
    assert result["uncertain"] is False


def test_commit_preserves_verbatim_multiline_message(repo: Path) -> None:
    (repo / "a.txt").write_text("changed\n")
    command(repo, "add", "a.txt")
    state = git.git_status(repo)
    message = "Title\n\nDetailed body  \n\n"
    result = git.git_commit(repo, message, state["head"], state["index_fingerprint"])
    assert result["uncertain"] is False
    raw = subprocess.check_output(["/usr/bin/git", "cat-file", "commit", "HEAD"], cwd=repo)
    assert raw.split(b"\n\n", 1)[1] == message.encode()


def test_split_index_refused(repo: Path) -> None:
    command(repo, "update-index", "--split-index")
    with pytest.raises(git.GitOperationError, match="unsupported_repository"):
        git.git_status(repo)


def test_repository_attributes_refused(repo: Path) -> None:
    (repo / ".git/info/attributes").write_text("* diff=custom\n")
    with pytest.raises(git.GitOperationError, match="unsupported_repository"):
        git.git_status(repo)


def test_ignored_dependency_symlinks_do_not_break_observations(repo: Path) -> None:
    (repo / ".gitignore").write_text(".venv/\nnode_modules/\n")
    (repo / ".venv").mkdir()
    (repo / ".venv/python").symlink_to("/usr/bin/python3")
    (repo / "node_modules").mkdir()
    (repo / "node_modules/pkg").symlink_to("/nonexistent-package")
    assert git.git_status(repo)["head"] == command(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize(
    "kind", ["tracked_symlink", "ancestor_symlink", "metadata_symlink", "ancestor_attributes"]
)
def test_narrow_inventory_retains_git_path_guards(repo: Path, kind: str) -> None:
    (repo / "folder").mkdir()
    (repo / "folder/tracked.txt").write_text("fixture")
    command(repo, "add", "folder/tracked.txt")
    if kind == "tracked_symlink":
        (repo / "link").symlink_to("/tmp/irrelevant")
        command(repo, "add", "link")
    elif kind == "ancestor_symlink":
        (repo / "folder").rename(repo / "old-folder")
        (repo / "folder").symlink_to(repo / "old-folder", target_is_directory=True)
    elif kind == "metadata_symlink":
        (repo / ".git/info/link").symlink_to("/tmp/irrelevant")
    else:
        (repo / "folder/.gitattributes").write_text("* diff=custom")
    with pytest.raises(git.GitOperationError, match="unsupported_repository"):
        git.git_status(repo)


def test_commit_preview_binds_full_symbolic_branch_at_same_oid(repo: Path) -> None:
    (repo / "a.txt").write_text("changed\n")
    command(repo, "add", "a.txt")
    state = git.git_status(repo)
    command(repo, "update-ref", "refs/heads/other", state["head"])
    before = git.git_commit(repo, "Change", state["head"], state["index_fingerprint"], True)
    command(repo, "symbolic-ref", "HEAD", "refs/heads/other")
    after = git.git_commit(repo, "Change", state["head"], state["index_fingerprint"], True)
    assert before["fingerprint"] != after["fingerprint"]
    assert {"label": "Branch", "before": "refs/heads/main", "after": "refs/heads/main"} in before[
        "preview"
    ]


async def test_actual_mcp_commit_readback_failure_remains_uncertain_in_history(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from solus_api.agent.tools.shapes import ToolResult
    from solus_api.routers.sol_confirmations import _decision_summary

    (repo / "a.txt").write_text("approved change\n")
    command(repo, "add", "a.txt")
    state = git.git_status(repo)
    original_run = git.Repository.run

    def fail_readback(self: object, args: list[str], **kwargs: object) -> bytes:
        if args[0] == "cat-file":
            raise git.GitOperationError("git_failed")
        return cast(bytes, original_run(self, args, **kwargs))

    monkeypatch.setattr(git.Repository, "run", fail_readback)
    monkeypatch.setenv("SOLUS_MCP_WORKSPACE", str(repo))
    server = overlay_module("server")
    _content, structured = await server.build_server().call_tool(
        "git_commit",
        {
            "message": "Approved",
            "expected_head": state["head"],
            "expected_index_fingerprint": state["index_fingerprint"],
        },
    )
    assert command(repo, "rev-parse", "HEAD") != state["head"]
    assert structured["uncertain"] is True
    result = ToolResult.success("fixture-call", structured)
    summary = _decision_summary("approve", result).lower()
    assert "uncertain" in summary or "may have changed" in summary
    assert "no automatic retry" in summary or "do not retry automatically" in summary
    assert "applied ok" not in summary and "refused to run" not in summary


@pytest.mark.parametrize("value", ["false", "true", "merges", "interactive"])
def test_unused_editor_and_pull_preferences_are_allowed(repo: Path, value: str) -> None:
    command(repo, "config", "branch.main.vscode-merge-base", "main")
    command(repo, "config", "pull.rebase", value)
    assert git.git_status(repo)["head"] == command(repo, "rev-parse", "HEAD")


def test_arbitrary_pull_setting_is_refused(repo: Path) -> None:
    command(repo, "config", "pull.rebase", "!execute-something")
    with pytest.raises(git.GitOperationError, match="unsafe_config"):
        git.git_status(repo)


def test_branch_switch_before_commit_refuses_execution(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections.abc import Iterator
    from contextlib import contextmanager
    from typing import Any

    (repo / "a.txt").write_text("changed\n")
    command(repo, "add", "a.txt")
    state = git.git_status(repo)
    command(repo, "update-ref", "refs/heads/other", state["head"])
    original_locked = git.Repository.locked

    @contextmanager
    def switch_branch(self: Any) -> Iterator[None]:
        with original_locked(self):
            command(repo, "symbolic-ref", "HEAD", "refs/heads/other")
            yield

    monkeypatch.setattr(git.Repository, "locked", switch_branch)
    with pytest.raises(git.GitOperationError, match="stale_state"):
        git.git_commit(repo, "Change", state["head"], state["index_fingerprint"])
    assert command(repo, "rev-parse", "HEAD") == state["head"]
    assert git.git_status(repo)["index_fingerprint"] == state["index_fingerprint"]
