"""SOLUSDEV-249 — `tools_installed` is probed, never assumed: macOS app
bundles, Linux `which`, Windows documented roots; altium is Windows-only;
missing = false. Probes are injectable so no test touches the real machine."""

from collections.abc import Callable

import pytest

from .local_paths import overlay_module  # isort: skip

detect = overlay_module("detect")

ALL_TOOLS = ("kicad", "altium", "vscode")


def _exists(present: set[str]) -> Callable[[str], bool]:
    return lambda path: path in present


def _which(present: dict[str, str]) -> Callable[[str], str | None]:
    return lambda name: present.get(name)


def _listdir(tree: dict[str, list[str]]) -> Callable[[str], list[str]]:
    return lambda path: list(tree.get(path, []))


def test_result_always_carries_all_three_keys() -> None:
    result = detect.tools_installed(platform="darwin", exists=_exists(set()), which=_which({}))
    assert result == {"kicad": False, "altium": False, "vscode": False}


@pytest.mark.parametrize("kicad_app", ["/Applications/KiCad/KiCad.app", "/Applications/KiCad.app"])
def test_darwin_probes_both_kicad_bundle_locations(kicad_app: str) -> None:
    result = detect.tools_installed(
        platform="darwin", exists=_exists({kicad_app}), which=_which({})
    )
    assert result["kicad"] is True
    assert result["altium"] is False
    assert result["vscode"] is False


def test_darwin_vscode_bundle() -> None:
    result = detect.tools_installed(
        platform="darwin",
        exists=_exists({"/Applications/Visual Studio Code.app"}),
        which=_which({}),
    )
    assert result["vscode"] is True and result["kicad"] is False


def test_darwin_ignores_which_and_altium_is_always_false() -> None:
    result = detect.tools_installed(
        platform="darwin",
        exists=_exists({"C:\\Program Files\\Altium\\AD24\\X2.EXE"}),
        which=_which({"kicad": "/usr/local/bin/kicad", "code": "/usr/local/bin/code"}),
    )
    assert result == {"kicad": False, "altium": False, "vscode": False}


def test_linux_uses_which() -> None:
    result = detect.tools_installed(
        platform="linux",
        exists=_exists({"/Applications/KiCad.app"}),
        which=_which({"kicad": "/usr/bin/kicad", "code": "/usr/bin/code"}),
    )
    assert result == {"kicad": True, "altium": False, "vscode": True}


def test_linux_missing_binaries() -> None:
    result = detect.tools_installed(platform="linux", exists=_exists(set()), which=_which({}))
    assert result == {"kicad": False, "altium": False, "vscode": False}


def test_windows_probes_documented_roots() -> None:
    tree = {
        "C:\\Program Files\\KiCad": ["8.0", "9.0"],
        "C:\\Program Files\\Altium": ["AD24"],
    }
    present = {
        "C:\\Program Files\\KiCad\\9.0\\bin\\kicad.exe",
        "C:\\Program Files\\Altium\\AD24\\X2.EXE",
        "C:\\Users\\me\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
    }
    result = detect.tools_installed(
        platform="win32",
        exists=_exists(present),
        which=_which({}),
        listdir=_listdir(tree),
        home="C:\\Users\\me",
    )
    assert result == {"kicad": True, "altium": True, "vscode": True}


def test_windows_system_wide_vscode_without_home() -> None:
    result = detect.tools_installed(
        platform="win32",
        exists=_exists({"C:\\Program Files\\Microsoft VS Code\\Code.exe"}),
        which=_which({}),
        listdir=_listdir({}),
        home="",
    )
    assert result == {"kicad": False, "altium": False, "vscode": True}


def test_windows_nothing_installed() -> None:
    result = detect.tools_installed(
        platform="win32", exists=_exists(set()), which=_which({}), listdir=_listdir({}), home=""
    )
    assert result == {"kicad": False, "altium": False, "vscode": False}


def test_find_tool_returns_the_launch_target_per_platform() -> None:
    assert (
        detect.find_tool(
            "kicad", platform="darwin", exists=_exists({"/Applications/KiCad/KiCad.app"})
        )
        == "KiCad"
    )
    assert (
        detect.find_tool(
            "vscode",
            platform="darwin",
            exists=_exists({"/Applications/Visual Studio Code.app"}),
        )
        == "Visual Studio Code"
    )
    assert (
        detect.find_tool("kicad", platform="linux", which=_which({"kicad": "/usr/bin/kicad"}))
        == "/usr/bin/kicad"
    )
    assert detect.find_tool("altium", platform="linux", which=_which({"altium": "/x"})) is None
    assert detect.find_tool("unknown", platform="darwin", exists=_exists(set())) is None


def test_probe_failures_read_as_not_installed() -> None:
    def boom(_path: str) -> bool:
        raise OSError("probe exploded")

    result = detect.tools_installed(platform="darwin", exists=boom, which=_which({}))
    assert result == {"kicad": False, "altium": False, "vscode": False}


def test_default_probe_runs_on_this_machine_without_raising() -> None:
    result = detect.tools_installed()
    assert set(result) == set(ALL_TOOLS)
    assert all(isinstance(value, bool) for value in result.values())
