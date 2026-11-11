"""The new-family (`gz sim`) adapter against the gz8 fixture CLI; every argv asserted exactly
against the shapes recorded from Harmonic 8.15.0 (RECON §3)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from integrations.mcp.gazebo.solus.adapters.adapter_base import (
    CliError,
    Completed,
    WorldPose,
    run_argv,
)
from integrations.mcp.gazebo.solus.adapters.gz import GzAdapter, _joint_samples_from_message
from integrations.mcp.gazebo.solus.family_detect import Family

PAUSED_PARTITION = "solus-fixture-paused"  # the fixture CLIs replay a paused world (replay_lib)


@pytest.fixture
def gz(fixture_family: Callable[[str], Family]) -> tuple[GzAdapter, list[list[str]], str]:
    calls: list[list[str]] = []

    def recording(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        return run_argv(argv, timeout)

    family = fixture_family("gz8")
    return GzAdapter(family, run=recording), calls, str(family.exe)


def test_running_worlds_from_service_list(gz: tuple[GzAdapter, list[list[str]], str]) -> None:
    adapter, calls, exe = gz
    assert adapter.running_worlds() == ["empty"]
    assert calls == [[exe, "service", "-l"]]


def test_scene_lists_models_links_and_joints(gz: tuple[GzAdapter, list[list[str]], str]) -> None:
    adapter, calls, exe = gz
    scene = adapter.scene("empty")
    assert scene.world == "empty"
    assert [m.name for m in scene.models] == ["ground_plane", "twolink"]
    twolink = scene.models[1]
    assert twolink.links == ("base", "arm", "tip")
    assert [(j.name, j.type, j.parent_link, j.child_link) for j in twolink.joints] == [
        ("shoulder", "revolute", "base", "arm"),
        ("elbow", "revolute", "arm", "tip"),
    ]
    assert scene.models[0].joints == ()
    assert calls[0] == [
        exe,
        "service",
        "-s",
        "/world/empty/scene/info",
        "--reqtype",
        "gz.msgs.Empty",
        "--reptype",
        "gz.msgs.Scene",
        "--timeout",
        "5000",
        "--req",
        "",
    ]
    assert calls[1:] == [
        [exe, "model", "-m", "ground_plane", "-j"],
        [exe, "model", "-m", "twolink", "-j"],
    ]


def test_spawn_argv_and_request_text(
    gz: tuple[GzAdapter, list[list[str]], str], tmp_path: Path
) -> None:
    adapter, calls, exe = gz
    model = tmp_path / "twolink.sdf"
    model.write_text("<sdf/>")
    adapter.spawn("empty", model, "twolink", WorldPose(xyz=(1.0, 0.0, 0.5), rpy=(0.0, 0.0, 0.5)))
    assert calls == [
        [
            exe,
            "service",
            "-s",
            "/world/empty/create",
            "--reqtype",
            "gz.msgs.EntityFactory",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            "5000",
            "--req",
            f'sdf_filename: "{model}" name: "twolink" pose {{ position {{ x: 1.0 y: 0.0 z: 0.5 }} '
            "orientation { x: 0.0 y: 0.0 z: 0.24740395925452294 w: 0.9689124217106447 } }",
        ]
    ]
    with pytest.raises(ValueError):
        adapter.spawn("empty", Path("relative.sdf"), "twolink", WorldPose())
    with pytest.raises(ValueError):
        adapter.spawn("empty", tmp_path / 'quo"te.sdf', "twolink", WorldPose())


def test_joint_state_window_uses_duration_then_stats(
    gz: tuple[GzAdapter, list[list[str]], str],
) -> None:
    adapter, calls, exe = gz
    samples = adapter.joint_state("empty", "twolink", None, 0.5)
    assert calls == [
        [
            exe,
            "topic",
            "-e",
            "-t",
            "/world/empty/model/twolink/joint_state",
            "--json-output",
            "-d",
            "0.5",
        ],
        [exe, "topic", "-e", "-t", "/world/empty/stats", "--json-output", "-d", "0.3"],
    ]
    assert {s.joint for s in samples} == {"shoulder", "elbow"}
    assert all(s.paused is False for s in samples)
    shoulder = [s for s in samples if s.joint == "shoulder"]
    assert shoulder[0].position == pytest.approx(0.91339023173050071)
    assert shoulder[0].velocity == pytest.approx(0.71177044306127879)
    assert shoulder[0].sim_time_s == pytest.approx(15.838)
    assert len(shoulder) >= 2 and shoulder[1].position != shoulder[0].position
    only = adapter.joint_state("empty", "twolink", ["elbow"], 0.0)
    assert {s.joint for s in only} == {"elbow"}
    assert calls[2][-2:] == ["-n", "1"]


def test_joint_state_window_on_paused_world_returns_and_flags_paused(
    gz: tuple[GzAdapter, list[list[str]], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, calls, _ = gz
    monkeypatch.setenv("GZ_PARTITION", PAUSED_PARTITION)
    started = time.monotonic()
    samples = adapter.joint_state("empty", "twolink", ["shoulder"], 0.5)
    assert time.monotonic() - started < 0.5 + 2.0
    assert len(samples) >= 2
    assert all(s.paused is True for s in samples)
    assert len({(s.position, s.sim_time_s) for s in samples}) == 1


def test_joint_state_without_publisher_is_a_cli_error_not_a_hang(
    gz: tuple[GzAdapter, list[list[str]], str],
) -> None:
    adapter, _, _ = gz
    started = time.monotonic()
    with pytest.raises(CliError) as excinfo:
        adapter.joint_state("empty", "nope", None, 0.3)
    assert time.monotonic() - started < 0.3 + 2.0
    assert "joint_state" in str(excinfo.value)


def test_set_targets_one_publish_per_joint(gz: tuple[GzAdapter, list[list[str]], str]) -> None:
    adapter, calls, exe = gz
    adapter.set_targets("empty", "twolink", {"shoulder": 0.7, "elbow": -0.25})
    assert calls == [
        [
            exe,
            "topic",
            "-t",
            "/model/twolink/joint/shoulder/0/cmd_pos",
            "-m",
            "gz.msgs.Double",
            "-p",
            "data: 0.7",
        ],
        [
            exe,
            "topic",
            "-t",
            "/model/twolink/joint/elbow/0/cmd_pos",
            "-m",
            "gz.msgs.Double",
            "-p",
            "data: -0.25",
        ],
    ]


@pytest.mark.parametrize(
    ("action", "kwargs", "req"),
    [
        ("pause", {}, "pause: true"),
        ("play", {}, "pause: false"),
        ("step", {"steps": 3}, "pause: true multi_step: 3"),
        ("reset", {}, "reset { all: true }"),
        ("reset", {"scope": "time"}, "reset { time_only: true }"),
        ("reset", {"scope": "model_only"}, "reset { model_only: true }"),
    ],
)
def test_control_argv_matches_the_recorded_world_control_requests(
    gz: tuple[GzAdapter, list[list[str]], str], action: str, kwargs: dict[str, Any], req: str
) -> None:
    adapter, calls, exe = gz
    adapter.control("empty", action, **kwargs)  # type: ignore[arg-type]
    assert calls == [
        [
            exe,
            "service",
            "-s",
            "/world/empty/control",
            "--reqtype",
            "gz.msgs.WorldControl",
            "--reptype",
            "gz.msgs.Boolean",
            "--timeout",
            "5000",
            "--req",
            req,
        ]
    ]


def test_control_refuses_unknown_action_scope_and_bad_steps(
    gz: tuple[GzAdapter, list[list[str]], str],
) -> None:
    adapter, calls, _ = gz
    with pytest.raises(ValueError):
        adapter.control("empty", "explode")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        adapter.control("empty", "reset", scope="everything")
    with pytest.raises(ValueError):
        adapter.control("empty", "step", steps=0)
    assert calls == []


def test_service_timeout_and_refused_request_raise_cli_error(
    gz: tuple[GzAdapter, list[list[str]], str],
) -> None:
    adapter, _, _ = gz
    with pytest.raises(CliError) as excinfo:
        adapter.control("nope", "pause")
    assert "timed out" in str(excinfo.value)


def test_save_world_writes_the_unescaped_sdf(
    gz: tuple[GzAdapter, list[list[str]], str], tmp_path: Path
) -> None:
    adapter, calls, exe = gz
    dest = tmp_path / "saved.sdf"
    dest.write_text("stale")  # the user's own world file is replaced in place
    adapter.save_world("empty", tmp_path, "saved.sdf")
    assert calls == [
        [
            exe,
            "service",
            "-s",
            "/world/empty/generate_world_sdf",
            "--reqtype",
            "gz.msgs.SdfGeneratorConfig",
            "--reptype",
            "gz.msgs.StringMsg",
            "--timeout",
            "5000",
            "--req",
            "",
        ]
    ]
    text = dest.read_text()
    assert text.startswith("<sdf version='1.10'>\n  <world name='empty'>") and text.endswith(
        "</sdf>\n"
    )
    assert "\\n" not in text


def test_start_is_argv_only_in_a_new_session_with_the_scrubbed_env(
    gz: tuple[GzAdapter, list[list[str]], str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, exe = gz
    seen: dict[str, Any] = {}

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            seen["argv"] = argv
            seen.update(kwargs)
            self.pid = 4242

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setenv("GZ_CONFIG_PATH", "/opt/gz/share")
    monkeypatch.setenv("SOLUS_SECRET_TOKEN", "never")
    world = tmp_path / "w.sdf"
    world.write_text("<sdf/>")
    adapter.home = tmp_path / "home"
    process = adapter.start(world, gui=False)
    assert process.pid == 4242
    assert seen["argv"] == [exe, "sim", "-s", "-r", str(world)]
    assert seen["start_new_session"] is True
    assert seen["env"]["GZ_CONFIG_PATH"] == "/opt/gz/share"
    assert seen["env"]["HOME"] == str(tmp_path / "home") and (tmp_path / "home").is_dir()
    assert "SOLUS_SECRET_TOKEN" not in seen["env"] and "shell" not in seen
    assert seen["stdin"] == subprocess.DEVNULL
    adapter.start(world, gui=True)
    assert seen["argv"] == [exe, "sim", "-r", str(world)]
    with pytest.raises(ValueError):
        adapter.start(Path("relative.sdf"), gui=False)


def test_telemetry_argv_is_the_json_echo(gz: tuple[GzAdapter, list[list[str]], str]) -> None:
    adapter, _, exe = gz
    assert adapter.telemetry_argv("/world/empty/model/twolink/joint_state") == [
        exe,
        "topic",
        "-e",
        "-t",
        "/world/empty/model/twolink/joint_state",
        "--json-output",
    ]
    for bad in ("world/empty", "/a b", "", "-t", "/x\ny"):
        with pytest.raises(ValueError):
            adapter.telemetry_argv(bad)


def test_save_world_is_confined_to_the_root(
    gz: tuple[GzAdapter, list[list[str]], str], tmp_path: Path
) -> None:
    adapter, calls, _ = gz
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "root"
    root.mkdir()
    os.symlink(outside, root / "dir")
    os.symlink(outside / "leaf.sdf", root / "leaf.sdf")
    for rel in ("dir/w.sdf", "leaf.sdf"):
        with pytest.raises(ValueError):
            adapter.save_world("empty", root, rel)
    assert not (outside / "w.sdf").exists() and not (outside / "leaf.sdf").exists()
    assert len(calls) == 2  # well-formed names are refused at the fd walk, after the service
    for rel in ("../w.sdf", "/abs/w.sdf", "-w.sdf", "a/../w.sdf"):
        with pytest.raises(ValueError):
            adapter.save_world("empty", root, rel)
    assert len(calls) == 2  # a hostile-shaped dest never reaches the server
    assert sorted(p.name for p in root.iterdir()) == ["dir", "leaf.sdf"]


def test_cli_failures_redact_paths_and_unparseable_replies_are_cli_errors(
    fixture_family: Callable[[str], Family],
) -> None:
    replies: list[Completed] = []

    def scripted(argv: list[str], timeout: float) -> Completed:
        return replies.pop(0)

    adapter = GzAdapter(fixture_family("gz8"), run=scripted)
    replies.append(
        Completed((), 255, "", "Error: File [/home/u/.solus/sim/models/x/m.sdf] does not exist.\n")
    )
    with pytest.raises(CliError) as excinfo:
        adapter.control("empty", "pause")
    assert "/" not in excinfo.value.reason and "m.sdf" in excinfo.value.reason
    replies.append(Completed((), 0, "a {" * 20 + "x: 1" + "}" * 20, ""))
    with pytest.raises(CliError):
        adapter.control("empty", "pause")
    replies.append(Completed((), 0, 'data: "\\x\\u12\\"', ""))
    with pytest.raises(CliError):  # malformed escapes parse (to a non-true), never raise
        adapter.control("empty", "pause")


def test_non_finite_json_joint_values_are_dropped_or_none() -> None:
    """`--json-output` prints NaN/Infinity for diverged physics (json.loads accepts them); a
    non-finite position drops the sample, a non-finite velocity becomes None."""
    message = json.loads(
        '{"joint":[{"name":"a","axis1":{"position":NaN,"velocity":0.1}},'
        '{"name":"b","axis1":{"position":0.2,"velocity":Infinity}},'
        '{"name":"c","axis1":{"position":1e999,"velocity":-Infinity}}]}'
    )
    samples = _joint_samples_from_message(message, None, False)
    assert [(s.joint, s.position, s.velocity) for s in samples] == [("b", 0.2, None)]
