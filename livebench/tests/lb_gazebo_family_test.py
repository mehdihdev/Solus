"""SOLUSDEV-322 P3-T5: the livebench sources find their Gazebo binary ONLY through
`SOLUS_GAZEBO_PATH` (never the ambient PATH) and derive the joint_state topic per family."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest
from livebench.sim.gazebo_family import (
    GazeboNotAvailableError,
    detect_family,
    family_on_disk,
    find_exe,
    gazebo_bin_dirs,
    joint_state_topic,
    probe_stdout,
    simulator_env,
)

FIXTURE_BINS = Path(__file__).resolve().parent / "fixtures" / "bin"
GZ8, IGN6, CLASSIC11 = FIXTURE_BINS / "gz8", FIXTURE_BINS / "ign6", FIXTURE_BINS / "classic11"


def _bins(*dirs: Path) -> dict[str, str]:
    return {"SOLUS_GAZEBO_PATH": os.pathsep.join(str(d) for d in dirs)}


def test_sources_resolve_exe_from_solus_gazebo_path_never_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    fake = ambient / "gz"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{ambient}:/usr/bin:/bin")
    monkeypatch.delenv("SOLUS_GAZEBO_PATH", raising=False)

    assert gazebo_bin_dirs() == ()
    with pytest.raises(GazeboNotAvailableError):
        find_exe("gz")
    assert detect_family() is None

    # Relative, missing and duplicate entries are dropped; only absolute existing dirs count.
    env = {"SOLUS_GAZEBO_PATH": f"relative/bin:{tmp_path / 'missing'}:{GZ8}:{GZ8}"}
    assert gazebo_bin_dirs(env) == (GZ8,)
    assert find_exe("gz", env=env) == GZ8 / "gz"


def test_find_exe_tells_classic_gz_from_the_new_gz() -> None:
    # Both families ship a `gz`; classic is the one with `gzserver` beside it.
    both = _bins(CLASSIC11, GZ8)
    assert find_exe("classic", env=both) == CLASSIC11 / "gz"
    assert find_exe("gz", env=both) == GZ8 / "gz"
    assert find_exe("ignition", env=_bins(IGN6)) == IGN6 / "ign"
    with pytest.raises(GazeboNotAvailableError):
        find_exe("classic", env=_bins(GZ8))
    with pytest.raises(GazeboNotAvailableError):
        find_exe("ignition", env=_bins(GZ8, CLASSIC11))


def test_detect_family_prefers_the_newest_installed() -> None:
    assert detect_family(env=_bins(CLASSIC11, IGN6, GZ8)) == "gz"
    assert detect_family(env=_bins(CLASSIC11, IGN6)) == "ignition"
    assert detect_family(env=_bins(CLASSIC11)) == "classic"  # banner on stdout, exit 255


def test_family_on_disk_is_file_only_and_newest_first() -> None:
    assert family_on_disk(env=_bins(CLASSIC11, IGN6, GZ8)) == "gz"
    assert family_on_disk(env=_bins(CLASSIC11, IGN6)) == "ignition"
    assert family_on_disk(env=_bins(CLASSIC11)) == "classic"  # `gz` beside `gzserver`
    assert family_on_disk(env={}) is None


def test_family_on_disk_ignores_tool_shims_beside_classic(tmp_path: Path) -> None:
    # A conda classic 11 env drops an `ign` tool shim next to `gzserver` (this host's
    # solus-gz-classic does); it is still classic, not Fortress.
    for name in ("gz", "gzserver", "ign", "gazebo"):
        exe = tmp_path / name
        exe.write_text("#!/bin/sh\n")
        exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    assert family_on_disk(env=_bins(tmp_path)) == "classic"


def test_joint_state_topic_per_family() -> None:
    assert joint_state_topic("gz", "empty", "twolink") == "/world/empty/model/twolink/joint_state"
    assert joint_state_topic("ignition", "w", "m") == "/world/w/model/m/joint_state"
    assert joint_state_topic("classic", "default", "twolink") is None  # polled, not published
    with pytest.raises(ValueError):
        joint_state_topic("gz", "-w", "m")
    with pytest.raises(ValueError):
        joint_state_topic("gz", "w", "a b")


ENV_DUMP = [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"]


def test_simulator_env_forwards_only_the_simulator_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SOLUS_DATABASE_URL", "postgresql://planted")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "planted-key")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "planted-stripe")
    monkeypatch.setenv("GZ_PARTITION", "bench")
    monkeypatch.setenv("IGN_PARTITION", "bench6")
    monkeypatch.setenv("GAZEBO_MASTER_URI", "http://localhost:11345")
    monkeypatch.setenv("SOLUS_GAZEBO_PATH", str(GZ8))

    scrubbed = simulator_env()
    child = json.loads(probe_stdout(ENV_DUMP, 5.0) or "{}")  # what the probe child really sees

    for env in (scrubbed, child):
        assert env["GZ_PARTITION"] == "bench" and env["IGN_PARTITION"] == "bench6"
        assert env["GAZEBO_MASTER_URI"] == "http://localhost:11345"
        assert env["SOLUS_GAZEBO_PATH"] == str(GZ8) and "PATH" in env
        assert not {"SOLUS_DATABASE_URL", "ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY"} & set(env)
    assert set(child) <= set(scrubbed)
    assert simulator_env({"REDIS_URL": "redis://x", "LD_LIBRARY_PATH": "/opt/lib"}) == {
        "LD_LIBRARY_PATH": "/opt/lib"
    }
