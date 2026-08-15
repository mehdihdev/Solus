"""LB-01: sim LiveConnections — MuJoCo (real physics), MCAP replay, Gazebo (injected source)."""

import asyncio
import io
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from livebench.sim.connections import (
    GazeboSimConnection,
    McapReplaySimConnection,
    MuJoCoSimConnection,
)
from livebench.telemetry.mcap_export import write_packets
from solus_api.agent.interfaces import TelemetryWindow, TelemetryWindowSummary
from solus_api.connectors.live import LiveStatus
from solus_api.connectors.live_conformance import assert_live_connection_contract
from solus_api.graph.packet import TelemetryPacket

T0 = datetime(2026, 1, 1, tzinfo=UTC)

PENDULUM_XML = """
<mujoco model="pendulum">
  <option timestep="0.002" gravity="0 0 -9.81"/>
  <worldbody>
    <body name="arm" pos="0 0 1">
      <joint name="hinge" type="hinge" axis="0 1 0"/>
      <geom name="rod" type="capsule" fromto="0 0 0 0.5 0 0" size="0.02" mass="1"/>
    </body>
  </worldbody>
</mujoco>
"""


def test_providers() -> None:
    assert MuJoCoSimConnection.provider == "mujoco"
    assert GazeboSimConnection.provider == "gazebo"
    assert McapReplaySimConnection.provider == "mcap-replay"


async def test_mujoco_smoke_scene_streams_windows_through_the_contract() -> None:
    conn = MuJoCoSimConnection(
        PENDULUM_XML, scene_name="pendulum", start_time=T0, sample_hz=100.0, duration_seconds=30.0
    )
    received: list[TelemetryWindowSummary] = []

    async def collect(summary: TelemetryWindowSummary) -> None:
        received.append(summary)

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=0.05))
    conn.on_batch(handle, collect)
    for _ in range(2000):
        await asyncio.sleep(0)
        if len(received) >= 2:
            break
    await conn.aclose()

    assert len(received) >= 2
    stats = received[0].signals["qpos"]
    assert stats["count"] >= 1.0  # real physics samples landed in the window


async def test_mujoco_teardown_is_clean() -> None:
    conn = MuJoCoSimConnection(
        PENDULUM_XML, scene_name="pendulum", start_time=T0, sample_hz=100.0, duration_seconds=30.0
    )
    await conn.subscribe(TelemetryWindow(duration_seconds=0.05))
    await conn.aclose()
    assert conn.status() is LiveStatus.DISCONNECTED


async def test_mcap_replay_passes_the_conformance_suite(tmp_path: Path) -> None:
    packets = [
        TelemetryPacket(
            device_id="/joint/elbow",
            timestamp=T0 + timedelta(seconds=0.5 * i),
            values={"qpos": float(i)},
        )
        for i in range(6)  # spans 2.5s → crosses a 1s window boundary
    ]
    buf = io.BytesIO()
    write_packets(buf, packets)
    path = tmp_path / "run.mcap"
    path.write_bytes(buf.getvalue())

    conn = McapReplaySimConnection(path)

    async def emit() -> None:
        # Return as soon as delivery is observed: a finite replay legitimately drops
        # to DISCONNECTED once the file is exhausted, and the suite's STREAMING
        # assertion is about delivery, not about a file outliving the test.
        for _ in range(500):
            await asyncio.sleep(0)
            if conn.status() is LiveStatus.STREAMING:
                return

    try:
        await assert_live_connection_contract(
            conn, emit=emit, window=TelemetryWindow(duration_seconds=1.0)
        )
    finally:
        await conn.aclose()


async def test_gazebo_connection_with_injected_source(tmp_path: Path) -> None:
    # No gz binary on this machine: the connection accepts an injected source, so
    # the windowing/contract path is proven; the live subprocess smoke runs
    # post-install (documented in the completion report).
    class FakeGz:
        closed = False

        async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
            for i in range(4):
                yield TelemetryPacket(
                    device_id="/model/arm/joint",
                    timestamp=T0 + timedelta(seconds=0.4 * i),
                    values={"position": float(i)},
                )

        async def aclose(self) -> None:
            self.closed = True

    conn = GazeboSimConnection(source=FakeGz())
    received: list[TelemetryWindowSummary] = []

    async def collect(summary: TelemetryWindowSummary) -> None:
        received.append(summary)

    handle = await conn.subscribe(TelemetryWindow(duration_seconds=1.0))
    conn.on_batch(handle, collect)
    for _ in range(200):
        await asyncio.sleep(0)
        if received:
            break
    await conn.aclose()

    assert received
    assert received[0].signals["position"]["count"] >= 1.0
