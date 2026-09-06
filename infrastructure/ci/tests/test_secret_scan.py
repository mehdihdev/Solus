"""Exercise the CI scanner against real Git history without storing secret fixtures."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

SCAN_SCRIPT = Path(__file__).resolve().parents[1] / "scan-secrets.sh"
SCAN_ARGS = ["detect", "--source", ".", "--config", ".gitleaks.toml", "--no-banner", "--redact"]
FULL_SCAN_ARGS = [*SCAN_ARGS, "--log-opts=--full-history --all --diff-merges=separate"]


@dataclass(frozen=True)
class Repository:
    path: Path
    env: dict[str, str]
    base: str

    def git(self, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.path), *args],
            env=self.env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def commit(self, message: str) -> str:
        self.git("add", ".")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def scan(self, **overrides: str | None) -> tuple[subprocess.CompletedProcess[str], list[str]]:
        env = {
            **self.env,
            "CI_PIPELINE_SOURCE": "merge_request_event",
            "CI_MERGE_REQUEST_DIFF_BASE_SHA": self.base,
            "CI_COMMIT_SHA": self.git("rev-parse", "HEAD"),
            **{key: value for key, value in overrides.items() if value is not None},
        }
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
        result = subprocess.run(
            ["sh", str(SCAN_SCRIPT)], cwd=self.path, env=env, capture_output=True, text=True
        )
        calls = Path(self.env["SCAN_CALLS"])
        return result, calls.read_text().splitlines() if calls.exists() else []


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    scanner = bin_path / "gitleaks"
    scanner.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$SCAN_CALLS"\nexit "${SCAN_EXIT:-0}"\n')
    scanner.chmod(0o755)
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    env = {
        "PATH": f"{bin_path}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "HOME": str(tmp_path),
        "GIT_CONFIG_NOSYSTEM": "1",
        "SCAN_CALLS": str(tmp_path / "scanner-arguments"),
    }
    repo = Repository(repo_path, env, "")
    repo.git("init", "--initial-branch=feature")
    repo.git("config", "user.name", "CI Test")
    repo.git("config", "user.email", "ci@example.invalid")
    (repo.path / ".gitleaks.toml").write_text("# Initial scanner policy\n")
    (repo.path / ".gitleaksignore").write_text("# Initial ignore policy\n")
    (repo.path / "baseline.txt").write_text("content already scanned before this merge request\n")
    base = repo.commit("Baseline")
    (repo.path / "feature.txt").write_text("new feature content\n")
    repo.commit("Feature")
    return Repository(repo.path, env, base)


def test_merge_request_scans_every_introduced_commit_including_deleted_content(
    repository: Repository,
) -> None:
    transient_file = repository.path / "transient.txt"
    transient_file.write_text("content introduced and then deleted\n")
    introduced = repository.commit("Introduce transient content")
    transient_file.unlink()
    head = repository.commit("Remove transient content")

    result, args = repository.scan()

    assert result.returncode == 0, result.stderr
    commit_range = f"{repository.base}..{head}"
    assert args == [*SCAN_ARGS, f"--log-opts=--full-history --diff-merges=separate {commit_range}"]
    commits = repository.git("rev-list", commit_range).splitlines()
    assert introduced in commits
    assert head in commits
    assert repository.base not in commits
    history = repository.git("log", "-p", *_selected_log_options(args))
    assert "+content introduced and then deleted" in history
    assert "content already scanned before this merge request" not in history


@pytest.mark.parametrize("policy_file", [".gitleaks.toml", ".gitleaksignore"])
@pytest.mark.parametrize("change", ["modify", "delete", "change-and-revert"])
def test_scanner_policy_changes_require_full_history(
    repository: Repository, policy_file: str, change: str
) -> None:
    path = repository.path / policy_file
    original = path.read_text()
    if change == "delete":
        path.unlink()
    else:
        path.write_text("# Changed policy\n")
    repository.commit("Change scanner policy")
    if change == "change-and-revert":
        path.write_text(original)
        repository.commit("Restore scanner policy")

    result, args = repository.scan()

    assert result.returncode == 0, result.stderr
    assert args == FULL_SCAN_ARGS


def test_tags_scan_full_history_without_a_merge_request_base(repository: Repository) -> None:
    result, args = repository.scan(
        CI_PIPELINE_SOURCE="push", CI_COMMIT_TAG="v1.0.0", CI_MERGE_REQUEST_DIFF_BASE_SHA=None
    )

    assert result.returncode == 0, result.stderr
    assert args == FULL_SCAN_ARGS


def _selected_log_options(args: list[str]) -> list[str]:
    # Gitleaks uses these defaults only when no custom --log-opts is supplied.
    options = next(
        (arg.removeprefix("--log-opts=") for arg in args if arg.startswith("--log-opts=")),
        "--full-history --all",
    )
    return options.split()


@pytest.mark.parametrize("tag", [None, "v1.0.0"])
@pytest.mark.parametrize("delete_after_merge", [False, True])
def test_scan_includes_content_introduced_only_by_a_merge(
    repository: Repository, tag: str | None, delete_after_merge: bool
) -> None:
    repository.git("checkout", "-b", "side", repository.base)
    (repository.path / "side.txt").write_text("side branch content\n")
    repository.commit("Side branch")
    repository.git("checkout", "feature")
    repository.git("merge", "--no-ff", "--no-commit", "side")
    merge_file = repository.path / "merge-content.txt"
    merge_file.write_text("content introduced only in merge resolution\n")
    repository.commit("Merge with additional content")
    if delete_after_merge:
        merge_file.unlink()
        repository.commit("Delete merge-only content")

    result, args = repository.scan(CI_COMMIT_TAG=tag)

    assert result.returncode == 0, result.stderr
    history = repository.git("log", "-p", "-U0", *_selected_log_options(args))
    assert "+content introduced only in merge resolution" in history


@pytest.mark.parametrize("policy_file", [".gitleaks.toml", ".gitleaksignore"])
def test_discarded_side_branch_policy_changes_require_full_history(
    repository: Repository, policy_file: str
) -> None:
    repository.git("checkout", "-b", "side", repository.base)
    (repository.path / policy_file).write_text("# Side branch policy\n")
    repository.commit("Side branch policy change")
    repository.git("checkout", "feature")
    repository.git("merge", "--no-ff", "-s", "ours", "-m", "Discard side branch changes", "side")

    result, args = repository.scan()

    assert result.returncode == 0, result.stderr
    assert "--all" in _selected_log_options(args)


def test_full_scan_preserves_history_on_other_refs(repository: Repository) -> None:
    repository.git("checkout", "-b", "unmerged", repository.base)
    (repository.path / "unmerged.txt").write_text("content on a different ref\n")
    repository.commit("Unmerged content")
    repository.git("checkout", "feature")

    result, args = repository.scan(CI_COMMIT_TAG="v1.0.0")

    assert result.returncode == 0, result.stderr
    history = repository.git("log", "-p", "-U0", *_selected_log_options(args))
    assert "+content on a different ref" in history


@pytest.mark.parametrize("variable", ["CI_MERGE_REQUEST_DIFF_BASE_SHA", "CI_COMMIT_SHA"])
@pytest.mark.parametrize("value", [None, "", "--all", "not-a-sha", "abcd123", "0" * 40])
def test_missing_invalid_or_unavailable_revisions_fail_closed(
    repository: Repository, variable: str, value: str | None
) -> None:
    result, args = repository.scan(**{variable: value})

    assert result.returncode != 0
    assert args == []


@pytest.mark.parametrize("variable", ["CI_MERGE_REQUEST_DIFF_BASE_SHA", "CI_COMMIT_SHA"])
def test_non_commit_objects_fail_closed(repository: Repository, variable: str) -> None:
    blob = repository.git("rev-parse", "HEAD:feature.txt")

    result, args = repository.scan(**{variable: blob})

    assert result.returncode != 0
    assert args == []


def test_empty_merge_request_range_fails_closed(repository: Repository) -> None:
    result, args = repository.scan(
        CI_MERGE_REQUEST_DIFF_BASE_SHA=repository.git("rev-parse", "HEAD")
    )

    assert result.returncode != 0
    assert args == []


def test_unrelated_merge_request_base_fails_closed(repository: Repository) -> None:
    head = repository.git("rev-parse", "HEAD")
    repository.git("checkout", "--orphan", "unrelated")
    unrelated = repository.commit("Unrelated root")
    repository.git("checkout", "feature")

    result, args = repository.scan(CI_MERGE_REQUEST_DIFF_BASE_SHA=unrelated, CI_COMMIT_SHA=head)

    assert result.returncode != 0
    assert args == []


@pytest.mark.parametrize("source", [None, "", "push", "schedule", "web"])
def test_unsupported_pipeline_fails_closed(repository: Repository, source: str | None) -> None:
    result, args = repository.scan(CI_PIPELINE_SOURCE=source)

    assert result.returncode != 0
    assert args == []


@pytest.mark.parametrize("tag", [None, "v1.0.0"])
def test_scanner_failure_fails_the_job(repository: Repository, tag: str | None) -> None:
    result, args = repository.scan(CI_COMMIT_TAG=tag, SCAN_EXIT="7")

    assert result.returncode == 7
    assert args[: len(SCAN_ARGS)] == SCAN_ARGS
