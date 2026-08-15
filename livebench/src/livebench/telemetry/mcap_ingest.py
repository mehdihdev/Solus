"""MCAP → LB-06 packets (CON-03 ingest, file/recorded side).

Reads an MCAP stream (a `foxglove_bridge` recording, an Isaac Sim log, a rosbag2
MCAP export) and yields `TelemetryPacket`s for every message on a **json-encoded**
channel. Other encodings (protobuf/cdr/flatbuffer) are skipped — decoding them
means shipping their schema toolchains, which is exactly the dependency weight the
LB-06 contract rejected; the json path is what `foxglove_bridge` and rosbag2's
json converters already speak.

Per-message failures are dropped, never raised: one malformed message must not end
a file that carries millions (CLAUDE.md §7). A structurally hostile FILE, by
contrast, fails loudly and early:

* non-seekable streams are refused — the mcap library's non-seeking reader loads
  the ENTIRE file into memory to sort by log time (buffer to disk first);
* input size is capped (`max_bytes`) before any record is read;
* individual records are capped via the reader's `record_size_limit`.

Known ceiling, stated plainly: the mcap library decompresses chunks to a size the
CHUNK HEADER declares (zstd) or with no cap at all (lz4), so a crafted file can
amplify well past its on-disk size — measured 32,000:1 in review. The size cap
bounds the input, not the amplification; ingest of untrusted files must therefore
run inside a memory-capped worker (ARQ), never in the request path.
"""

import logging
import os
from collections.abc import Collection, Iterator
from typing import IO, Final

from mcap.reader import SeekingReader
from solus_api.graph.packet import TelemetryPacket

from livebench.telemetry.normalize import packet_from_json_payload

logger = logging.getLogger(__name__)

#: Refuse inputs larger than this before reading a single record.
MAX_MCAP_BYTES: Final = 512 * 1024 * 1024

#: One record (message/chunk/schema) may not exceed this.
MAX_RECORD_BYTES: Final = 64 * 1024 * 1024


def read_packets(
    stream: IO[bytes],
    *,
    topics: Collection[str] | None = None,
    max_bytes: int = MAX_MCAP_BYTES,
) -> Iterator[TelemetryPacket]:
    """Yield packets from `stream` in log-time order, json channels only.

    `topics`, when given, restricts reading to those topic names (pushed down into
    the MCAP reader, so filtered channels are never even decoded).
    """
    if not stream.seekable():
        raise ValueError("MCAP ingest requires a seekable stream — buffer to disk first")
    start = stream.tell()
    stream.seek(0, os.SEEK_END)
    size = stream.tell() - start
    stream.seek(start)
    if size > max_bytes:
        raise ValueError(f"MCAP input of {size} bytes exceeds the {max_bytes}-byte cap")

    reader = SeekingReader(stream, record_size_limit=MAX_RECORD_BYTES)
    wanted = list(topics) if topics is not None else None
    for _schema, channel, message in reader.iter_messages(topics=wanted, log_time_order=True):
        if channel.message_encoding != "json":
            continue
        packet = packet_from_json_payload(channel.topic, message.log_time, message.data)
        if packet is None:
            logger.debug("skipping undecodable message on %.64r", channel.topic)
            continue
        yield packet
