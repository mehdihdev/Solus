"""LB-06 packets → Foxglove-consumable MCAP (CON-03 viz-out).

The complementary direction: anything Solus holds as packets (a replay, a sim run,
a buffered window's raw source) can be handed to Foxglove Studio or any MCAP tool.
One json-encoded channel per `device_id`, payloads in the ratified LB-06 wire form
(`ts_us` et al.), `log_time` mirroring the packet timestamp — so an export read
back through `read_packets` reproduces the packets exactly (round-trip tested).
"""

from collections.abc import Iterable
from typing import IO

from mcap.writer import Writer
from solus_api.graph.codec import encode_json, to_wire
from solus_api.graph.packet import TelemetryPacket

#: Wire timestamps are microseconds; MCAP log times are nanoseconds.
_NS_PER_US = 1_000

#: One channel per device; an input with more distinct devices than this is not a
#: telemetry export, it's an attack or a bug — fail loudly, never truncate silently.
MAX_EXPORT_CHANNELS = 4096


def write_packets(stream: IO[bytes], packets: Iterable[TelemetryPacket]) -> int:
    """Write `packets` as an MCAP file to `stream`; returns the message count."""
    writer = Writer(stream)
    writer.start()
    channels: dict[str, int] = {}
    written = 0
    try:
        for packet in packets:
            channel_id = channels.get(packet.device_id)
            if channel_id is None:
                if len(channels) >= MAX_EXPORT_CHANNELS:
                    raise ValueError(f"more than {MAX_EXPORT_CHANNELS} distinct devices in export")
                schema_id = writer.register_schema(
                    name="solus.TelemetryPacket", encoding="jsonschema", data=b"{}"
                )
                channel_id = writer.register_channel(
                    topic=packet.device_id, message_encoding="json", schema_id=schema_id
                )
                channels[packet.device_id] = channel_id
            log_time = int(to_wire(packet)["ts_us"]) * _NS_PER_US
            writer.add_message(
                channel_id=channel_id,
                log_time=log_time,
                publish_time=log_time,
                data=encode_json(packet).encode(),
            )
            written += 1
    finally:
        writer.finish()
    return written
