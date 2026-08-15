"""MuJoCo sim → LB-06 packets (LB-01).

Steps a MuJoCo model and emits, at `sample_hz` in SIM time, one packet per joint
(`<scene>/<joint>` carrying `qpos`/`qvel`) and one per sensor (`<scene>/<sensor>`
carrying `value`). Timestamps are `start_time + sim_time`, so a run is fully
deterministic and replays identically — no wall clock in the loop unless
`realtime=True` asks for pacing.

Per-joint topics (not one giant device) is deliberate: `device_id` resolves against
`graph_entity.external_ref`, and the graph's entities from CAD/URDF are per part —
one topic per joint is what LNK-06 can actually attach.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import mujoco
from solus_api.graph.packet import TelemetryPacket


class MuJoCoPacketSource:
    """Async packet stream over a stepped MuJoCo model. One instance = one run."""

    def __init__(
        self,
        xml: str,
        *,
        scene_name: str,
        start_time: datetime,
        sample_hz: float = 50.0,
        duration_seconds: float | None = None,
        realtime: bool = False,
    ) -> None:
        if sample_hz <= 0:
            raise ValueError("sample_hz must be positive")
        try:
            self._model = mujoco.MjModel.from_xml_string(xml)
        except Exception as exc:
            raise ValueError(f"invalid MuJoCo model XML: {exc}") from exc
        self._data = mujoco.MjData(self._model)
        self._scene = scene_name
        self._start = start_time
        self._period = 1.0 / sample_hz
        self._duration = duration_seconds
        self._realtime = realtime
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        next_sample = 0.0
        while not self._closed:
            sim_time = float(self._data.time)
            if self._duration is not None and sim_time > self._duration:
                return
            if sim_time + 1e-12 >= next_sample:
                stamp = self._start + timedelta(seconds=sim_time)
                for packet in self._sample(stamp):
                    yield packet
                next_sample += self._period
                if self._realtime:
                    await asyncio.sleep(self._period)
                else:
                    await asyncio.sleep(0)  # cooperative: never starve the loop
            mujoco.mj_step(self._model, self._data)

    def _sample(self, stamp: datetime) -> list[TelemetryPacket]:
        packets: list[TelemetryPacket] = []
        for joint_id in range(self._model.njnt):
            name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_JOINT, joint_id)
            if not name:
                continue
            qpos_adr = self._model.jnt_qposadr[joint_id]
            qvel_adr = self._model.jnt_dofadr[joint_id]
            packets.append(
                TelemetryPacket(
                    device_id=f"{self._scene}/{name}",
                    timestamp=stamp,
                    values={
                        "qpos": float(self._data.qpos[qpos_adr]),
                        "qvel": float(self._data.qvel[qvel_adr]),
                    },
                )
            )
        for sensor_id in range(self._model.nsensor):
            name = mujoco.mj_id2name(self._model, mujoco.mjtObj.mjOBJ_SENSOR, sensor_id)
            if not name:
                continue
            adr = self._model.sensor_adr[sensor_id]
            packets.append(
                TelemetryPacket(
                    device_id=f"{self._scene}/{name}",
                    timestamp=stamp,
                    values={"value": float(self._data.sensordata[adr])},
                )
            )
        return packets

    async def aclose(self) -> None:
        """Stop the stream; the model is released with the object."""
        self._closed = True
