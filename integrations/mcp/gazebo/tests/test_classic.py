"""The classic (Gazebo 11) adapter against the classic11 fixture CLI: `gz model -i` polling
(classic has no joint-state topic and no `-j`, RECON §2), `gz world`/`gz joint` shapes,
`save_world` unsupported."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from integrations.mcp.gazebo.solus.adapters.adapter_base import (
    CliError,
    Completed,
    Unsupported,
    WorldPose,
    parse_text_format,
    run_argv,
)
from integrations.mcp.gazebo.solus.adapters.classic import ClassicAdapter, _angles
from integrations.mcp.gazebo.solus.family_detect import Family

PAUSED_PARTITION = "solus-fixture-paused"  # the fixture CLIs replay a paused world (replay_lib)
NONFINITE_PARTITION = "solus-fixture-nonfinite"  # classic11 prints angle: nan / inf

Harness = tuple[ClassicAdapter, list[list[str]], str]


@pytest.fixture
def classic(fixture_family: Callable[[str], Family]) -> Harness:
    calls: list[list[str]] = []

    def recording(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        return run_argv(argv, timeout)

    family = fixture_family("classic11")
    return ClassicAdapter(family, run=recording), calls, str(family.bin_dir / "gz")


def test_running_worlds_from_topic_prefixes(classic: Harness) -> None:
    adapter, calls, gz = classic
    assert adapter.running_worlds() == ["default"]
    assert calls == [[gz, "topic", "-l"]]


def test_scene_from_wrench_topics_and_model_info(classic: Harness) -> None:
    adapter, calls, gz = classic
    scene = adapter.scene("default")
    assert [m.name for m in scene.models] == ["twolink"]
    twolink = scene.models[0]
    assert twolink.links == ("base", "arm", "tip")
    assert [(j.name, j.type, j.parent_link, j.child_link) for j in twolink.joints] == [
        ("shoulder", "revolute", "base", "arm"),
        ("elbow", "revolute", "arm", "tip"),
    ]
    assert calls == [[gz, "topic", "-l"], [gz, "model", "-w", "default", "-m", "twolink", "-i"]]


def test_spawn_passes_pose_flags(classic: Harness, tmp_path: Path) -> None:
    adapter, calls, gz = classic
    model = tmp_path / "twolink.urdf"
    model.write_text("<robot/>")
    adapter.spawn("default", model, "twolink", WorldPose(xyz=(1.0, 0.0, 0.5), rpy=(0.0, 0.0, 0.5)))
    assert calls == [
        [
            gz,
            "model",
            "-w",
            "default",
            "-m",
            "twolink",
            "-f",
            str(model),
            "-x",
            "1.0",
            "-y",
            "0.0",
            "-z",
            "0.5",
            "-R",
            "0.0",
            "-P",
            "0.0",
            "-Y",
            "0.5",
        ],
        [gz, "model", "-w", "default", "-m", "twolink", "-i"],  # presence check (P8 defect B)
    ]


def test_spawn_fails_when_gz_model_prints_an_error_with_rc_0(
    classic: Harness, tmp_path: Path
) -> None:
    """P8 defect B: classic `gz model -f` exits 0 and reports a parse failure only as an
    `Error:` line on stderr; the fixture replays that for `-m broken` and `gz model -i` then
    answers "Unable to get info" (both recorded live, P8-T2 / P9-T3 2026-11-09)."""
    adapter, calls, gz = classic
    model = tmp_path / "broken.urdf"
    model.write_text("<robot/>")
    with pytest.raises(CliError) as excinfo:
        adapter.spawn("default", model, "broken", WorldPose())
    assert excinfo.value.reason == "gz model failed: Error: SDF parsing the xml failed"
    assert [c[:2] for c in calls] == [[gz, "model"]] and "-i" not in calls[0]


def test_spawn_fails_when_the_model_is_absent_after_a_silent_gz_model(
    fixture_family: Callable[[str], Family],
) -> None:
    """A silent rc-0 `gz model -f` is never trusted: spawn confirms presence with one
    `gz model -i` and fails when the model is not in the world."""
    replies = [
        Completed((), 0, "", ""),
        Completed((), 0, "Unable to get info on model[ghost] in the world[default]\n", ""),
    ]
    calls: list[list[str]] = []

    def scripted(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        return replies.pop(0)

    adapter = ClassicAdapter(fixture_family("classic11"), run=scripted)
    with pytest.raises(CliError, match="ghost is not in world default"):
        adapter.spawn("default", Path("/abs/ghost.urdf"), "ghost", WorldPose())
    assert calls[1][1:] == ["model", "-w", "default", "-m", "ghost", "-i"]


def test_set_targets_fails_when_gz_joint_prints_an_error(
    fixture_family: Callable[[str], Family],
) -> None:
    """Classic CLIs report failures as an `Error` line with rc 0; `gz joint` is held to the
    same rule (AUTHORED stderr: live `gz joint --pos-t` on an absent model is silent)."""
    replies = [Completed((), 0, "", "Error: something about joint [shoulder]\n")]

    def scripted(argv: list[str], timeout: float) -> Completed:
        return replies.pop(0)

    adapter = ClassicAdapter(fixture_family("classic11"), run=scripted)
    with pytest.raises(CliError) as excinfo:
        adapter.set_targets("default", "twolink", {"shoulder": 0.7, "elbow": -0.25})
    assert excinfo.value.reason == "gz joint failed: Error: something about joint [shoulder]"
    assert replies == []  # the loop stopped at the first failing joint


def test_classic_joint_state_polls_gz_model_j_with_a_10hz_ceiling(
    fixture_family: Callable[[str], Family],
) -> None:
    """Classic has no `-j`: the poll is `gz model -w <w> -m <m> -i` (RECON §2); the ceiling is
    10 Hz measured on an injected clock."""
    calls: list[list[str]] = []
    now = [100.0]
    sleeps: list[float] = []

    def recording(argv: list[str], timeout: float) -> Completed:
        calls.append(list(argv))
        now[0] += 0.02  # a poll costs 20 ms on this clock
        return run_argv(argv, timeout)

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    family = fixture_family("classic11")
    adapter = ClassicAdapter(family, run=recording, clock=clock, sleep=sleep)
    samples = adapter.joint_state("default", "twolink", None, 1.0)
    polls = [c for c in calls if c[1] == "model"]
    assert all(
        c == [str(family.bin_dir / "gz"), "model", "-w", "default", "-m", "twolink", "-i"]
        for c in polls
    )
    assert 2 <= len(polls) <= 11, len(polls)
    assert all(s >= 0.0 for s in sleeps) and sum(sleeps) + 0.02 * len(polls) >= 0.99
    assert calls[-1] == [
        str(family.bin_dir / "gz"),
        "topic",
        "-e",
        "/gazebo/default/world_stats",
        "-d",
        "1",
    ]
    shoulder = [s for s in samples if s.joint == "shoulder"]
    assert len(shoulder) == len(polls)
    assert shoulder[0].position == pytest.approx(1.5697520194514176)
    assert shoulder[0].velocity is None and shoulder[0].paused is False
    elbow = [s for s in samples if s.joint == "elbow"]
    assert elbow and elbow[0].position == pytest.approx(1.5464770391330855)
    one = adapter.joint_state("default", "twolink", ["elbow"], 0.0)
    assert [s.joint for s in one] == ["elbow"]


def test_joint_state_window_on_paused_world_returns_and_flags_paused(
    classic: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, _ = classic
    monkeypatch.setenv("GZ_PARTITION", PAUSED_PARTITION)
    started = time.monotonic()
    samples = adapter.joint_state("default", "twolink", ["shoulder"], 0.3)
    assert time.monotonic() - started < 0.3 + 2.0
    assert len(samples) >= 2 and all(s.paused is True for s in samples)
    assert len({s.position for s in samples}) == 1


def test_missing_model_is_a_cli_error(classic: Harness) -> None:
    adapter, _, _ = classic
    with pytest.raises(CliError) as excinfo:
        adapter.joint_state("default", "nope", None, 0.0)
    assert "nope" in str(excinfo.value)


def test_set_targets_uses_gz_joint_pos_t(classic: Harness) -> None:
    adapter, calls, gz = classic
    adapter.set_targets("default", "twolink", {"shoulder": 0.7, "elbow": -0.25})
    assert calls == [
        [gz, "joint", "-w", "default", "-m", "twolink", "-j", "shoulder", "--pos-t", "0.7"],
        [gz, "joint", "-w", "default", "-m", "twolink", "-j", "elbow", "--pos-t", "-0.25"],
    ]


@pytest.mark.parametrize(
    ("action", "kwargs", "tail"),
    [
        ("pause", {}, ["-p", "1"]),
        ("play", {}, ["-p", "0"]),
        ("step", {}, ["-s"]),
        ("step", {"steps": 3}, ["-m", "3"]),
        ("reset", {}, ["-r"]),
        ("reset", {"scope": "time"}, ["-t"]),
        ("reset", {"scope": "model_only"}, ["-o"]),
    ],
)
def test_control_argv_uses_gz_world_flags(
    classic: Harness, action: str, kwargs: dict[str, Any], tail: list[str]
) -> None:
    adapter, calls, gz = classic
    adapter.control("default", action, **kwargs)  # type: ignore[arg-type]
    assert calls == [[gz, "world", "-w", "default", *tail]]


def test_classic_save_world_is_unsupported_on_classic_11(classic: Harness, tmp_path: Path) -> None:
    adapter, calls, _ = classic
    with pytest.raises(Unsupported) as excinfo:
        adapter.save_world("default", tmp_path, "out.world")
    assert excinfo.value.wire()["code"] == "unsupported_on"
    assert (excinfo.value.family, excinfo.value.version) == ("classic", "11.15.1")
    assert excinfo.value.sentence.endswith(".") and excinfo.value.sentence.count(". ") == 0
    assert calls == [] and not (tmp_path / "out.world").exists()


def test_start_uses_gzserver_headless_and_gazebo_for_gui(
    classic: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter, _, gz = classic
    seen: dict[str, Any] = {}

    class FakePopen:
        def __init__(self, argv: list[str], **kwargs: Any) -> None:
            seen["argv"] = argv
            seen.update(kwargs)

    monkeypatch.setattr(subprocess, "Popen", FakePopen)
    monkeypatch.setenv("GAZEBO_MASTER_URI", "http://127.0.0.1:11345")
    world = tmp_path / "w.world"
    world.write_text("<sdf/>")
    bin_dir = Path(gz).parent
    adapter.start(world, gui=False)
    assert seen["argv"] == [str(bin_dir / "gzserver"), str(world)] and seen["start_new_session"]
    assert seen["env"]["GAZEBO_MASTER_URI"] == "http://127.0.0.1:11345"
    adapter.start(world, gui=True)
    assert seen["argv"] == [str(bin_dir / "gazebo"), str(world)]


def test_telemetry_argv_is_the_text_echo(classic: Harness) -> None:
    adapter, _, gz = classic
    assert adapter.telemetry_argv("/gazebo/default/world_stats") == [
        gz,
        "topic",
        "-e",
        "/gazebo/default/world_stats",
    ]


def test_unparseable_model_info_and_path_leaking_stderr_become_cli_errors(
    fixture_family: Callable[[str], Family],
) -> None:
    replies: list[Completed] = []

    def scripted(argv: list[str], timeout: float) -> Completed:
        return replies.pop(0)

    adapter = ClassicAdapter(fixture_family("classic11"), run=scripted)
    deep = 'name: "twolink"\n' + "a {" * 20 + "x: 1" + "}" * 20
    replies.append(Completed((), 0, deep, ""))
    with pytest.raises(CliError):
        adapter.joint_state("default", "twolink", None, 0.0)
    replies.append(Completed((), 0, 'name: "twolink" link { name: "a: \\x" }', ""))
    assert adapter._model("default", "twolink").links == ("a: \\x",)  # malformed escape kept
    replies.append(
        Completed((), 255, "", "Error: File [/home/u/.solus/sim/models/x/m.urdf] does not exist.\n")
    )
    with pytest.raises(CliError) as excinfo:
        adapter.spawn("default", Path("/abs/m.urdf"), "twolink", WorldPose())
    assert "/" not in excinfo.value.reason and "m.urdf" in excinfo.value.reason


def test_non_finite_angles_are_dropped_not_sampled(
    classic: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gz model -i` on diverged physics prints `angle: nan` / `angle: inf`; such joints yield no
    sample (a JointSample.position is always finite) and a model with none left is a CliError."""
    doc = parse_text_format(
        'joint { name: "m::a" angle: nan }\njoint { name: "m::b" angle: 0.5 }\n'
        'joint { name: "m::c" angle: inf }\njoint { name: "m::d" angle: -Infinity }\n'
    )
    assert _angles(doc, "m") == [("b", 0.5)]
    adapter, _, _ = classic
    monkeypatch.setenv("GZ_PARTITION", NONFINITE_PARTITION)
    with pytest.raises(CliError, match="twolink"):
        adapter.joint_state("default", "twolink", None, 0.0)
