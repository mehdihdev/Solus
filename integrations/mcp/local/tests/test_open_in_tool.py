"""SOLUSDEV-249 — `open_in_tool`: argv-list launches only, absolute binaries,
`--` before the path on macOS `open`, workspace confinement, unsupported or
uninstalled tools answered with a reason, never raises."""

import os
from pathlib import Path
from typing import Any

import pytest

from .local_paths import overlay_module  # isort: skip

launch = overlay_module("launch")


class Recorder:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.started: list[str] = []
        self.fail = fail

    def run(self, argv: list[str]) -> None:
        if self.fail:
            raise OSError("spawn refused")
        self.calls.append(list(argv))

    def startfile(self, path: str) -> None:
        if self.fail:
            raise OSError("startfile refused")
        self.started.append(path)


def _find(installed: dict[str, str]) -> Any:
    return lambda tool, **_kwargs: installed.get(tool)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    target = tmp_path / "hw" / "main" / "main.kicad_pro"
    target.parent.mkdir(parents=True)
    target.write_text("{}")
    return tmp_path


def _open(
    root: Path, path: str, tool: str, *, platform: str, rec: Recorder, installed: dict[str, str]
) -> dict[str, Any]:
    return launch.open_in_tool(
        root,
        path,
        tool,
        platform=platform,
        run=rec.run,
        startfile=rec.startfile,
        find=_find(installed),
    )


def test_macos_kicad_argv(root: Path) -> None:
    rec = Recorder()
    result = _open(
        root,
        "hw/main/main.kicad_pro",
        "kicad",
        platform="darwin",
        rec=rec,
        installed={"kicad": "KiCad"},
    )
    assert result == {"launched": True, "tool": "kicad", "reason": None}
    target = str((root / "hw/main/main.kicad_pro").resolve())
    assert rec.calls == [["/usr/bin/open", "-a", "KiCad", "--", target]]


def test_macos_vscode_argv(root: Path) -> None:
    rec = Recorder()
    _open(
        root,
        "hw/main/main.kicad_pro",
        "vscode",
        platform="darwin",
        rec=rec,
        installed={"vscode": "Visual Studio Code"},
    )
    target = str((root / "hw/main/main.kicad_pro").resolve())
    assert rec.calls == [["/usr/bin/open", "-a", "Visual Studio Code", "--", target]]


def test_macos_system_is_bare_open(root: Path) -> None:
    rec = Recorder()
    result = _open(
        root, "hw/main/main.kicad_pro", "system", platform="darwin", rec=rec, installed={}
    )
    assert result["launched"] is True
    target = str((root / "hw/main/main.kicad_pro").resolve())
    assert rec.calls == [["/usr/bin/open", "--", target]]


def test_linux_uses_the_resolved_binary(root: Path) -> None:
    rec = Recorder()
    _open(
        root,
        "hw/main/main.kicad_pro",
        "kicad",
        platform="linux",
        rec=rec,
        installed={"kicad": "/usr/bin/kicad"},
    )
    target = str((root / "hw/main/main.kicad_pro").resolve())
    assert rec.calls == [["/usr/bin/kicad", target]]


def test_linux_system_is_xdg_open(root: Path) -> None:
    rec = Recorder()
    _open(root, "hw/main/main.kicad_pro", "system", platform="linux", rec=rec, installed={})
    target = str((root / "hw/main/main.kicad_pro").resolve())
    assert rec.calls == [["/usr/bin/xdg-open", target]]


def test_windows_named_tool_runs_the_exe(root: Path) -> None:
    rec = Recorder()
    exe = "C:\\Program Files\\KiCad\\9.0\\bin\\kicad.exe"
    _open(
        root, "hw/main/main.kicad_pro", "kicad", platform="win32", rec=rec, installed={"kicad": exe}
    )
    target = str((root / "hw/main/main.kicad_pro").resolve())
    assert rec.calls == [[exe, target]]


def test_windows_system_uses_startfile(root: Path) -> None:
    rec = Recorder()
    result = _open(
        root, "hw/main/main.kicad_pro", "system", platform="win32", rec=rec, installed={}
    )
    assert result["launched"] is True
    assert rec.calls == []
    assert rec.started == [str((root / "hw/main/main.kicad_pro").resolve())]


