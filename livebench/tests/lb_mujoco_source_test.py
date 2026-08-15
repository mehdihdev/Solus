"""LB-01: MuJoCo sim → LB-06 packets (physics stepped for real, sim-time stamps)."""

from datetime import UTC, datetime, timedelta

import pytest
from livebench.sim.mujoco_source import MuJoCoPacketSource
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
  <sensor>
    <jointpos name="hinge_pos" joint="hinge"/>
  </sensor>
</mujoco>
"""


async def collect(source: MuJoCoPacketSource) -> list[TelemetryPacket]:
    packets = []
    async for p in source:
        packets.append(p)
    return packets


async def test_streams_joint_and_sensor_packets() -> None:
    source = MuJoCoPacketSource(
        PENDULUM_XML, scene_name="pendulum", sample_hz=50.0, start_time=T0, duration_seconds=0.2
    )

    packets = await collect(source)

    devices = {p.device_id for p in packets}
    assert "pendulum/hinge" in devices
    assert "pendulum/hinge_pos" in devices
    joint = next(p for p in packets if p.device_id == "pendulum/hinge")
    assert set(joint.values) == {"qpos", "qvel"}
    sensor = next(p for p in packets if p.device_id == "pendulum/hinge_pos")
    assert set(sensor.values) == {"value"}


async def test_physics_actually_runs_gravity_swings_the_pendulum() -> None:
    source = MuJoCoPacketSource(
        PENDULUM_XML, scene_name="pendulum", sample_hz=50.0, start_time=T0, duration_seconds=0.5
    )

    packets = await collect(source)

    qpos = [p.values["qpos"] for p in packets if p.device_id == "pendulum/hinge"]
    assert qpos[0] == 0.0
    assert abs(qpos[-1]) > 1e-4  # a horizontal arm under gravity moves


async def test_timestamps_advance_in_sim_time() -> None:
    source = MuJoCoPacketSource(
        PENDULUM_XML, scene_name="pendulum", sample_hz=50.0, start_time=T0, duration_seconds=0.2
    )

    packets = await collect(source)

    joint_times = [p.timestamp for p in packets if p.device_id == "pendulum/hinge"]
    assert joint_times[0] == T0
    deltas = [(b - a).total_seconds() for a, b in zip(joint_times, joint_times[1:], strict=False)]
    assert deltas == pytest.approx([0.02] * len(deltas))  # 50 Hz sampling in sim time


async def test_duration_bounds_the_stream() -> None:
    source = MuJoCoPacketSource(
        PENDULUM_XML, scene_name="pendulum", sample_hz=50.0, start_time=T0, duration_seconds=0.2
    )

    packets = await collect(source)

    samples = len([p for p in packets if p.device_id == "pendulum/hinge"])
    assert 10 <= samples <= 11  # 0.2s at 50 Hz, inclusive first sample
    last = max(p.timestamp for p in packets)
    assert last <= T0 + timedelta(seconds=0.2)


async def test_aclose_stops_the_stream_early() -> None:
    source = MuJoCoPacketSource(
        PENDULUM_XML, scene_name="pendulum", sample_hz=50.0, start_time=T0, duration_seconds=60.0
    )
    packets = []

    async for p in source:
        packets.append(p)
        if len(packets) >= 4:
            await source.aclose()

    assert len(packets) <= 6  # stopped promptly, nowhere near 60s worth


def test_invalid_xml_raises_at_construction() -> None:
    with pytest.raises(ValueError):
        MuJoCoPacketSource("<not-mujoco/>", scene_name="x", start_time=T0)
