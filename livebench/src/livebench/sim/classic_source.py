"""Classic Gazebo 11 telemetry (SOLUSDEV-322 P3-T5).

Classic has no `--json-output`: `gz topic -e <topic>` prints each message as protobuf text format
(`a { b: 1.5 }`), one blank line between messages. The flattener keeps numeric leaves only
(`a.b = 1.5`; strings, booleans and repeated fields are not measurements) and is bounded: depth
16, 64 KiB per message — a hostile block drops itself, never the stream.

Classic publishes no joint_state topic either (plan §1.1 item 8), so with a `world` and `model`
the source polls `gz model -w <w> -m <m> -i` (gazebo.msgs.Model text format, joint `angle`) and
emits one `<world>/<model>/<joint>` packet per joint, `<joint>.position` in rad — velocity is not
reported by classic. The poll runs at ≤ 10 Hz.
"""

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Final

from solus_api.graph.packet import TelemetryPacket

from livebench.sim.gazebo_family import FamilyName, identifier_or_raise
from livebench.sim.gazebo_source import (
    GazeboTopicSource,
    joint_packet,
    log_time_ns,
    stdout_lines,
    utc_now,
)
from livebench.telemetry.normalize import packet_from_json_payload

logger = logging.getLogger(__name__)

MAX_TEXT_FORMAT_BYTES: Final = 64 * 1024
MAX_TEXT_DEPTH: Final = 16
POLL_HZ_CEILING: Final = 10.0  # ponytail: classic answers `gz model -i` one sample per call
POLL_TIMEOUT_S: Final = 2.0
_READ_CHUNK: Final = 16 * 1024
_TOKEN = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'|[{}:]|[^\s{}:]+")


# --- protobuf text format ------------------------------------------------------------------


def text_format_document(text: str) -> dict[str, Any]:
    """`google::protobuf::TextFormat` → nested dicts; repeated keys become lists; stray tokens
    (the conda build's `goo.gle/debug*` markers) are skipped. Raises `ValueError` past the
    size or depth bound."""
    if len(text) > MAX_TEXT_FORMAT_BYTES:
        raise ValueError("text-format message too large")
    doc, _ = _tf_message(_TOKEN.findall(text), 0, 0)
    return doc


def _tf_message(tokens: list[str], index: int, depth: int) -> tuple[dict[str, Any], int]:
    if depth > MAX_TEXT_DEPTH:
        raise ValueError("text-format nesting too deep")
    doc: dict[str, Any] = {}
    while index < len(tokens):
        key = tokens[index]
        if key == "}":
            return doc, index + 1
        nxt = tokens[index + 1] if index + 1 < len(tokens) else None
        if key in ("{", ":") or nxt is None:
            index += 1
            continue
        opens_block = nxt == "{" or (nxt == ":" and tokens[index + 2 : index + 3] == ["{"])
        if opens_block:
            start = index + 2 if nxt == "{" else index + 3
            value, index = _tf_message(tokens, start, depth + 1)
        elif nxt == ":" and index + 2 < len(tokens):
            value, index = _tf_scalar(tokens[index + 2]), index + 3
        else:
            index += 1
            continue
        _tf_add_field(doc, key, value)
    return doc, index


def _tf_scalar(piece: str) -> Any:
    if piece[:1] in ('"', "'"):
        return piece[1:-1] if len(piece) >= 2 and piece[-1] == piece[0] else piece[1:]
    if piece in ("true", "false"):
        return piece == "true"
    for cast in (int, float):
        try:
            return cast(piece)
        except ValueError:
            continue
    return piece


def _tf_add_field(doc: dict[str, Any], key: str, value: Any) -> None:
    if key not in doc:
        doc[key] = value
    elif isinstance(doc[key], list):
        doc[key].append(value)
    else:
        doc[key] = [doc[key], value]


async def text_blocks(lines: AsyncIterator[bytes]) -> AsyncIterator[str]:
    """Blank-line separated messages from a `gz topic -e` stdout. The running byte count is
    bounded while the block accumulates: past MAX_TEXT_FORMAT_BYTES the block is discarded and
    the rest of it skipped up to the next blank line, so a stream that never emits a separator
    cannot grow memory."""
    buffer: list[bytes] = []
    size = 0
    async for raw in lines:
        if not raw.strip():
            if buffer:
                yield _flush_block(buffer)
            size = 0
            continue
        size += len(raw)
        if size <= MAX_TEXT_FORMAT_BYTES:
            buffer.append(raw)
        elif buffer:
            logger.debug(
                "dropping oversized text-format message (>%d bytes)", MAX_TEXT_FORMAT_BYTES
            )
            buffer.clear()
    if buffer:
        yield _flush_block(buffer)


def _flush_block(buffer: list[bytes]) -> str:
    data = b"".join(buffer)
    buffer.clear()
    return data.decode("utf-8", "replace").strip()


