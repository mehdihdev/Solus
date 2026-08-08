"""Companion entrypoint: `python -m solus_companion`.

Env config → server discovery → supervisor → channel loop. Runs until the
cloud sends a STOP close code (update required / revoked / superseded) or a
SIGINT/SIGTERM arrives, then shuts the servers down gracefully.
"""

import asyncio
import contextlib
import dataclasses
import logging
import signal
import sys

from solus_companion.channel import run_channel
from solus_companion.config import (
    _MAX_STDIN_LINE_BYTES,
    CompanionConfig,
    TokenBox,
    apply_token_line,
    config_from_env,
    discover_servers,
)
from solus_companion.supervisor import Supervisor

logger = logging.getLogger("solus.companion")

HEALTH_INTERVAL_SECONDS = 30.0

# MCP-05 / M4: cap the stdin StreamReader at twice the control-line bound so a
# well-formed control line always fits (apply_token_line still rejects any
# line over _MAX_STDIN_LINE_BYTES before parsing). A line longer than THIS
# makes asyncio's readline raise ValueError instead of returning; the consume
# loop drops it and resyncs rather than letting the whole control channel die.
STDIN_READER_LIMIT = _MAX_STDIN_LINE_BYTES * 2


async def _health_loop(supervisor: Supervisor) -> None:
    while True:
        await asyncio.sleep(HEALTH_INTERVAL_SECONDS)
        await supervisor.ensure_healthy()


async def _consume_token_lines(reader: asyncio.StreamReader, box: TokenBox) -> None:
    """Read newline-delimited control lines until EOF, applying each. An
    oversize line (longer than the reader limit) makes `readline` raise
    ValueError — asyncio clears the offending bytes from the buffer, so we
    count the drop and resync on the next newline rather than dying (M4)."""
    dropped = 0
    while True:
        try:
            line = await reader.readline()
        except ValueError:
            dropped += 1
            logger.warning(
                "dropped oversize stdin line (over %d bytes); %d dropped so far",
                STDIN_READER_LIMIT,
                dropped,
            )
            continue
        if not line:  # EOF: the app hung up; keep running on the current token
            return
        apply_token_line(box, line)


async def _stdin_token_loop(box: TokenBox) -> None:
    """BRG-04 prep: newline-delimited JSON token lines from the desktop app."""
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=STDIN_READER_LIMIT)
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    await _consume_token_lines(reader, box)


async def _amain(config: CompanionConfig) -> int:
    supervisor = Supervisor(config.servers)
    await supervisor.start_all()
    channel = asyncio.create_task(run_channel(config, supervisor))
    side_tasks = [asyncio.create_task(_health_loop(supervisor))]
    box = config.token_source if isinstance(config.token_source, TokenBox) else None
    if box is not None and not sys.stdin.isatty():
        side_tasks.append(asyncio.create_task(_stdin_token_loop(box)))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, channel.cancel)
    try:
        state = await channel
        logger.info("channel stopped: %s", state.stop_reason)
    except asyncio.CancelledError:
        logger.info("signal received; shutting down")
    finally:
        for task in side_tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await supervisor.stop_all()
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = config_from_env()
    servers = discover_servers(config.integrations_root, workspace=config.workspace)
    logger.info("discovered %d server(s) under %s", len(servers), config.integrations_root)
    return asyncio.run(_amain(dataclasses.replace(config, servers=servers)))


if __name__ == "__main__":
    raise SystemExit(main())
