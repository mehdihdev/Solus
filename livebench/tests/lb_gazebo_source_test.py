"""LB-01 / SOLUSDEV-322 P3-T5: Gazebo topic echo (JSON lines) → LB-06 packets. A `joint_state`
topic splits into one packet per joint (`<world>/<model>/<joint>`, rad / rad/s); the binary comes
from `SOLUS_GAZEBO_PATH` only; the live subprocess path runs against the recorded fixture CLI."""

import asyncio
import json
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from livebench.sim.gazebo_family import GazeboNotAvailableError, find_exe
from livebench.sim.gazebo_source import (
    GazeboTopicSource,
    packets_from_json_lines,
    stdout_lines,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)
GZ8 = Path(__file__).resolve().parent / "fixtures" / "bin" / "gz8"
JOINT_TOPIC = "/world/empty/model/twolink/joint_state"
# Recorded from Harmonic gz 8.15.0 on 2026-11-09 (see fixtures/bin/gz_replay.py).
JOINT_LINE = (
    b'{"header":{"stamp":{"sec":"15","nsec":838000000}},"name":"twolink","id":10,'
    b'"joint":[{"name":"shoulder","id":20,"axis1":{"xyz":{"y":1},"limitLower":-1.57,'
    b'"limitUpper":1.57,"position":0.91339023173050071,"velocity":0.71177044306127879}},'
    b'{"name":"elbow","id":21,"axis1":{"xyz":{"y":1},"position":0.013115564070374449,'
    b'"velocity":0.12584293534387486}}]}'
)


async def lines(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


def clock() -> datetime:
    return T0


async def test_json_lines_become_packets_with_topic_as_device() -> None:
    reader = lines(b'{"position": 1.5, "velocity": -0.2}', b'{"position": 1.6}')

    packets = [p async for p in packets_from_json_lines("/model/arm/joint", reader, clock=clock)]

    assert len(packets) == 2
    assert packets[0].device_id == "/model/arm/joint"
    assert packets[0].values == {"position": 1.5, "velocity": -0.2}
    assert packets[0].timestamp == T0


async def test_malformed_and_non_numeric_lines_are_skipped() -> None:
    reader = lines(b"{broken", b'{"state": "ok"}', b'{"v": 2.0}', b"")

    packets = [p async for p in packets_from_json_lines("/t", reader, clock=clock)]

    assert [p.values for p in packets] == [{"v": 2.0}]


async def test_nested_gz_messages_flatten() -> None:
    reader = lines(b'{"pose": {"position": {"x": 1.0, "z": 3.0}}}')

    packets = [p async for p in packets_from_json_lines("/pose", reader, clock=clock)]

    assert packets[0].values == {"pose.position.x": 1.0, "pose.position.z": 3.0}


async def test_joint_state_message_splits_into_one_packet_per_joint() -> None:
    packets = [
        p async for p in packets_from_json_lines(JOINT_TOPIC, lines(JOINT_LINE), clock=clock)
    ]

    assert [p.device_id for p in packets] == ["empty/twolink/shoulder", "empty/twolink/elbow"]
    shoulder = packets[0]
    assert shoulder.values == {
        "shoulder.position": 0.91339023173050071,
        "shoulder.velocity": 0.71177044306127879,
    }
    assert shoulder.units == {"shoulder.position": "rad", "shoulder.velocity": "rad/s"}
    assert shoulder.timestamp == T0
    assert packets[1].values["elbow.position"] == pytest.approx(0.013115564070374449)


async def test_joint_state_drops_non_finite_and_hostile_joints() -> None:
    line = (
        b'{"joint":[{"name":"ok","axis1":{"position":0.5,"velocity":"fast"}},'
        b'{"name":"nan","axis1":{"position":NaN}},{"name":42,"axis1":{"position":1}},'
        b'{"name":"' + b"x" * 300 + b'","axis1":{"position":1}},"not-a-joint"]}'
    )

    packets = [p async for p in packets_from_json_lines(JOINT_TOPIC, lines(line), clock=clock)]

    assert len(packets) == 1
    assert packets[0].device_id == "empty/twolink/ok"
    assert packets[0].values == {"ok.position": 0.5}  # a non-numeric velocity is not a signal
    assert packets[0].units == {"ok.position": "rad"}


def test_source_refuses_flag_shaped_topics_and_requires_one() -> None:
    with pytest.raises(ValueError):
        GazeboTopicSource([], exe=GZ8 / "gz")
    with pytest.raises(ValueError):
        GazeboTopicSource(["-rf"], exe=GZ8 / "gz")
    assert GazeboTopicSource(["/t"], exe=GZ8 / "gz").argv("/t") == [
        str(GZ8 / "gz"), "topic", "-e", "-t", "/t", "--json-output",
    ]  # fmt: skip


async def test_live_fixture_echo_streams_per_joint_packets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")  # the fixture is reached by SOLUS_GAZEBO_PATH only
    exe = find_exe("gz", env={"SOLUS_GAZEBO_PATH": str(GZ8)})
    with pytest.raises(GazeboNotAvailableError):
        find_exe("gz", env={})

    packets = [p async for p in GazeboTopicSource([JOINT_TOPIC], exe=exe)]

    assert len(packets) == 6  # three recorded messages × two joints
    assert {p.device_id for p in packets} == {"empty/twolink/shoulder", "empty/twolink/elbow"}
    assert all(
        p.units["shoulder.velocity"] == "rad/s" for p in packets if "shoulder" in p.device_id
    )


async def test_an_overlong_stdout_line_drops_itself_not_the_stream() -> None:
    # 200 000 bytes is past asyncio's 64 KiB StreamReader limit (readline() would raise ValueError
    # and end the topic) and past MAX_PACKET_BYTES, so the line can never be a packet anyway.
    child = (
        "import sys; w = sys.stdout.write; w('x' * 200000 + '\\n'); "
        "w('{\"v\": 2.0}\\n'); w('y' * 70000); w('\\n{\"v\": 3.0}\\n'); w('{\"v\": 4.0}')"
    )
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", child, stdout=asyncio.subprocess.PIPE
    )

    packets = [p async for p in packets_from_json_lines("/t", stdout_lines(proc), clock=clock)]
    await proc.wait()

    assert [p.values for p in packets] == [{"v": 2.0}, {"v": 3.0}, {"v": 4.0}]


async def test_topic_child_never_sees_planted_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOLUS_DATABASE_URL", "postgresql://planted")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "planted-key")
    monkeypatch.setenv("GZ_PARTITION", "bench")
    source = GazeboTopicSource(["/t"], exe=GZ8 / "gz")

    proc = await source._spawn(
        [sys.executable, "-c", "import json, os; print(json.dumps(dict(os.environ)))"]
    )
    assert proc.stdout is not None
    child = json.loads(await proc.stdout.read())
    await source.aclose()

    assert child["GZ_PARTITION"] == "bench" and "PATH" in child
    assert not {"SOLUS_DATABASE_URL", "ANTHROPIC_API_KEY"} & set(child)
