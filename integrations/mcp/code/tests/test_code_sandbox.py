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
    assert sandbox.probe("linux", landlock_abi=lambda: 3)[0] == "landlock-abi3"
    assert sandbox.probe("linux", landlock_abi=lambda: 1)[0] == "landlock-abi1"
    kind, why = sandbox.probe("linux", landlock_abi=lambda: 0)
    assert kind is None and "landlock" in why

    def broken() -> int:
        raise OSError(38, "ENOSYS")

    kind, why = sandbox.probe("linux", landlock_abi=broken)
    assert kind is None and "landlock" in why


def test_probe_other_platforms_refuse() -> None:
    kind, why = sandbox.probe("win32")
    assert kind is None and "win32" in why


@pytest.mark.own_sandbox_probe
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
    git = f"{real}/.git"
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
        "-D",
        f"DOTGIT={git}",
        "-D",
        f"GIT_DIR={git}",
        "-D",
        f"GIT_DIR_RE={sandbox.sbpl_regex_escape(git)}",
        "-D",
        f"GIT_COMMON={git}",
        "-D",
        f"GIT_COMMON_RE={sandbox.sbpl_regex_escape(git)}",
        "/usr/bin/make",
        "-j4",
    ]


def test_regex_escape_neutralises_metacharacters() -> None:
    assert sandbox.sbpl_regex_escape("/a.b+c(d)[e]{f}*?^$|\\g-h") == (
        "/a\\.b\\+c\\(d\\)\\[e\\]\\{f\\}\\*\\?\\^\\$\\|\\\\g-h"
    )


def test_macos_profile_states_the_writable_set_and_denials() -> None:
    profile = sandbox.MACOS_PROFILE
    assert profile.startswith("(version 1)(allow default)(deny file-write*)")
    for cache in CACHES:
        assert f'(string-append (param "HOME") "/{cache}")' in profile, cache
    for literal in ('"/private/tmp"', '"/private/var/folders"', '"/dev/null"', '"/dev/zero"'):
        assert literal in profile
    denials = profile.split("(deny file-write*", 2)[2]
    for fragment in (
        '(literal (param "DOTGIT"))',
        '"/hooks"',
        '"/info"',
        '"/config[^/]*$"',
        '"/modules/',
        '"/worktrees/[^/]+/config[^/]*$"',
        '"/commondir"',
        '"/.solus"',
    ):
        assert fragment in denials, fragment
    for program in sandbox.MACOS_DENIED_EXEC:
        assert f'(literal "{program}")' in profile
    assert '(deny mach-lookup (global-name "com.apple.coreservices.appleevents"))' in profile


def test_protected_git_dirs_follow_gitfile_and_commondir(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    assert sandbox.protected_git_dirs(ws) == (str(ws / ".git"), str(ws / ".git"))
    main = tmp_path / "main" / ".git"
    (main / "worktrees" / "feature").mkdir(parents=True)
    (main / "worktrees" / "feature" / "commondir").write_text("../..\n")
    (ws / ".git").write_text(f"gitdir: {main / 'worktrees' / 'feature'}\n")
    git_dir, common = sandbox.protected_git_dirs(ws)
    assert git_dir == os.path.realpath(main / "worktrees" / "feature")
    assert common == os.path.realpath(main)
    (ws / ".git").write_text("garbage\n")
    assert sandbox.protected_git_dirs(ws) == (str(ws / ".git"), str(ws / ".git"))


def test_limitations_are_reported_per_kind() -> None:
    mac = sandbox.limitations("sandbox-exec")
    assert mac == ["reads, exec and network are not restricted"]
    old = sandbox.limitations("landlock-abi1")
    assert "truncate not confined" in old
    assert "file metadata (chmod/chown/utimes) not confined" in old
    assert "unix-socket/signal scoping unavailable" in old
    assert ".git hooks and config are protected by detection only" in old
    new = sandbox.limitations("landlock-abi6")
    assert "truncate not confined" not in new
    assert "unix-socket/signal scoping unavailable" not in new
    assert sandbox.limitations(None) == []


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
    git = tmp_path / ".git"
    (git / "hooks").mkdir(parents=True)
    (git / "config").write_text("[core]\n")
    (git / "objects").mkdir()
    before = sandbox.git_metadata_digest(tmp_path)
    (tmp_path / "src.py").write_text("x = 1\n")
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "index").write_bytes(b"DIRC")
    (git / "objects" / "ab").write_bytes(b"x")
    assert sandbox.git_metadata_digest(tmp_path) == before, "ordinary git state is not protected"
    for change in (
        lambda: (git / "hooks" / "pre-commit").write_text("#!/bin/sh\n"),
        lambda: (git / "config").write_text("[core]\nhooksPath = /x\n"),
        lambda: (git / "config.worktree").write_text("[core]\n"),
        lambda: (git / "info").mkdir(),
        lambda: (git / "info" / "attributes").write_text("* filter=x\n"),
        lambda: (git / "commondir").write_text(".."),
        lambda: (git / "modules" / "sub" / "hooks").mkdir(parents=True),
        lambda: (git / "modules" / "sub" / "config").write_text("[core]\n"),
        lambda: (git / "worktrees" / "w").mkdir(parents=True),
        lambda: (git / "worktrees" / "w" / "config.worktree").write_text("[x]\n"),
        lambda: (git / "hooks" / "pre-commit").chmod(0o755),
    ):
        previous = sandbox.git_metadata_digest(tmp_path)
        change()
        assert sandbox.git_metadata_digest(tmp_path) != previous


