"""MCAP replay → LB-06 packets (LB-01, the Isaac Sim path).

Isaac Sim logs to MCAP — the same container CON-03 already reads — so its telemetry
enters Solus by replaying the log, not through a bespoke transport. This wraps
`read_packets` as an async `PacketSource` so a recorded run flows through the exact
windowing/LiveConnection machinery a live stream would.

The live-Isaac decision (native Python API vs ROS 2 bridge) is taken when Isaac Sim
is actually installed on this machine; nothing here forecloses either.
"""

import asyncio
from collections.abc import AsyncIterator, Collection
from pathlib import Path

from solus_api.graph.packet import TelemetryPacket

from livebench.telemetry.mcap_ingest import read_packets


class McapReplaySource:
    """Replays one MCAP file as a packet stream; the file handle is always released."""

    def __init__(self, path: Path, *, topics: Collection[str] | None = None) -> None:
        self._path = Path(path)
        self._topics = list(topics) if topics is not None else None
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        with self._path.open("rb") as stream:
            for packet in read_packets(stream, topics=self._topics):
                if self._closed:
                    return
                yield packet
                await asyncio.sleep(0)  # cooperative: a big file must not starve the loop

    async def aclose(self) -> None:
        self._closed = True
