"""WS packet source (LB-02): a robot's own WebSocket pushing LB-06 frames.

The wifi/direct transport for robots that speak the contract natively: binary
frames are msgpack LB-06 (the throughput form), text frames are the JSON debug
form. Anything that fails the codec is dropped, never raised — the decoders are
the ratified trust boundary and surface exactly one error type each.

Direct-link identity: the frame's own `device_id` is the claim (one link, one
robot). URL rules match `FoxgloveLiveConnection.for_url`: ws/wss only, and
credentials never ride the URL — an authenticated robot gets a `secret_ref`.
"""

import logging
from collections.abc import AsyncIterator
from typing import Final
from urllib.parse import urlsplit

import websockets
from solus_api.graph.codec import MAX_PACKET_BYTES, PacketDecodeError, decode, decode_json
from solus_api.graph.packet import TelemetryPacket

logger = logging.getLogger(__name__)

#: One frame is one packet; the codec's own cap plus framing slack.
MAX_FRAME_BYTES: Final = MAX_PACKET_BYTES + 1024


class WsPacketSource:
    """LB-06 frames from a robot's WebSocket, as an async packet stream."""

    def __init__(self, url: str, *, max_frame_bytes: int = MAX_FRAME_BYTES) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("ws", "wss"):
            raise ValueError(f"unsupported scheme {parts.scheme!r}: only ws:// or wss://")
        if "@" in parts.netloc:
            raise ValueError("credentials in the URL are not allowed; use a secret_ref")
        self._url = url
        self._max_frame = max_frame_bytes
        self._ws: websockets.ClientConnection | None = None
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        if self._closed:
            raise RuntimeError("source is closed")
        self._ws = await websockets.connect(self._url, max_size=self._max_frame)
        try:
            async for frame in self._ws:
                try:
                    packet = decode(frame) if isinstance(frame, bytes) else decode_json(frame)
                except PacketDecodeError:
                    logger.debug("dropping undecodable ws frame")
                    continue
                yield packet
        except websockets.ConnectionClosed:
            logger.debug("robot ws link closed")
        finally:
            await self.aclose()

    async def aclose(self) -> None:
        self._closed = True
        if self._ws is not None:
            await self._ws.close()
