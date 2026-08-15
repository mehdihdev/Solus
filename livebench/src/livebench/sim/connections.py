"""Sim `LiveConnection`s (LB-01): thin providers over `PacketStreamLiveConnection`.

The SimConnector lifecycle maps onto the MCP-02 seam: *start* is construction +
`subscribe` (the pump starts lazily), *stream* is windowed delivery via `on_batch`,
*stop* is `aclose` (clean teardown, pending window flushed, source closed). Signals
map to graph entities through `device_id == graph_entity.external_ref` — per-joint
topics from MuJoCo, gz topics from Gazebo, recorded topics from MCAP.
"""

from datetime import datetime
from pathlib import Path
from typing import ClassVar
from uuid import UUID

from livebench.sim.gazebo_source import GazeboTopicSource
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


class GazeboSimConnection(PacketStreamLiveConnection):
    """Gazebo topics → windowed telemetry, via the pinned `gz` CLI subprocess.

    Raises `GazeboNotAvailableError` at construction when the CLI is absent (unless
    a `source` is injected — the fixture/test path, and any future gz-transport
    binding)."""

    provider: ClassVar[str] = "gazebo"

    def __init__(
        self,
        topics: list[str] | None = None,
        *,
        source: PacketSource | None = None,
        project_id: UUID | None = None,
    ) -> None:
        if source is None:
            source = GazeboTopicSource(topics or [])
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
