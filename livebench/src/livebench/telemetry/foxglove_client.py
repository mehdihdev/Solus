"""Subscribe-only Foxglove WebSocket protocol client (CON-03 live side).

Speaks the `foxglove.websocket.v1` subprotocol that `foxglove_bridge` serves
(`ws://robot:8765`): read `advertise`, subscribe to every **json-encoded** channel,
and surface each binary MESSAGE_DATA frame as `(topic, log_time_ns, payload)`.
Built directly on the already-installed `websockets` — a one-direction subscriber
does not need the vendor SDK.

This is a Pattern-2 streaming subscription and a trust boundary: frames arrive
from a robot nobody controls. Frame size is capped at the transport, channel
state is capped (`MAX_CHANNELS`) so an advertise flood cannot grow memory, control
messages are parsed under the same catch-everything rule as the LB-06 codec
(deep nesting raises `RecursionError`, which is not a `ValueError`), and nothing
in a frame can make this client send anything but its own `subscribe` messages.
"""

import json
import logging
import struct
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Final, NamedTuple

import websockets
from solus_api.graph.packet import MAX_DEVICE_ID_LEN

logger = logging.getLogger(__name__)

SUBPROTOCOL: Final = "foxglove.websocket.v1"

#: Binary opcode for a server→client message-data frame, per the ws-protocol spec.
_OPCODE_MESSAGE_DATA: Final = 0x01
#: opcode (1) + subscription id (uint32 LE) + receive timestamp ns (uint64 LE)
_MESSAGE_HEADER: Final = struct.Struct("<IQ")
_HEADER_LEN: Final = 1 + _MESSAGE_HEADER.size

_MAX_CHANNEL_ID: Final = 2**32 - 1  # channel ids ride a uint32 on the wire

#: Total channels this client will ever track — a hostile bridge advertising
#: endless synthetic channels must hit a ceiling, not the process's memory.
MAX_CHANNELS: Final = 4096

#: One data frame is one message (the LB-06 packet cap is 64 KiB); the headroom is
#: for one legitimate control frame — a full advertise of MAX_CHANNELS channels at
#: ~100 bytes each. 8x the packet cap, not unbounded.
MAX_FRAME_BYTES: Final = 512 * 1024


@dataclass(frozen=True)
class ChannelInfo:
    """One advertised server channel."""

    id: int
    topic: str
    encoding: str
    schema_name: str


class FoxgloveMessage(NamedTuple):
    """One data message: enough to normalize into an LB-06 packet."""

    topic: str
    log_time_ns: int
    payload: bytes


def _channel_from_entry(entry: object) -> ChannelInfo | None:
    if not isinstance(entry, dict):
        return None
    channel_id, topic, encoding = entry.get("id"), entry.get("topic"), entry.get("encoding")
    if not isinstance(channel_id, int) or isinstance(channel_id, bool):
        return None
    if not 0 <= channel_id <= _MAX_CHANNEL_ID:
        return None
    if not isinstance(topic, str) or not 0 < len(topic) <= MAX_DEVICE_ID_LEN:
        return None
    if encoding != "json":
        return None
    schema_name = entry.get("schemaName")
    return ChannelInfo(
        id=channel_id,
        topic=topic,
        encoding=encoding,
        schema_name=schema_name if isinstance(schema_name, str) else "",
    )


def parse_advertise(msg: Mapping[str, object]) -> list[ChannelInfo]:
    """`advertise` op → the json-encoded channels (the only ones this client reads),
    bounds-checked and capped at `MAX_CHANNELS`."""
    channels: list[ChannelInfo] = []
    raw = msg.get("channels")
    if not isinstance(raw, list):
        return channels
    for entry in raw:
        channel = _channel_from_entry(entry)
        if channel is None:
            continue
        channels.append(channel)
        if len(channels) >= MAX_CHANNELS:
            logger.warning("advertise capped at %d channels", MAX_CHANNELS)
            break
    return channels


def build_subscribe(
    channels: list[ChannelInfo], start_id: int = 0
) -> tuple[str, dict[int, ChannelInfo]]:
    """The client's one outbound message: subscribe to `channels`, ids from `start_id`."""
    by_sub_id = {start_id + offset: channel for offset, channel in enumerate(channels)}
    text = json.dumps(
        {
            "op": "subscribe",
            "subscriptions": [
                {"id": sub_id, "channelId": channel.id} for sub_id, channel in by_sub_id.items()
            ],
        }
    )
    return text, by_sub_id


def parse_message_data(
    frame: bytes, subscriptions: Mapping[int, ChannelInfo]
) -> FoxgloveMessage | None:
    """Binary frame → message, or ``None`` for anything that is not a well-formed
    MESSAGE_DATA on a known subscription (unknown opcodes are other protocol features)."""
    if len(frame) < _HEADER_LEN or frame[0] != _OPCODE_MESSAGE_DATA:
        return None
    sub_id, log_time_ns = _MESSAGE_HEADER.unpack_from(frame, 1)
    channel = subscriptions.get(sub_id)
    if channel is None:
        logger.debug("message on unknown subscription id %d", sub_id)
        return None
    return FoxgloveMessage(
        topic=channel.topic, log_time_ns=log_time_ns, payload=frame[_HEADER_LEN:]
    )


class FoxgloveClient:
    """Connects, subscribes to json channels, and yields data messages until closed."""

    def __init__(self, url: str, *, max_frame_bytes: int | None = MAX_FRAME_BYTES) -> None:
        self._url = url
        self._max_frame_bytes = max_frame_bytes
        self._ws: websockets.ClientConnection | None = None
        self._closed = False

    async def messages(self) -> AsyncIterator[FoxgloveMessage]:
        """Connect (lazily) and yield messages; ends when the link drops or `close` runs."""
        if self._closed:
            raise RuntimeError("client is closed")
        self._ws = await websockets.connect(
            self._url,
            subprotocols=[websockets.Subprotocol(SUBPROTOCOL)],
            max_size=self._max_frame_bytes,
        )
        subscriptions: dict[int, ChannelInfo] = {}
        subscribed_channel_ids: set[int] = set()
        next_sub_id = 0
        try:
            async for frame in self._ws:
                if isinstance(frame, bytes):
                    message = parse_message_data(frame, subscriptions)
                    if message is not None:
                        yield message
                    continue
                try:
                    control = json.loads(frame)
                except Exception:  # RecursionError et al. — same breadth as the codec
                    logger.debug("ignoring malformed control message")
                    continue
                if not isinstance(control, dict) or control.get("op") != "advertise":
                    continue  # serverInfo, unadvertise, future ops: nothing for a reader
                budget = MAX_CHANNELS - len(subscriptions)
                new = [c for c in parse_advertise(control) if c.id not in subscribed_channel_ids][
                    :budget
                ]
                if not new:
                    if budget == 0:
                        logger.warning("channel cap %d reached; ignoring advertise", MAX_CHANNELS)
                    continue
                text, by_sub_id = build_subscribe(new, start_id=next_sub_id)
                next_sub_id += len(new)
                subscriptions.update(by_sub_id)
                subscribed_channel_ids.update(c.id for c in new)
                await self._ws.send(text)
        except websockets.ConnectionClosed:
            logger.debug("foxglove link closed")
        finally:
            await self.close()

    async def close(self) -> None:
        """Idempotent teardown; a suspended `messages()` iterator ends after this."""
        self._closed = True
        if self._ws is not None:
            await self._ws.close()