async def packets_from_text_blocks(
    topic: str, blocks: AsyncIterator[str], *, clock: Callable[[], datetime] = utc_now
) -> AsyncIterator[TelemetryPacket]:
    """One text-format message → one packet of its numeric leaves (through the shared JSON
    choke point, so the same name/size/signal bounds apply); unparseable blocks are skipped."""
    async for block in blocks:
        try:
            doc = text_format_document(block)
        except ValueError:
            logger.debug("skipping unparseable text-format message on %s", topic)
            continue
        packet = packet_from_json_payload(topic, log_time_ns(clock()), json.dumps(doc).encode())
        if packet is not None:
            yield packet


def joint_angle_packets(
    world: str, model: str, stamp: datetime, doc: dict[str, Any]
) -> list[TelemetryPacket]:
    """`gz model -i` document → one packet per joint (`angle` → `<joint>.position`); the
    `<model>::` scope classic prefixes joint names with is stripped."""
    joints = doc.get("joint")
    items = joints if isinstance(joints, list) else [joints] if isinstance(joints, dict) else []
    out: list[TelemetryPacket] = []
    for joint in items:
        name = joint.get("name") if isinstance(joint, dict) else None
        if not isinstance(name, str):
            continue
        short = name.removeprefix(f"{model}::")
        packet = joint_packet(world, model, short, stamp, {"position": joint.get("angle")})
        if packet is not None:
            out.append(packet)
    return out


class ClassicTopicSource(GazeboTopicSource):
    """`gz topic -e <topic>` (text format) per topic plus an optional joint poll."""

    family: ClassVar[FamilyName] = "classic"

    def __init__(
        self,
        topics: list[str],
        *,
        exe: Path,
        world: str | None = None,
        model: str | None = None,
        poll_hz: float = POLL_HZ_CEILING,
    ) -> None:
        if (world is None) != (model is None):
            raise ValueError("world and model go together")
        if not topics and world is None:
            raise ValueError("at least one topic, or a world and model, required")
        self._world = identifier_or_raise(world) if world is not None else None
        self._model = identifier_or_raise(model) if model is not None else None
        self.poll_hz = min(max(poll_hz, 0.1), POLL_HZ_CEILING)
        self._init_common(topics, exe)

    def argv(self, topic: str) -> list[str]:
        return [self._exe, "topic", "-e", topic]

    def poll_argv(self) -> list[str]:
        if self._world is None or self._model is None:
            raise ValueError("no world/model to poll")
        return [self._exe, "model", "-w", self._world, "-m", self._model, "-i"]

    def _pumps(self, queue: asyncio.Queue[TelemetryPacket | None]) -> list[asyncio.Task[None]]:
        pumps = super()._pumps(queue)
        if self._world is not None:
            pumps.append(asyncio.create_task(self._pump(self._poll_packets(), queue, "joint poll")))
        return pumps

    async def _topic_packets(self, topic: str) -> AsyncIterator[TelemetryPacket]:
        proc = await self._spawn(self.argv(topic))
        async for packet in packets_from_text_blocks(topic, text_blocks(stdout_lines(proc))):
            yield packet

    async def _poll_packets(self) -> AsyncIterator[TelemetryPacket]:
        assert self._world is not None and self._model is not None
        period = 1.0 / self.poll_hz
        loop = asyncio.get_running_loop()
        while not self._closed:
            started = loop.time()
            doc = await self._poll_once()
            for packet in joint_angle_packets(self._world, self._model, utc_now(), doc):
                yield packet
            await asyncio.sleep(max(0.0, period - (loop.time() - started)))

    async def _poll_once(self) -> dict[str, Any]:
        proc = await self._spawn(self.poll_argv())
        raw = bytearray()
        try:
            if not self._closed:  # aclose may have landed while the child was spawning
                await asyncio.wait_for(_read_to_eof(proc, raw), timeout=POLL_TIMEOUT_S)
        except TimeoutError:
            raw.clear()
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            if proc in self._procs:  # aclose clears the list under an in-flight poll
                self._procs.remove(proc)
        if self._closed:
            return {}  # a child aclose killed mid-dump answered nothing worth emitting
        try:
            return text_format_document(raw.decode("utf-8", "replace"))
        except ValueError:
            logger.debug("classic joint poll answered unparseable text format")
            return {}


async def _read_to_eof(proc: asyncio.subprocess.Process, buf: bytearray) -> None:
    """`gz model -i` writes through block-buffered stdio, so a model dump arrives in several
    pipe chunks: read until EOF, bounded — past MAX_TEXT_FORMAT_BYTES the document is refused
    by `text_format_document` anyway, so stop accumulating there."""
    assert proc.stdout is not None
    while len(buf) <= MAX_TEXT_FORMAT_BYTES and (chunk := await proc.stdout.read(_READ_CHUNK)):
        buf += chunk
