"""Family detection runs only binaries found under SOLUS_GAZEBO_PATH, reads
versions from the recorded CLI shapes (RECON §2), and never runs `gazebo`."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from integrations.mcp.gazebo.solus.family_detect import (
    Family,
    Runner,
    detect_families,
    family_for,
    family_hint,
    gazebo_search_path,
    newest,
    subprocess_run,
)


def _recording_runner(outputs: dict[str, str | None]) -> tuple[list[list[str]], Runner]:
    calls: list[list[str]] = []

    def run(argv: list[str], timeout: float) -> str | None:
        calls.append(list(argv))
        assert timeout > 0
        return outputs.get(Path(argv[0]).name)

    return calls, run


def _bins(tmp_path: Path, *names: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in names:
        exe = bin_dir / name
        exe.write_text("#!/bin/sh\nexit 1\n")
        exe.chmod(0o755)
    return bin_dir


def test_detect_new_family_from_gz_sim_versions(tmp_path: Path) -> None:
    bin_dir = _bins(tmp_path, "gz")
    calls, run = _recording_runner({"gz": "8.15.0\n"})
    families = detect_families([bin_dir], run)
    assert families == (Family(name="gz", version="8.15.0", bin_dir=bin_dir, exe=bin_dir / "gz"),)
    assert calls == [[str(bin_dir / "gz"), "sim", "--versions"]]
    assert families[0].distro == "Harmonic"


def test_detect_ignition_and_classic_side_by_side(fixture_bins: Path) -> None:
    families = detect_families([fixture_bins / "ign6", fixture_bins / "classic11"], subprocess_run)
    assert [(f.name, f.version, f.exe.name) for f in families] == [
        ("ignition", "6.16.0", "ign"),
        ("classic", "11.15.1", "gzserver"),
    ]
    assert families[0].distro == "Fortress"
    assert families[1].distro is None


def test_detect_all_three_fixture_families_and_newest(fixture_bins: Path) -> None:
    dirs = [fixture_bins / "classic11", fixture_bins / "ign6", fixture_bins / "gz8"]
    families = detect_families(dirs, subprocess_run)
    assert sorted(f.name for f in families) == ["classic", "gz", "ignition"]
    assert newest(families) is not None
    assert newest(families).name == "gz"  # type: ignore[union-attr]
    assert newest(()) is None


def test_newest_compares_versions_numerically_not_lexically(tmp_path: Path) -> None:
    older = Family(name="gz", version="8.9.0", bin_dir=tmp_path / "a", exe=tmp_path / "a" / "gz")
    newer = Family(name="gz", version="8.15.0", bin_dir=tmp_path / "b", exe=tmp_path / "b" / "gz")
    assert newest((older, newer)) == newer
    assert newest((newer, older)) == newer


def test_classic_banner_with_nonzero_exit_is_success_and_gazebo_is_never_run(
    fixture_bins: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mark = tmp_path / "mark"
    monkeypatch.setenv("SOLUS_FIXTURE_MARK", str(mark))
    # The real runner: gzserver exits 255 with the banner on stdout (RECON §2).
    assert subprocess_run([str(fixture_bins / "classic11" / "gzserver"), "--version"], 5.0)
    families = detect_families([fixture_bins / "classic11"], subprocess_run)
    assert [(f.name, f.version) for f in families] == [("classic", "11.15.1")]
    assert not mark.exists(), "the detector ran `gazebo`, which hangs on real installs"


def test_classic_gz_is_not_the_new_family(fixture_bins: Path) -> None:
    calls, run = _recording_runner({"gz": "", "gzserver": None})
    bin_dir = fixture_bins / "classic11"
    assert detect_families([bin_dir], run) == ()
    assert [str(bin_dir / "gazebo"), "--version"] not in calls


def test_runner_returns_none_when_binary_cannot_run_or_times_out(tmp_path: Path) -> None:
    assert subprocess_run([str(tmp_path / "missing"), "--version"], 1.0) is None
    slow = tmp_path / "slow"
    slow.write_text("#!/bin/sh\nsleep 5\n")
    slow.chmod(0o755)
    assert subprocess_run([str(slow)], 0.2) is None


def test_detect_never_uses_ambient_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _bins(tmp_path, "gz", "ign", "gzserver")
    monkeypatch.setenv("PATH", f"{fake}{os.pathsep}/usr/bin:/bin")
    monkeypatch.delenv("SOLUS_GAZEBO_PATH", raising=False)
    calls, run = _recording_runner({"gz": "8.15.0\n", "ign": "6.16.0\n"})
    assert gazebo_search_path(os.environ) == ()
    assert detect_families(gazebo_search_path(os.environ), run) == ()
    assert calls == []


def test_search_path_keeps_only_absolute_existing_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = tmp_path / "real"
    real.mkdir()
    monkeypatch.setenv("SOLUS_GAZEBO_PATH", f"relative/bin:{real}:{tmp_path / 'missing'}::{real}")
    assert gazebo_search_path(os.environ) == (real,)


def test_unreadable_versions_are_skipped(tmp_path: Path) -> None:
    bin_dir = _bins(tmp_path, "gz", "ign", "gzserver")
    _, run = _recording_runner(
        {"gz": "I cannot find any available 'gz' command:\n", "ign": None, "gzserver": "junk"}
    )
    assert detect_families([bin_dir], run) == ()


# --- family_for -------------------------------------------------------------


def _families(tmp_path: Path, *names: str) -> tuple[Family, ...]:
    versions = {"classic": "11.15.1", "ignition": "6.16.0", "gz": "8.15.0"}
    return tuple(
        Family(name=n, version=versions[n], bin_dir=tmp_path, exe=tmp_path / n)  # type: ignore[arg-type]
        for n in names
    )


@pytest.mark.parametrize(
    ("text", "hint"),
    [
        ('<sdf version="1.11"><world name="w"/></sdf>', "gz"),
        ('<plugin filename="gz-sim-physics-system" name="gz::sim::systems::Physics"/>', "gz"),
        ('<plugin filename="libgz-sim8-physics-system.so"/>', "gz"),
        ('<plugin filename="ignition-gazebo-physics-system" />', "ignition"),
        ('<plugin filename="libignition-gazebo6-physics-system.so"/>', "ignition"),
        ('<plugin name="x" filename="libgazebo_ros_api_plugin.so"/>', "classic"),
        ('<plugin name="my_plugin" filename="libContactPlugin.so" />', "classic"),
        ('<sdf version="1.6"><world name="default"/></sdf>', None),
        ("not sdf at all", None),
    ],
)
def test_family_hint_from_sdf_version_and_plugins(text: str, hint: str | None) -> None:
    assert family_hint(text.encode()) == hint


# P8 defect E: plugin FILENAMES decide the family before namespaces. Fortress 6.16's own stock
# worlds load ``ignition-gazebo-*`` plugins but name them ``gz::sim::systems::*``.
_FORTRESS_STOCK = (
    '<sdf version="1.6"><world name="empty"><plugin\n'
    '      filename="ignition-gazebo-physics-system"\n'
    '      name="gz::sim::systems::Physics">\n    </plugin></world></sdf>'
)


def test_fortress_stock_world_with_gz_namespace_names_hints_ignition() -> None:
    assert family_hint(_FORTRESS_STOCK.encode()) == "ignition"


def test_harmonic_stock_world_hints_gz() -> None:
    text = (
        '<sdf version="1.6"><world name="empty"><plugin\n'
        '      filename="gz-sim-physics-system"\n'
        '      name="gz::sim::systems::Physics">\n    </plugin></world></sdf>'
    )
    assert family_hint(text.encode()) == "gz"


def test_garden_style_ignition_namespace_with_gz_filename_hints_gz() -> None:
    text = '<plugin filename="gz-sim-physics-system" name="ignition::gazebo::systems::Physics"/>'
    assert family_hint(text.encode()) == "gz"


def test_namespace_alone_still_hints_when_no_filename_decides() -> None:
    assert family_hint(b'<plugin name="ignition::gazebo::systems::Physics"/>') == "ignition"
    assert family_hint(b'<plugin name="gz::sim::systems::Physics"/>') == "gz"


def test_family_for_prefers_the_hinted_installed_family(tmp_path: Path) -> None:
    world = tmp_path / "w.sdf"
    world.write_text(
        '<sdf version="1.6"><plugin filename="libignition-gazebo6-physics-system.so"/></sdf>'
    )
    fams = _families(tmp_path, "classic", "ignition", "gz")
    chosen = family_for(world, fams)
    assert chosen is not None and chosen.name == "ignition"


def test_ambiguous_world_file_picks_newest_family_and_reports_it(tmp_path: Path) -> None:
    world = tmp_path / "plain.sdf"
    world.write_text('<sdf version="1.6">\n  <world name="default"/>\n</sdf>\n')
    fams = _families(tmp_path, "classic", "gz")
    assert family_hint(world.read_bytes()) is None  # what the server reports: no hint
    chosen = family_for(world, fams)
    assert chosen == newest(fams)
    assert chosen is not None and chosen.name == "gz"


def test_family_for_with_no_installed_family_or_unreadable_file(tmp_path: Path) -> None:
    assert family_for(tmp_path / "missing.sdf", ()) is None
    fams = _families(tmp_path, "classic")
    chosen = family_for(tmp_path / "missing.sdf", fams)
    assert chosen is not None and chosen.name == "classic"
    hinted_but_absent = tmp_path / "gz.sdf"
    hinted_but_absent.write_text('<sdf version="1.11"/>')
    chosen = family_for(hinted_but_absent, fams)
    assert chosen is not None and chosen.name == "classic"
