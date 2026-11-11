"""The ignition (Fortress) adapter: the gz shapes under `ign`, `ignition.msgs.*`, and
`--timeout` on every service call (RECON §2). Fixture stdouts are authored, see ign6/ign."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from integrations.mcp.gazebo.solus.adapters.adapter_base import Completed, WorldPose, run_argv
from integrations.mcp.gazebo.solus.adapters.gz import GzAdapter
from integrations.mcp.gazebo.solus.adapters.ignition import IgnitionAdapter
from integrations.mcp.gazebo.solus.family_detect import Family


@pytest.fixture
def ign(fixture_family: Callable[[str], Family]) -> tuple[IgnitionAdapter, list[list[str]], str]:
    calls: list[list[str]] = []

    def recording(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        return run_argv(argv, timeout)

    family = fixture_family("ign6")
    return IgnitionAdapter(family, run=recording), calls, str(family.exe)


def test_ignition_is_the_gz_adapter_with_ignition_names(
    ign: tuple[IgnitionAdapter, list[list[str]], str],
) -> None:
    adapter, _, _ = ign
    assert isinstance(adapter, GzAdapter)
    assert adapter.family.name == "ignition" and adapter.family.distro == "Fortress"


def test_running_worlds_and_scene(ign: tuple[IgnitionAdapter, list[list[str]], str]) -> None:
    adapter, calls, exe = ign
    assert adapter.running_worlds() == ["empty"]
    scene = adapter.scene("empty")
    assert [m.name for m in scene.models] == ["ground_plane", "twolink"]
    assert [j.name for j in scene.models[1].joints] == ["shoulder", "elbow"]
    assert calls[1] == [
        exe,
        "service",
        "-s",
        "/world/empty/scene/info",
        "--reqtype",
        "ignition.msgs.Empty",
        "--reptype",
        "ignition.msgs.Scene",
        "--timeout",
        "5000",
        "--req",
        "",
    ]


def test_every_service_call_carries_timeout(
    ign: tuple[IgnitionAdapter, list[list[str]], str], tmp_path: Path
) -> None:
    adapter, calls, exe = ign
    model = tmp_path / "m.sdf"
    model.write_text("<sdf/>")
    adapter.control("empty", "pause")
    adapter.control("empty", "step", steps=2)
    adapter.spawn("empty", model, "twolink", WorldPose())
    adapter.save_world("empty", tmp_path, "out.sdf")
    for argv in calls:
        assert argv[1] == "service" and argv[argv.index("--timeout") + 1] == "5000", argv
        assert argv[argv.index("--reqtype") + 1].startswith("ignition.msgs."), argv
    assert calls[0] == [
        exe,
        "service",
        "-s",
        "/world/empty/control",
        "--reqtype",
        "ignition.msgs.WorldControl",
        "--reptype",
        "ignition.msgs.Boolean",
        "--timeout",
        "5000",
        "--req",
        "pause: true",
    ]
    assert calls[2][calls[2].index("--reqtype") + 1] == "ignition.msgs.EntityFactory"
    assert calls[3][calls[3].index("--reptype") + 1] == "ignition.msgs.StringMsg"


def test_joint_state_and_targets_under_ign(
    ign: tuple[IgnitionAdapter, list[list[str]], str],
) -> None:
    adapter, calls, exe = ign
    samples = adapter.joint_state("empty", "twolink", ["shoulder"], 0.0)
    assert samples and samples[0].joint == "shoulder" and samples[0].paused is False
    assert calls[0] == [
        exe,
        "topic",
        "-e",
        "-t",
        "/world/empty/model/twolink/joint_state",
        "--json-output",
        "-n",
        "1",
    ]
    adapter.set_targets("empty", "twolink", {"elbow": 0.25})
    assert calls[-1] == [
        exe,
        "topic",
        "-t",
        "/model/twolink/joint/elbow/0/cmd_pos",
        "-m",
        "ignition.msgs.Double",
        "-p",
        "data: 0.25",
    ]


def test_start_uses_ign_gazebo(
    ign: tuple[IgnitionAdapter, list[list[str]], str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter, _, exe = ign
    seen: dict[str, Any] = {}

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            seen["argv"] = argv
            seen.update(kwargs)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    world = tmp_path / "w.sdf"
    world.write_text("<sdf/>")
    adapter.start(world, gui=False)
    assert seen["argv"] == [exe, "gazebo", "-s", "-r", str(world)] and seen["start_new_session"]
    assert adapter.telemetry_argv("/world/empty/stats") == [
        exe,
        "topic",
        "-e",
        "-t",
        "/world/empty/stats",
        "--json-output",
    ]
