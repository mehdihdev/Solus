"""Gazebo sim → LB-06 packets (LB-01).

Gazebo's Python transport bindings ship with the simulator install, not on PyPI, so
binding to them would make this package uninstallable everywhere Gazebo isn't. The
CLI is the stable seam: `gz topic -e -t <topic> --json-output` prints one JSON
object per message, and `packets_from_json_lines` turns that stream into packets —
the same function the tests drive directly with recorded lines.

Message time: `gz topic --json-output` lines carry no transport receive-time, so
packets are stamped with the provided clock (arrival time) — honest for a live
stream, and injectable for tests.

Subprocess rules (CLAUDE.md §7): argument lists only, binary resolved once via
`shutil.which` and pinned, never `shell=True`, topics validated as flag-safe.
"""

import asyncio
import logging
import shutil
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from solus_api.graph.packet import TelemetryPacket

from livebench.telemetry.normalize import packet_from_json_payload

logger = logging.getLogger(__name__)

_NS_PER_US = 1_000
_US_PER_S = 1_000_000


class GazeboNotAvailableError(RuntimeError):
    """The `gz` CLI is not installed — the Gazebo connector cannot run on this machine."""


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


async def packets_from_json_lines(
    topic: str,
    lines: AsyncIterator[bytes],
    *,
    clock: Callable[[], datetime] = _utc_now,
) -> AsyncIterator[TelemetryPacket]:
    """One `gz topic --json-output` line → one packet; malformed lines are skipped."""
    async for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        stamp = clock()
        log_time_ns = int(stamp.timestamp() * _US_PER_S) * _NS_PER_US
        packet = packet_from_json_payload(topic, log_time_ns, stripped)
        if packet is None:
            logger.debug("skipping undecodable gz line on %s", topic)
            continue
        yield packet


class GazeboTopicSource:
    """Live source: one pinned `gz topic -e --json-output` subprocess per topic."""

    def __init__(self, topics: list[str], *, gz_binary: str | None = None) -> None:
        if not topics:
            raise ValueError("at least one topic required")
        for topic in topics:
            if topic.startswith("-"):
                raise ValueError(f"topic may not start with '-': {topic!r}")
        binary = gz_binary or shutil.which("gz")
        if binary is None:
            raise GazeboNotAvailableError(
                "`gz` CLI not found — install Gazebo (ros-jazzy-ros-gz) to stream from it"
            )
        self._binary = binary
        self._topics = list(topics)
        self._procs: list[asyncio.subprocess.Process] = []
        self._closed = False

    async def __aiter__(self) -> AsyncIterator[TelemetryPacket]:
        queue: asyncio.Queue[TelemetryPacket | None] = asyncio.Queue()
        pumps = [asyncio.create_task(self._pump_topic(topic, queue)) for topic in self._topics]
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

    async def _pump_topic(self, topic: str, queue: asyncio.Queue[TelemetryPacket | None]) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                "topic",
                "-e",
                "-t",
                topic,
                "--json-output",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            self._procs.append(proc)
            assert proc.stdout is not None

            async def stdout_lines() -> AsyncIterator[bytes]:
                assert proc.stdout is not None
                async for raw in proc.stdout:
                    yield raw

            async for packet in packets_from_json_lines(topic, stdout_lines()):
                await queue.put(packet)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("gz topic pump for %s died", topic)
        finally:
            await queue.put(None)

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
