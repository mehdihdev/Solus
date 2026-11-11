"""Sim `LiveConnection`s (LB-01): thin providers over `PacketStreamLiveConnection`.

The SimConnector lifecycle maps onto the MCP-02 seam: *start* is construction +
`subscribe` (the pump starts lazily), *stream* is windowed delivery via `on_batch`,
*stop* is `aclose` (clean teardown, pending window flushed, source closed). Signals
map to graph entities through `device_id == graph_entity.external_ref` — per-joint
topics from MuJoCo, gz topics from Gazebo, recorded topics from MCAP.
"""

from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from livebench.sim.classic_source import ClassicTopicSource
from livebench.sim.gazebo_family import (
    FamilyName,
    GazeboNotAvailableError,
    detect_family,
    find_exe,
    joint_state_topic,
)
from livebench.sim.gazebo_source import GazeboTopicSource
from livebench.sim.ignition_source import IgnitionTopicSource
from livebench.sim.mcap_replay import McapReplaySource
from livebench.sim.mujoco_source import MuJoCoPacketSource
from livebench.telemetry.stream_live import PacketSource, PacketStreamLiveConnection


class MuJoCoSimConnection(PacketStreamLiveConnection):
    """MuJoCo scene → windowed telemetry. Steps real physics in sim time."""

    provider: ClassVar[str] = "mujoco"

    def __init__(
        self,
        xml: str,
        *,
        scene_name: str,
        start_time: datetime,
        sample_hz: float = 50.0,
        duration_seconds: float | None = None,
        realtime: bool = False,
        project_id: UUID | None = None,
    ) -> None:
        source = MuJoCoPacketSource(
            xml,
            scene_name=scene_name,
            start_time=start_time,
            sample_hz=sample_hz,
            duration_seconds=duration_seconds,
            realtime=realtime,
        )
        super().__init__(source=source, project_id=project_id)


def make_source(
    topics: list[str],
    *,
    family: FamilyName | None = None,
    world: str | None = None,
    model: str | None = None,
    env: Mapping[str, str] | None = None,
) -> GazeboTopicSource:
    """The family's topic source over the binary `SOLUS_GAZEBO_PATH` holds (SOLUSDEV-322 P3-T5).
    `family=None` takes the newest installed one; `world` + `model` add that model's joint_state
    stream (a 10 Hz `gz model -i` poll on classic, which has no such topic)."""
    if family is None:
        family = detect_family(env=env)
        if family is None:
            raise GazeboNotAvailableError("no Gazebo family found under SOLUS_GAZEBO_PATH")
    exe = find_exe(family, env=env)
    if (world is None) != (model is None):
        raise ValueError("world and model go together")
    if family == "classic":
        return ClassicTopicSource(topics, exe=exe, world=world, model=model)
    if world is not None and model is not None:
        joint_topic = joint_state_topic(family, world, model)
        if joint_topic is not None and joint_topic not in topics:
            topics = [*topics, joint_topic]
    cls = IgnitionTopicSource if family == "ignition" else GazeboTopicSource
    return cls(topics, exe=exe)


class GazeboSimConnection(PacketStreamLiveConnection):
    """Gazebo topics → windowed telemetry, via the family's pinned CLI subprocess.

    Raises `GazeboNotAvailableError` at construction when no binary of the family is under
    `SOLUS_GAZEBO_PATH` (unless a `source` is injected — the fixture/test path, and any future
    gz-transport binding)."""

    provider: ClassVar[str] = "gazebo"

    def __init__(
        self,
        topics: list[str] | None = None,
        *,
        source: PacketSource | None = None,
        project_id: UUID | None = None,
        family: FamilyName | None = None,
        world: str | None = None,
        model: str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        if source is None:
            source = make_source(topics or [], family=family, world=world, model=model, env=env)
        super().__init__(source=source, project_id=project_id)


class McapReplaySimConnection(PacketStreamLiveConnection):
    """MCAP recording (Isaac Sim's log container) → windowed telemetry replay."""

    provider: ClassVar[str] = "mcap-replay"

    def __init__(
        self,
        path: Path,
        *,
        topics: list[str] | None = None,
        project_id: UUID | None = None,
    ) -> None:
        super().__init__(source=McapReplaySource(path, topics=topics), project_id=project_id)
