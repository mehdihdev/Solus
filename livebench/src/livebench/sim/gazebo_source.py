"""Gazebo sim → LB-06 packets (LB-01; per-joint split and pinned binary: SOLUSDEV-322 P3-T5).

Gazebo's Python transport bindings ship with the simulator install, not on PyPI, so
binding to them would make this package uninstallable everywhere Gazebo isn't. The
CLI is the stable seam: `gz topic -e -t <topic> --json-output` prints one JSON
object per message, and `packets_from_json_lines` turns that stream into packets —
the same function the tests drive directly with recorded lines.

A `/world/<w>/model/<m>/joint_state` message (`gz.msgs.Model` from the joint-state-publisher
system) is split into one packet per joint — `device_id = <w>/<m>/<joint>`, values
`<joint>.position` (rad) and `<joint>.velocity` (rad/s) — so each joint resolves to its own
part node exactly as the MuJoCo source's `<scene>/<joint>` does (plan §1.4).

Message time: `gz topic --json-output` lines carry no transport receive-time, so
packets are stamped with the provided clock (arrival time) — honest for a live
stream, and injectable for tests.

Subprocess rules (CLAUDE.md §7): argument lists only, the binary is a path the caller resolved
through `gazebo_family.find_exe` (`SOLUS_GAZEBO_PATH`, never PATH), never `shell=True`, topics
validated as flag-safe, and the child runs under `gazebo_family.simulator_env()` — the
simulator's own variables only, never this process's secrets.
"""

import asyncio
import json
import logging
import math
import re
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError
from solus_api.graph.codec import MAX_PACKET_BYTES
from solus_api.graph.packet import TelemetryPacket

from livebench.sim.gazebo_family import FamilyName, GazeboNotAvailableError, simulator_env
from livebench.telemetry.normalize import packet_from_json_payload

__all__ = ["GazeboNotAvailableError", "GazeboTopicSource", "packets_from_json_lines"]

logger = logging.getLogger(__name__)

_NS_PER_US = 1_000
_US_PER_S = 1_000_000
_JOINT_STATE_TOPIC = re.compile(r"^/world/([^/]+)/model/([^/]+)/joint_state$")
_JOINT_UNITS = {"position": "rad", "velocity": "rad/s"}
_READ_CHUNK = 16 * 1024


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def log_time_ns(stamp: datetime) -> int:
    return int(stamp.timestamp() * _US_PER_S) * _NS_PER_US


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def joint_packet(
    world: str, model: str, joint: str, stamp: datetime, readings: dict[str, object]
) -> TelemetryPacket | None:
    """`<world>/<model>/<joint>` with `<joint>.position` (rad) / `<joint>.velocity` (rad/s) from
    whichever of `readings` is a finite number; `None` when neither is."""
    values = {
        f"{joint}.{key}": number
        for key in _JOINT_UNITS
        if (number := _finite_float(readings.get(key))) is not None
    }
    if not values:
        return None
    units = {signal: _JOINT_UNITS[signal.rsplit(".", 1)[1]] for signal in values}
    try:
        return TelemetryPacket(
            device_id=f"{world}/{model}/{joint}", timestamp=stamp, values=values, units=units
        )
    except ValidationError:
        logger.debug("dropping joint %.64r: packet refused it", joint)
        return None


def _model_joint_packets(
    world: str, model: str, stamp: datetime, message: dict[str, object]
) -> list[TelemetryPacket]:
    """One `gz.msgs.Model` JSON document → one packet per joint carrying finite signals."""
    joints = message.get("joint")
    if not isinstance(joints, list):
        return []
    out: list[TelemetryPacket] = []
    for joint in joints:
        name, axis = (
            (joint.get("name"), joint.get("axis1")) if isinstance(joint, dict) else (None, None)
        )
        if isinstance(name, str) and isinstance(axis, dict):
            packet = joint_packet(world, model, name, stamp, axis)
            if packet is not None:
                out.append(packet)
    return out


def _joint_state_packets(
    world: str, model: str, stamp: datetime, payload: bytes
) -> list[TelemetryPacket]:
    if len(payload) > MAX_PACKET_BYTES:
        return []
    try:
        message = json.loads(payload)
    except ValueError:
        return []
    return _model_joint_packets(world, model, stamp, message) if isinstance(message, dict) else []


