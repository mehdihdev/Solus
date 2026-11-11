"""SOLUSDEV-322 P3-T5: classic Gazebo 11 streams protobuf text format from `gz topic -e <topic>`
(numeric leaves flattened, bounded) and polls joint angles through `gz model -w -m -i` at ≤ 10 Hz
because classic publishes no joint_state topic (plan §1.1 item 8)."""

import asyncio
import math
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from livebench.sim import classic_source, gazebo_source
from livebench.sim.classic_source import (
    MAX_TEXT_DEPTH,
    MAX_TEXT_FORMAT_BYTES,
    POLL_HZ_CEILING,
    ClassicTopicSource,
    packets_from_text_blocks,
    text_blocks,
    text_format_document,
)
from livebench.sim.gazebo_family import find_exe, simulator_env

T0 = datetime(2026, 1, 1, tzinfo=UTC)
CLASSIC11 = Path(__file__).resolve().parent / "fixtures" / "bin" / "classic11"
STATS_TOPIC = "/gazebo/default/world_stats"
# Recorded from Classic 11.15.1 on 2026-11-09 (fixtures/bin/classic11/gz).
STATS_BLOCK = """goo.gle/debugonly
sim_time {
  sec: 7
  nsec: 458000000
}
real_time {
  sec: 7
  nsec: 464878991
}
paused: false
name: "default"
iterations: 7458
"""


def clock() -> datetime:
    return T0


async def blocks(*items: str) -> AsyncIterator[str]:
    for item in items:
        yield item


async def lines(*items: bytes) -> AsyncIterator[bytes]:
    for item in items:
        yield item


async def test_classic_text_format_flattens_numeric_leaves_only() -> None:
    nested = 'a { b: 1.5 c: "text" d: true e { f: -2 } } g: 3 h { } h { i: 1 }'

    packets = [
        p async for p in packets_from_text_blocks("/t", blocks(nested, STATS_BLOCK), clock=clock)
    ]

    # strings and booleans are not measurements; a repeated field (h) is a list and is skipped
    assert packets[0].values == {"a.b": 1.5, "a.e.f": -2.0, "g": 3.0}
    assert packets[0].device_id == "/t" and packets[0].timestamp == T0
    assert packets[1].values == {
        "sim_time.sec": 7.0,
        "sim_time.nsec": 458000000.0,
        "real_time.sec": 7.0,
        "real_time.nsec": 464878991.0,
        "iterations": 7458.0,
    }


def test_text_format_document_keeps_repeated_fields_and_strings() -> None:
    doc = text_format_document('joint { name: "m::a" angle: 1 } joint { name: "m::b" angle: nan }')

    # nan != nan, so the document is compared piecewise rather than as one literal
    assert list(doc) == ["joint"] and len(doc["joint"]) == 2
    assert doc["joint"][0] == {"name": "m::a", "angle": 1}
    assert doc["joint"][1]["name"] == "m::b" and math.isnan(doc["joint"][1]["angle"])


