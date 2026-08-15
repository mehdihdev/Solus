"""`FoxgloveLiveConnection` — the Foxglove provider over `PacketStreamLiveConnection` (CON-03).

The generic machinery (pump, windowing, teardown flush, failure honesty) lives in
`stream_live.py`; this module contributes the Foxglove specifics: the ws client
wrapped as a `PacketSource` (frames normalized into LB-06 packets), and the
validated `for_url` constructor.
"""

from collections.abc import AsyncIterator
from typing import ClassVar
from urllib.parse import urlsplit
from uuid import UUID

from solus_api.graph.packet import TelemetryPacket

from livebench.telemetry.foxglove_client import FoxgloveClient
from livebench.telemetry.normalize import packet_from_json_payload
from livebench.telemetry.stream_live import PacketSource, PacketStreamLiveConnection

__all__ = ["FoxgloveLiveConnection", "PacketSource"]


class _ClientPacketSource:
    """Production source: Foxglove ws client frames, normalized into packets."""

    def __init__(self, client: FoxgloveClient) -> None:
        self._client = client

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        async for message in self._client.messages():
            packet = packet_from_json_payload(message.topic, message.log_time_ns, message.payload)
            if packet is not None:
                yield packet

    async def aclose(self) -> None:
        await self._client.close()


class FoxgloveLiveConnection(PacketStreamLiveConnection):
    """Live subscription surface over a Foxglove bridge (or any `PacketSource`)."""

    provider: ClassVar[str] = "foxglove"

    @classmethod
    def for_url(cls, url: str, *, project_id: UUID | None = None) -> "FoxgloveLiveConnection":
        """The production constructor: `ws://robot:8765` → live connection.

        `ws`/`wss` only, and no in-URL credentials — an authenticated bridge gets a
        `secret_ref` resolved through the secret store (W0-05 rule), never a URL param.
        """
        parts = urlsplit(url)
        if parts.scheme not in ("ws", "wss"):
            raise ValueError(f"unsupported scheme {parts.scheme!r}: only ws:// or wss://")
        if "@" in parts.netloc:
            raise ValueError("credentials in the URL are not allowed; use a secret_ref")
        return cls(source=_ClientPacketSource(FoxgloveClient(url)), project_id=project_id)