def test_git_metadata_digest_hashes_whole_files(tmp_path: Path) -> None:
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "big").write_bytes(b"a" * (2 * 1024 * 1024))
    before = sandbox.git_metadata_digest(tmp_path)
    (hooks / "big").write_bytes(b"a" * (2 * 1024 * 1024 - 1) + b"b")
    assert sandbox.git_metadata_digest(tmp_path) != before


def test_git_metadata_digest_fails_closed_past_its_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True)
    for index in range(5):
        (hooks / f"h{index}").write_text("x")
    monkeypatch.setattr(sandbox, "MAX_GIT_ENTRIES", 3)
    assert sandbox.git_metadata_digest(tmp_path) != sandbox.git_metadata_digest(tmp_path)
    monkeypatch.setattr(sandbox, "MAX_GIT_ENTRIES", 4096)
    monkeypatch.setattr(sandbox, "MAX_GIT_BYTES", 2)
    assert sandbox.git_metadata_digest(tmp_path) != sandbox.git_metadata_digest(tmp_path)


def test_git_metadata_digest_follows_the_gitfile(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    real = tmp_path / "real.git"
    (real / "hooks").mkdir(parents=True)
    (ws / ".git").write_text(f"gitdir: {real}\n")
    before = sandbox.git_metadata_digest(ws)
    (real / "hooks" / "post-checkout").write_text("#!/bin/sh\n")
    assert sandbox.git_metadata_digest(ws) != before


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


def _run_sandboxed(workspace: Path, script: str, tmp_path: Path) -> list[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    result = subprocess.run(
        sandbox.wrap(
            "sandbox-exec",
            ["/bin/sh", "-c", script],
            workspace=workspace,
            home=home,
            tmpdir=tmp_path,
        ),
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(home)},
    )
    return result.stdout.split()


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["/usr/bin/git", "init", "-q", str(path)], check=True, timeout=60)


@pytest.mark.skipif(not _macos_sandbox(), reason="needs macOS with /usr/bin/sandbox-exec")
def test_real_sandbox_keeps_git_usable_but_protects_its_metadata(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    _git_repo(workspace)
    (workspace / "a.txt").write_text("a\n")
    script = "; ".join(
        [
            "/usr/bin/git add a.txt >/dev/null 2>&1 && echo add-ok",
            "/usr/bin/git status --porcelain >/dev/null 2>&1 && echo status-ok",
            "mv .git .gitx 2>/dev/null || echo rename-denied",
            "echo x > .git/config.worktree 2>/dev/null || echo worktree-config-denied",
            "mkdir -p .git/info 2>/dev/null; echo x > .git/info/attributes 2>/dev/null"
            " || echo info-denied",
            "echo x > .git/commondir 2>/dev/null || echo commondir-denied",
            "mkdir -p .git/modules/sub/hooks 2>/dev/null;"
            " echo x > .git/modules/sub/hooks/post 2>/dev/null || echo module-hook-denied",
            "echo x > .git/modules/sub/config 2>/dev/null || echo module-config-denied",
        ]
    )
    assert _run_sandboxed(workspace, script, tmp_path) == [
        "add-ok",
        "status-ok",
        "rename-denied",
        "worktree-config-denied",
        "info-denied",
        "commondir-denied",
        "module-hook-denied",
        "module-config-denied",
    ]
    assert (workspace / ".git").is_dir()


@pytest.mark.skipif(not _macos_sandbox(), reason="needs macOS with /usr/bin/sandbox-exec")
def test_real_sandbox_protects_a_gitfile_target_inside_the_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "store" / "repo.git" / "hooks").mkdir(parents=True)
    (workspace / ".git").write_text(f"gitdir: {workspace / 'store' / 'repo.git'}\n")
    script = "; ".join(
        [
            "echo x > store/repo.git/hooks/pre-commit 2>/dev/null || echo hook-denied",
            "echo x > store/repo.git/config 2>/dev/null || echo config-denied",
            "echo x > .git 2>/dev/null || echo gitfile-denied",
            "echo x > store/other.txt && echo other-ok",
        ]
    )
    assert _run_sandboxed(workspace, script, tmp_path) == [
        "hook-denied",
        "config-denied",
        "gitfile-denied",
        "other-ok",
    ]


@pytest.mark.skipif(not _macos_sandbox(), reason="needs macOS with /usr/bin/sandbox-exec")
def test_real_sandbox_refuses_apple_event_and_launch_tools(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    script = "; ".join(
        [
            "/usr/bin/true && echo true-ok",
            "/usr/bin/osascript -e 'return 1' >/dev/null 2>&1 || echo osascript-refused",
            "/bin/launchctl list >/dev/null 2>&1 || echo launchctl-refused",
            "/usr/bin/open -h >/dev/null 2>&1 || echo open-refused",
        ]
    )
    assert _run_sandboxed(workspace, script, tmp_path) == [
        "true-ok",
        "osascript-refused",
        "launchctl-refused",
        "open-refused",
    ]