async def test_text_format_is_bounded_in_depth_and_size() -> None:
    too_deep = "a { " * (MAX_TEXT_DEPTH + 1) + "x: 1" + " }" * (MAX_TEXT_DEPTH + 1)
    too_big = "x: 1\n" * (MAX_TEXT_FORMAT_BYTES // 5 + 1)
    with pytest.raises(ValueError):
        text_format_document(too_deep)
    with pytest.raises(ValueError):
        text_format_document(too_big)

    packets = [
        p
        async for p in packets_from_text_blocks(
            "/t", blocks(too_deep, too_big, "ok: 2"), clock=clock
        )
    ]

    assert [p.values for p in packets] == [{"ok": 2.0}]  # hostile blocks drop themselves


async def test_text_blocks_split_on_blank_lines() -> None:
    reader = lines(b"a: 1\n", b"b {\n", b"  c: 2\n", b"}\n", b"\n", b"\n", b"d: 3\n")

    assert [b async for b in text_blocks(reader)] == ["a: 1\nb {\n  c: 2\n}", "d: 3"]


async def test_text_blocks_never_buffer_past_the_bound_without_a_blank_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flushed: list[int] = []
    real_flush = classic_source._flush_block

    def spy(buffer: list[bytes]) -> str:
        flushed.append(len(b"".join(buffer)))
        return real_flush(buffer)

    monkeypatch.setattr(classic_source, "_flush_block", spy)
    endless = [b"a: 1\n"] * (MAX_TEXT_FORMAT_BYTES // 5 * 3)  # ~3x the bound, no separator

    blocks_seen = [
        b async for b in text_blocks(lines(*endless, b"\n", b"ok: 2\n", b"\n", *endless))
    ]

    assert blocks_seen == ["ok: 2"]  # the hostile block drops itself, the stream lives on
    assert max(flushed) <= MAX_TEXT_FORMAT_BYTES


def test_classic_argv_shapes_and_refusals() -> None:
    exe = CLASSIC11 / "gz"
    source = ClassicTopicSource(
        [STATS_TOPIC], exe=exe, world="default", model="twolink", poll_hz=50.0
    )

    assert source.argv(STATS_TOPIC) == [str(exe), "topic", "-e", STATS_TOPIC]
    assert source.poll_argv() == [str(exe), "model", "-w", "default", "-m", "twolink", "-i"]
    assert source.poll_hz == POLL_HZ_CEILING  # 10 Hz ceiling, whatever was asked
    assert ClassicTopicSource([], exe=exe, world="w", model="m").poll_argv()[-1] == "-i"
    with pytest.raises(ValueError):
        ClassicTopicSource([], exe=exe)  # nothing to stream
    with pytest.raises(ValueError):
        ClassicTopicSource(["-rf"], exe=exe)
    with pytest.raises(ValueError):
        ClassicTopicSource([], exe=exe, world="-w", model="m")
    with pytest.raises(ValueError):
        ClassicTopicSource([], exe=exe, world="w", model="a b")


async def test_classic_live_topic_echo_against_the_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    exe = find_exe("classic", env={"SOLUS_GAZEBO_PATH": str(CLASSIC11)})

    packets = [p async for p in ClassicTopicSource([STATS_TOPIC], exe=exe)]

    assert [p.device_id for p in packets] == [STATS_TOPIC, STATS_TOPIC]
    assert [p.values["sim_time.sec"] for p in packets] == [7.0, 8.0]
    assert "paused" not in packets[0].values


async def test_classic_joint_poll_emits_per_joint_packets_at_the_ceiling() -> None:
    source = ClassicTopicSource([], exe=CLASSIC11 / "gz", world="default", model="twolink")
    packets = []
    async for packet in source:
        packets.append(packet)
        if len(packets) == 4:  # two polls × two joints, then stop the poll loop
            break

    assert {p.device_id for p in packets} == {"default/twolink/shoulder", "default/twolink/elbow"}
    shoulder = next(p for p in packets if p.device_id.endswith("/shoulder"))
    assert shoulder.values == {
        "shoulder.position": 1.5697520194514176
    }  # `twolink::` scope stripped
    assert shoulder.units == {"shoulder.position": "rad"}
    assert source.poll_hz == 10.0


def _fixture_chunk_delay(monkeypatch: pytest.MonkeyPatch, seconds: str) -> None:
    """The scrubbed child env forwards no SOLUS_FIXTURE_* knob, so it rides along explicitly."""
    monkeypatch.setattr(
        gazebo_source,
        "simulator_env",
        lambda: {**simulator_env(), "SOLUS_FIXTURE_CHUNK_DELAY_S": seconds},
    )


async def test_classic_joint_poll_reads_a_chunked_model_dump_to_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # `gz model -i` writes through block-buffered stdio: the dump arrives in several pipe chunks,
    # so one StreamReader.read() returns a truncated document. The fixture replays that shape.
    _fixture_chunk_delay(monkeypatch, "0.02")
    source = ClassicTopicSource([], exe=CLASSIC11 / "gz", world="default", model="twolink")

    doc = await source._poll_once()

    assert [j["name"] for j in doc["joint"]] == ["twolink::shoulder", "twolink::elbow"]
    assert doc["joint"][1]["angle"] == 1.5464770391330855  # the joint past the first chunk
    assert doc["self_collide"] is False  # the tail of the dump made it too
    assert source._procs == []


async def test_classic_joint_poll_survives_aclose_while_a_poll_is_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fixture_chunk_delay(monkeypatch, "0.2")
    source = ClassicTopicSource([], exe=CLASSIC11 / "gz", world="default", model="twolink")
    poll = asyncio.create_task(source._poll_once())
    await asyncio.sleep(0.1)  # the child is spawned and mid-read

    await source.aclose()  # terminates the child and clears _procs under the poll's feet

    assert await poll == {}  # no ValueError from a double remove, no dead proc kept
    assert source._procs == []