async def packets_from_json_lines(
    topic: str,
    lines: AsyncIterator[bytes],
    *,
    clock: Callable[[], datetime] = utc_now,
) -> AsyncIterator[TelemetryPacket]:
    """One `gz topic --json-output` line → one packet (or one per joint on a joint_state topic);
    malformed lines are skipped."""
    joint_topic = _JOINT_STATE_TOPIC.match(topic)
    async for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        stamp = clock()
        if joint_topic is not None:
            world, model = joint_topic.group(1), joint_topic.group(2)
            for split in _joint_state_packets(world, model, stamp, stripped):
                yield split
            continue
        packet = packet_from_json_payload(topic, log_time_ns(stamp), stripped)
        if packet is None:
            logger.debug("skipping undecodable gz line on %s", topic)
            continue
        yield packet


async def stdout_lines(proc: asyncio.subprocess.Process) -> AsyncIterator[bytes]:
    """Newline-terminated lines from the child's stdout. Split here rather than by
    `StreamReader.readline()`, whose 64 KiB limit raises ValueError and would end the topic for
    good: a line past MAX_PACKET_BYTES (never a packet anyway) is dropped whole, the stream
    lives on."""
    assert proc.stdout is not None
    pending = bytearray()
    skipping = False
    while chunk := await proc.stdout.read(_READ_CHUNK):
        pending += chunk
        *lines, tail = pending.split(b"\n")
        for line in lines:
            if skipping or len(line) > MAX_PACKET_BYTES:
                logger.debug("dropping overlong stdout line")
            else:
                yield bytes(line) + b"\n"
            skipping = False
        pending = bytearray(tail)
        if len(pending) > MAX_PACKET_BYTES:
            skipping, pending = True, bytearray()
    if pending and not skipping:
        yield bytes(pending)


class GazeboTopicSource:
    """Live source: one pinned `<exe> topic -e -t <topic> --json-output` subprocess per topic.
    The new family (`gz`); `IgnitionTopicSource` runs the same shape under `ign` and
    `ClassicTopicSource` overrides the per-topic decoder and adds a joint poll."""

    family: ClassVar[FamilyName] = "gz"

    def __init__(self, topics: list[str], *, exe: Path) -> None:
        if not topics:
            raise ValueError("at least one topic required")
        self._init_common(topics, exe)

    def _init_common(self, topics: list[str], exe: Path) -> None:
        for topic in topics:
            if topic.startswith("-"):
                raise ValueError(f"topic may not start with '-': {topic!r}")
        self._exe = str(exe)
        self._topics = list(topics)
        self._procs: list[asyncio.subprocess.Process] = []
        self._closed = False

    @property
    def topics(self) -> list[str]:
        return list(self._topics)

    def argv(self, topic: str) -> list[str]:
        return [self._exe, "topic", "-e", "-t", topic, "--json-output"]

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        queue: asyncio.Queue[TelemetryPacket | None] = asyncio.Queue()
        pumps = self._pumps(queue)
        pending = len(pumps)
        try:
            while pending and not self._closed:
                packet = await queue.get()
                if packet is None:
                    pending -= 1
                    continue
                yield packet
        finally:
            for task in pumps:
                task.cancel()
            # Join the cancelled pumps so no "Task was destroyed but pending" leaks
            # (matches PacketStreamLiveConnection.aclose's discipline).
            await asyncio.gather(*pumps, return_exceptions=True)
            await self.aclose()

    def _pumps(self, queue: asyncio.Queue[TelemetryPacket | None]) -> list[asyncio.Task[None]]:
        return [
            asyncio.create_task(self._pump(self._topic_packets(topic), queue, topic))
            for topic in self._topics
        ]

    async def _pump(
        self,
        packets: AsyncIterator[TelemetryPacket],
        queue: asyncio.Queue[TelemetryPacket | None],
        label: str,
    ) -> None:
        try:
            async for packet in packets:
                await queue.put(packet)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("%s pump for %s died", self.family, label)
        finally:
            await queue.put(None)

    async def _spawn(self, argv: list[str]) -> asyncio.subprocess.Process:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=simulator_env(),  # never this process's database URL or API keys
        )
        self._procs.append(proc)
        return proc

    async def _topic_packets(self, topic: str) -> AsyncIterator[TelemetryPacket]:
        proc = await self._spawn(self.argv(topic))
        async for packet in packets_from_json_lines(topic, stdout_lines(proc)):
            yield packet

    async def aclose(self) -> None:
        self._closed = True
        for proc in self._procs:
            if proc.returncode is None:
                proc.terminate()
                try:
                    # Reap the child; escalate to SIGKILL if it ignores SIGTERM.
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
        self._procs.clear()
