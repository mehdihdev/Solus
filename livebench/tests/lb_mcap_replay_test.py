"""LB-01: MCAP replay source — Isaac Sim's log container replayed as a packet stream."""

import io
from datetime import UTC, datetime, timedelta
from pathlib import Path

from livebench.sim.mcap_replay import McapReplaySource
from livebench.telemetry.mcap_export import write_packets
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def sample_file(tmp_path: Path) -> Path:
    packets = [
        TelemetryPacket(
            device_id=f"/joint/{name}",
            timestamp=T0 + timedelta(seconds=i * 0.1),
            values={"qpos": float(i)},
        )
        for i, name in enumerate(["elbow", "elbow", "wrist"])
    ]
    buf = io.BytesIO()
    write_packets(buf, packets)
    path = tmp_path / "isaac_run.mcap"
    path.write_bytes(buf.getvalue())
    return path


async def test_replays_all_packets_in_order(tmp_path: Path) -> None:
    source = McapReplaySource(sample_file(tmp_path))

    packets = [p async for p in source]

    assert [p.device_id for p in packets] == ["/joint/elbow", "/joint/elbow", "/joint/wrist"]
    assert [p.values["qpos"] for p in packets] == [0.0, 1.0, 2.0]


async def test_topic_filter(tmp_path: Path) -> None:
    source = McapReplaySource(sample_file(tmp_path), topics=["/joint/wrist"])

    packets = [p async for p in source]

    assert [p.device_id for p in packets] == ["/joint/wrist"]


async def test_aclose_mid_stream_stops_and_releases_the_file(tmp_path: Path) -> None:
    source = McapReplaySource(sample_file(tmp_path))
    seen = []

    async for p in source:
        seen.append(p)
        await source.aclose()

    assert len(seen) == 1
