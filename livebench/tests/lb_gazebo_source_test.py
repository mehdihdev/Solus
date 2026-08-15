"""LB-01: Gazebo topic echo (JSON lines) → LB-06 packets; binary-missing degrades loudly."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from livebench.sim.gazebo_source import (
    GazeboNotAvailableError,
    GazeboTopicSource,
    packets_from_json_lines,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


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


def test_missing_gz_binary_raises_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("livebench.sim.gazebo_source.shutil.which", lambda _: None)

    with pytest.raises(GazeboNotAvailableError):
        GazeboTopicSource(["/some/topic"])
