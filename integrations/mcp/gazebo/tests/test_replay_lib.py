"""The fixture CLIs replay the recorded shapes the adapters depend on (and nothing else)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


def _run(
    exe: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(exe), *args], capture_output=True, text=True, timeout=10, check=False, env=env
    )


@pytest.mark.parametrize(
    ("family", "exe", "sub", "msgs", "version"),
    [
        ("gz8", "gz", "sim", "gz.msgs", "8.15.0"),
        ("ign6", "ign", "gazebo", "ignition.msgs", "6.16.0"),
    ],
)
def test_replay_cli_versions_services_and_unhandled_argv(
    fixture_bins: Path, family: str, exe: str, sub: str, msgs: str, version: str
) -> None:
    cli = fixture_bins / family / exe
    assert _run(cli, sub, "--versions").stdout.strip() == version
    assert "/world/empty/control" in _run(cli, "service", "-l").stdout
    idle = dict(os.environ, GZ_PARTITION="solus-fixture-idle")
    assert "/world/" not in _run(cli, "service", "-l", env=idle).stdout
    assert "/world/" not in _run(cli, "topic", "-l", env=idle).stdout
    svc = _run(
        cli,
        "service",
        "-s",
        "/world/empty/control",
        "--reqtype",
        f"{msgs}.WorldControl",
        "--reptype",
        f"{msgs}.Boolean",
        "--timeout",
        "5000",
        "--req",
        "pause: true",
    )
    assert svc.stdout.startswith("data: true")
    wrong_type = _run(
        cli,
        "service",
        "-s",
        "/world/empty/control",
        "--reqtype",
        "other.msgs.WorldControl",
        "--reptype",
        f"{msgs}.Boolean",
        "--timeout",
        "5000",
        "--req",
        "pause: true",
    )
    assert wrong_type.returncode == 255
    unhandled = _run(cli, "frobnicate")
    assert unhandled.returncode == 255
    assert json.loads(unhandled.stdout)["unhandled_fixture_argv"] == ["frobnicate"]


def test_replay_paused_knob_freezes_stats_and_joint_state(fixture_bins: Path) -> None:
    cli = fixture_bins / "gz8" / "gz"
    env = dict(os.environ, GZ_PARTITION="solus-fixture-paused")
    stats = _run(
        cli, "topic", "-e", "-t", "/world/empty/stats", "--json-output", "-n", "1", env=env
    )
    assert json.loads(stats.stdout)["paused"] is True
    joint_args = ("topic", "-e", "-t", "/world/empty/model/twolink/joint_state", "--json-output")
    lines = _run(cli, *joint_args, "-d", "0.5", env=env).stdout.splitlines()
    assert len(lines) >= 2 and len(set(lines)) == 1
    running = _run(cli, *joint_args, "-d", "0.5").stdout.splitlines()
    assert len(set(running)) > 1
    assert (
        "paused"
        not in _run(
            cli, "topic", "-e", "-t", "/world/empty/stats", "--json-output", "-n", "1"
        ).stdout
    )


def test_classic_replay_shapes(fixture_bins: Path) -> None:
    cli = fixture_bins / "classic11" / "gz"
    assert "/gazebo/default/world_stats" in _run(cli, "topic", "-l").stdout
    idle = _run(cli, "topic", "-l", env=dict(os.environ, GZ_PARTITION="solus-fixture-idle"))
    assert "/gazebo/default/" not in idle.stdout and idle.returncode == 0
    info = _run(cli, "model", "-w", "default", "-m", "twolink", "-i").stdout
    assert 'name: "twolink::shoulder"' in info and "angle:" in info
    assert "Unable to get info" in _run(cli, "model", "-w", "default", "-m", "nope", "-i").stdout
    paused = _run(
        cli,
        "topic",
        "-e",
        "/gazebo/default/world_stats",
        "-d",
        "1",
        env=dict(os.environ, GZ_PARTITION="solus-fixture-paused"),
    ).stdout
    assert "paused: true" in paused
    # Recorded live (P8-T2): classic `-d` takes whole seconds; a fraction is "Invalid arguments"
    # on stderr with exit 0 and nothing on stdout.
    fraction = _run(cli, "topic", "-e", "/gazebo/default/world_stats", "-d", "0.3")
    assert (fraction.returncode, fraction.stdout) == (0, "")
    assert fraction.stderr == "Invalid arguments\n"
    assert _run(cli, "--version").returncode == 255
