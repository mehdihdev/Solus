"""SOLUSDEV-317 — the OS sandbox every executing `code` tool runs in
(docs/api/code-command-execution.md §3): probe, wrapping per platform, the
writable set, the macOS denials, git metadata detection, and REAL sandbox-exec
behaviour on this macOS machine."""

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

import pytest

from code_paths import SOLUS_DIR, overlay_module  # isort: skip

sandbox = overlay_module("sandbox")

CACHES = (
    ".cache",
    "Library/Caches",
    ".ros",
    ".npm",
    ".pnpm-store",
    ".local/share/pnpm",
    ".local/share/uv",
    ".cargo/registry",
    ".cargo/git",
    ".platformio",
    ".arduino15",
    ".gradle",
    ".colcon",
)


class FakeStat:
    def __init__(self, uid: int = 0, mode: int = 0o100755) -> None:
        self.st_uid = uid
        self.st_mode = mode


def test_declared_caches_are_exactly_the_spec_list() -> None:
    assert sandbox.HOME_CACHES == CACHES
    assert sandbox.WRITABLE_LABELS[:3] == ("<workspace>", "<tmp>", "<devices>")
    assert sandbox.WRITABLE_LABELS[3:] == tuple(f"~/{cache}" for cache in CACHES)


def test_probe_macos_requires_the_root_owned_sandbox_exec() -> None:
    kind, _ = sandbox.probe("darwin", stat_fn=lambda _p: FakeStat(), smoke=lambda: True)
    assert kind == "sandbox-exec"
    kind, why = sandbox.probe("darwin", stat_fn=lambda _p: FakeStat(uid=501), smoke=lambda: True)
    assert kind is None and "root-owned" in why
    kind, why = sandbox.probe(
        "darwin", stat_fn=lambda _p: FakeStat(mode=0o100777), smoke=lambda: True
    )
    assert kind is None and "writable" in why
    kind, why = sandbox.probe("darwin", stat_fn=lambda _p: FakeStat(), smoke=lambda: False)
    assert kind is None and "sandbox-exec" in why


def test_probe_macos_missing_binary() -> None:
    def missing(_path: str) -> Any:
        raise FileNotFoundError(_path)

    kind, why = sandbox.probe("darwin", stat_fn=missing, smoke=lambda: True)
    assert kind is None and "not found" in why


def test_probe_linux_needs_landlock_abi_one() -> None:
    assert sandbox.probe("linux", landlock_abi=lambda: 3)[0] == "landlock"
    kind, why = sandbox.probe("linux", landlock_abi=lambda: 0)
    assert kind is None and "landlock" in why

    def broken() -> int:
        raise OSError(38, "ENOSYS")

    kind, why = sandbox.probe("linux", landlock_abi=broken)
    assert kind is None and "landlock" in why


def test_probe_other_platforms_refuse() -> None:
    kind, why = sandbox.probe("win32")
    assert kind is None and "win32" in why


def test_available_is_cached_for_the_server_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def counted() -> tuple[str, str]:
        calls.append(1)
        return ("landlock", "ok")

    monkeypatch.setattr(sandbox, "probe", counted)
    sandbox.available.cache_clear()
    try:
        assert sandbox.available() == ("landlock", "ok")
        assert sandbox.available() == ("landlock", "ok")
        assert calls == [1]
    finally:
        sandbox.available.cache_clear()


def test_macos_wrap_uses_realpaths_and_the_constant_profile(tmp_path: Path) -> None:
    link = tmp_path / "link"
    (tmp_path / "real").mkdir()
    link.symlink_to(tmp_path / "real")
    argv = sandbox.wrap(
        "sandbox-exec", ["/usr/bin/make", "-j4"], workspace=link, home=link, tmpdir=link
    )
    real = os.path.realpath(tmp_path / "real")
    assert argv == [
        "/usr/bin/sandbox-exec",
        "-p",
        sandbox.MACOS_PROFILE,
        "-D",
        f"WORKSPACE={real}",
        "-D",
        f"TMP={real}",
        "-D",
        f"HOME={real}",
        "/usr/bin/make",
        "-j4",
    ]


def test_macos_profile_states_the_writable_set_and_denials() -> None:
    profile = sandbox.MACOS_PROFILE
    assert profile.startswith("(version 1)(allow default)(deny file-write*)")
    for cache in CACHES:
        assert f'(string-append (param "HOME") "/{cache}")' in profile, cache
    for literal in ('"/private/tmp"', '"/private/var/folders"', '"/dev/null"', '"/dev/zero"'):
        assert literal in profile
    denials = profile.rsplit("(deny file-write*", 1)[1]
    assert '"/.git/hooks"' in denials and '"/.git/config"' in denials and '"/.solus"' in denials


