"""Pinned Git process execution and repository layout refusal."""

from pathlib import Path
from typing import cast

import pytest

from code_paths import overlay_module  # isort: skip

execution = overlay_module("git_execution")


def test_environment_does_not_inherit_git_helpers_or_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_SSH_COMMAND", "unsafe")
    monkeypatch.setenv("GITHUB_TOKEN", "sensitive")
    env = execution.git_environment()
    assert "GIT_SSH_COMMAND" not in env and "GITHUB_TOKEN" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_external_git_directory_refused(tmp_path: Path) -> None:
    (tmp_path / ".git").write_text("gitdir: /tmp/external")
    with pytest.raises(execution.GitOperationError, match="unsupported_repository"):
        execution.Repository(tmp_path)


def test_network_execution_uses_only_fixed_ssh_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/untrusted-agent")
    monkeypatch.setenv("GIT_SSH_COMMAND", "unsafe")
    seen = {}

    def observe(*args: object, **kwargs: object) -> None:
        seen.update(kwargs)
        raise OSError("fixture refuses all network execution")

    monkeypatch.setattr(execution.subprocess, "Popen", observe)
    repo = execution.Repository.__new__(execution.Repository)
    repo.root, repo.binary, repo.used = tmp_path, "/usr/bin/git", 0
    with pytest.raises(execution.GitOperationError):
        repo.run(["ls-remote", "--", "git@github.com:owner/repo.git"], network=True)
    env = cast(dict[str, str], seen["env"])
    assert env["GIT_SSH_COMMAND"] == execution.SSH_COMMAND
    assert "SSH_AUTH_SOCK" not in env
    assert "-F /dev/null" in env["GIT_SSH_COMMAND"]
    assert "-oStrictHostKeyChecking=yes" in env["GIT_SSH_COMMAND"]
    assert "-oIdentityAgent=none" in env["GIT_SSH_COMMAND"]
    assert seen["stdin"] == execution.subprocess.DEVNULL
    assert seen["stderr"] == execution.subprocess.DEVNULL


def test_aggregate_process_output_is_bounded(tmp_path: Path) -> None:
    repo = execution.Repository.__new__(execution.Repository)
    repo.root, repo.binary, repo.used = tmp_path, "/usr/bin/git", execution.MAX_OUTPUT
    with pytest.raises(execution.GitOperationError, match="output_too_large"):
        repo.run(["--version"])


def test_process_group_deadline_terminates_child(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess
    import sys

    monkeypatch.setattr(execution, "COMMAND_TIMEOUT", 0.05)
    repo = execution.Repository.__new__(execution.Repository)
    repo.used = 0
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    ) as process:
        with pytest.raises(execution.GitOperationError, match="command_timeout"):
            repo._capture(process)
        assert process.poll() is not None