def test_every_launched_argv_uses_an_absolute_binary(root: Path) -> None:
    for platform, installed in (
        ("darwin", {"kicad": "KiCad"}),
        ("linux", {"kicad": "/usr/bin/kicad"}),
    ):
        rec = Recorder()
        _open(
            root, "hw/main/main.kicad_pro", "kicad", platform=platform, rec=rec, installed=installed
        )
        assert rec.calls and os.path.isabs(rec.calls[0][0]), rec.calls


@pytest.mark.parametrize("hostile", ["../x.kicad_pro", "/etc/passwd", "hw/../../x", "C:\\x", ""])
def test_refuses_paths_outside_the_folder(root: Path, hostile: str) -> None:
    rec = Recorder()
    result = _open(root, hostile, "kicad", platform="darwin", rec=rec, installed={"kicad": "KiCad"})
    assert result == {
        "launched": False,
        "tool": "kicad",
        "reason": "path is outside the linked folder",
    }
    assert rec.calls == []


def test_refuses_a_symlink_escaping_the_folder(tmp_path: Path) -> None:
    outside = tmp_path / "outside" / "s.kicad_pro"
    outside.parent.mkdir()
    outside.write_text("x")
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "s.kicad_pro")
    rec = Recorder()
    result = _open(
        root, "s.kicad_pro", "kicad", platform="darwin", rec=rec, installed={"kicad": "KiCad"}
    )
    assert result["launched"] is False and result["reason"] == "path is outside the linked folder"
    assert rec.calls == []


def test_missing_file_has_its_own_reason(root: Path) -> None:
    rec = Recorder()
    result = _open(
        root, "hw/none.kicad_pro", "kicad", platform="darwin", rec=rec, installed={"kicad": "KiCad"}
    )
    assert result["launched"] is False
    assert result["reason"] == "file not found: hw/none.kicad_pro"
    assert rec.calls == []


def test_unsupported_tool(root: Path) -> None:
    rec = Recorder()
    result = _open(root, "hw/main/main.kicad_pro", "bash", platform="darwin", rec=rec, installed={})
    assert result == {"launched": False, "tool": "bash", "reason": "unsupported tool: bash"}
    assert rec.calls == []


@pytest.mark.parametrize(
    ("tool", "reason"),
    [
        ("kicad", "KiCad is not installed on this machine"),
        ("vscode", "Visual Studio Code is not installed on this machine"),
        ("altium", "Altium Designer is not installed on this machine"),
    ],
)
def test_tool_not_installed(root: Path, tool: str, reason: str) -> None:
    rec = Recorder()
    result = _open(root, "hw/main/main.kicad_pro", tool, platform="darwin", rec=rec, installed={})
    assert result == {"launched": False, "tool": tool, "reason": reason}
    assert rec.calls == []


def test_spawn_failure_reason_leaks_no_path_or_user(root: Path) -> None:
    def runner(_argv: list[str]) -> None:
        raise OSError("[Errno 2] No such file: /Users/x/y")

    result = launch.open_in_tool(
        root,
        "hw/main/main.kicad_pro",
        "kicad",
        platform="darwin",
        run=runner,
        startfile=lambda _p: None,
        find=_find({"kicad": "KiCad"}),
    )
    assert result == {"launched": False, "tool": "kicad", "reason": "launch failed"}
    assert "/" not in result["reason"] and "Users" not in result["reason"]


def test_spawn_failure_is_answered_not_raised(root: Path) -> None:
    rec = Recorder(fail=True)
    result = _open(
        root,
        "hw/main/main.kicad_pro",
        "kicad",
        platform="darwin",
        rec=rec,
        installed={"kicad": "KiCad"},
    )
    assert result["launched"] is False
    assert result["tool"] == "kicad"
    assert result["reason"] == "launch failed"


def test_unknown_platform_is_refused(root: Path) -> None:
    rec = Recorder()
    result = _open(
        root, "hw/main/main.kicad_pro", "system", platform="haiku", rec=rec, installed={}
    )
    assert result["launched"] is False and rec.calls == []


def test_default_runner_spawns_detached_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            captured["argv"] = argv
            captured["kwargs"] = kwargs

    monkeypatch.setattr(launch.subprocess, "Popen", FakePopen)
    launch.spawn_detached(["/usr/bin/open", "--", "/tmp/x"])
    assert captured["argv"] == ["/usr/bin/open", "--", "/tmp/x"]
    assert captured["kwargs"].get("shell", False) is False
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["kwargs"]["stdin"] == launch.subprocess.DEVNULL
    assert captured["kwargs"]["stdout"] == launch.subprocess.DEVNULL
    assert captured["kwargs"]["stderr"] == launch.subprocess.DEVNULL