def test_linux_wrap_runs_the_isolated_helper_over_existing_writable_paths(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".ros").mkdir(parents=True)
    (home / ".cache").mkdir()
    workspace = tmp_path / "ws"
    workspace.mkdir()
    argv = sandbox.wrap(
        "landlock",
        ["/opt/ros/bin/colcon", "build"],
        workspace=workspace,
        home=home,
        tmpdir=tmp_path,
    )
    assert argv[:3] == [sys.executable, "-I", str(SOLUS_DIR / "landlock_exec.py")]
    separator = argv.index("--")
    assert argv[separator + 1 :] == ["/opt/ros/bin/colcon", "build"]
    granted = argv[3:separator:2]
    assert set(argv[3:separator:2]) == {"--rw"}
    paths = argv[4:separator:2]
    assert paths[0] == os.path.realpath(workspace) and paths[1] == os.path.realpath(tmp_path)
    assert os.path.realpath(home / ".ros") in paths and os.path.realpath(home / ".cache") in paths
    assert not any(path.endswith(".npm") for path in paths), "missing caches grant nothing"
    assert "/dev/null" in paths and granted


def test_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError):
        sandbox.wrap(None, ["/bin/true"], workspace=Path("/"), home=Path("/"), tmpdir=Path("/"))


def test_git_metadata_digest_detects_hook_and_config_changes(tmp_path: Path) -> None:
    assert sandbox.git_metadata_digest(tmp_path) == sandbox.git_metadata_digest(tmp_path)
    (tmp_path / ".git" / "hooks").mkdir(parents=True)
    (tmp_path / ".git" / "config").write_text("[core]\n")
    before = sandbox.git_metadata_digest(tmp_path)
    (tmp_path / "src.py").write_text("x = 1\n")
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    assert sandbox.git_metadata_digest(tmp_path) == before
    (tmp_path / ".git" / "hooks" / "pre-commit").write_text("#!/bin/sh\n")
    after_hook = sandbox.git_metadata_digest(tmp_path)
    assert after_hook != before
    (tmp_path / ".git" / "config").write_text("[core]\nhooksPath = /x\n")
    assert sandbox.git_metadata_digest(tmp_path) != after_hook


# --- the real macOS sandbox ------------------------------------------------------------


def _macos_sandbox() -> bool:
    return str(sys.platform) == "darwin" and sandbox.probe()[0] == "sandbox-exec"


@pytest.mark.skipif(not _macos_sandbox(), reason="needs macOS with /usr/bin/sandbox-exec")
def test_real_sandbox_exec_confines_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / ".git" / "hooks").mkdir(parents=True)
    (workspace / ".git" / "config").write_text("[core]\n")
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    real_home_probe = Path.home() / f".solus-sandbox-probe-{uuid.uuid4().hex}"
    script = "; ".join(
        [
            "echo ok > inside.txt && echo inside-ok",
            f"echo x > {real_home_probe} 2>/dev/null || echo home-denied",
            "echo x > .git/hooks/pre-commit 2>/dev/null || echo hooks-denied",
            "echo x >> .git/config 2>/dev/null || echo config-denied",
            f"mkdir -p {fake_home}/.solus 2>/dev/null || echo solus-denied",
            f"mkdir -p {fake_home}/.cache/tool && echo cache-ok",
        ]
    )
    try:
        result = subprocess.run(
            sandbox.wrap(
                "sandbox-exec",
                ["/bin/sh", "-c", script],
                workspace=workspace,
                home=fake_home,
                tmpdir=tmp_path,
            ),
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
            env={"PATH": "/usr/bin:/bin"},
        )
    finally:
        real_home_probe.unlink(missing_ok=True)
    lines = result.stdout.split()
    assert lines == [
        "inside-ok",
        "home-denied",
        "hooks-denied",
        "config-denied",
        "solus-denied",
        "cache-ok",
    ], result.stderr
    assert (workspace / "inside.txt").read_text() == "ok\n"
    assert not (workspace / ".git" / "hooks" / "pre-commit").exists()
    assert (workspace / ".git" / "config").read_text() == "[core]\n"


@pytest.mark.skipif(not _macos_sandbox(), reason="needs macOS with /usr/bin/sandbox-exec")
def test_real_sandbox_runs_python_with_network_and_reads_unrestricted(tmp_path: Path) -> None:
    code = "import os, socket; socket.socket(); print(len(os.listdir('/usr/bin')) > 0)"
    result = subprocess.run(
        sandbox.wrap(
            "sandbox-exec",
            [sys.executable, "-c", code],
            workspace=tmp_path,
            home=tmp_path,
            tmpdir=tmp_path,
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0 and result.stdout.strip() == "True", result.stderr
