"""The drive relay to the desktop (docs/architecture/sol-drive.md §3; slice 3b, XPC).

The companion never reaches the `solus-input` agent itself: Solus.app's main
process is the agent's only XPC client (ADR-041 amendment 2026-10-28). Each
call writes one stdout line `{"type":"drive_request","id":N,"argv":[…]}` (ids
increase) and waits, under ONE deadline, for `{"type":"drive_reply","id":N,
"reply":{…}}` on stdin, routed here by `config.apply_token_line`. Timeout or
cancellation (Stop, a dropped bridge) writes `{"type":"drive_cancel","id":N}`.
Unknown or late ids are dropped. A reply over 24 MiB as JSON is refused, and a
reply must be exactly one JSON object with an `ok` flag.
"""

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from solus_companion.drive.outline import Emit

logger = logging.getLogger("solus.companion.drive")

#: A capture is a base64 PNG of at most 2048 px on its long edge (1568 by
#: default). Even an incompressible 2048² RGBA image (~22 MB as base64) fits;
#: the cap bounds a hostile or broken reply.
STDOUT_CAP_BYTES = 24 * 1024 * 1024
_REPLY_KEYS = frozenset({"type", "id", "reply"})


class DriveHelperError(Exception):
    """A drive call that produced no trustworthy answer. `code` is stable."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _line(value: dict[str, Any]) -> str:
    return json.dumps(value, separators=(",", ":"))


def _checked(reply: Any) -> dict[str, Any]:
    if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
        raise DriveHelperError("helper_output", "missing the ok flag")
    return reply


class DriveRelay:
    """Pending drive calls, answered by `drive_reply` lines from the desktop.

    `attached` is set once the stdin control channel is being read; without it
    no reply can ever arrive, so calls refuse `agent_unavailable` at once."""

    def __init__(
        self,
        emit: Emit,
        *,
        attached: bool = False,
        timeouts: dict[str, float] | None = None,
        reply_cap: int = STDOUT_CAP_BYTES,
    ) -> None:
        self._emit = emit
        self.attached = attached
        self.timeouts = timeouts or {}
        self.reply_cap = reply_cap
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[Any]] = {}

    @property
    def pending(self) -> int:
        return len(self._pending)

    def timeout_for(self, command: str, default: float) -> float:
        return self.timeouts.get(command, default)

    async def run(self, args: Sequence[str], *, timeout: float) -> dict[str, Any]:
        """One relayed call for `args`. Raises DriveHelperError."""
        if not self.attached:
            raise DriveHelperError(
                "agent_unavailable", "the desktop app is not relaying drive calls"
            )
        self._next_id += 1
        call_id = self._next_id
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        answered = False
        try:
            self._emit(_line({"type": "drive_request", "id": call_id, "argv": list(args)}))
            async with asyncio.timeout(timeout):  # ONE deadline for the whole call
                reply = await future
            answered = True
        except TimeoutError as exc:
            raise DriveHelperError("helper_timeout", f"no answer within {timeout:g}s") from exc
        finally:
            self._pending.pop(call_id, None)
            if not answered:  # timeout, cancellation or a refused reply: stop the helper
                self._emit(_line({"type": "drive_cancel", "id": call_id}))
        return _checked(reply)

    def deliver(self, message: Mapping[str, Any], *, size: int) -> None:
        """A `drive_reply` stdin line (`size` = its raw length). Never raises."""
        call_id = message.get("id")
        if set(message) != _REPLY_KEYS or type(call_id) is not int:
            logger.warning("ignored malformed drive_reply line")
            return
        future = self._pending.get(call_id)
        if future is None or future.done():
            logger.info("ignored drive_reply for unknown or finished call %d", call_id)
            return
        if size > self.reply_cap:
            future.set_exception(
                DriveHelperError("helper_output", f"reply over {self.reply_cap} bytes")
            )
            return
        future.set_result(message["reply"])
