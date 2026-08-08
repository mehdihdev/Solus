"""BYO-license credential relay (MCP-05, bridge-protocol.md Addendum C).

The desktop app writes one stdin control line per capture —
`{"type":"credential","server":"<name>","secrets":{"<key>":"<value>"}}` —
and the companion relays it as exactly one `credential_submit` frame up the
cloud channel. The cloud replies with one `credential_ack` carrying key
NAMES only, surfaced on the supervisor's existing status entries.

Hygiene (CLAUDE.md §7 / Addendum C never-logged rule): secret VALUES only
ever exist in the queued wire frame and the socket write — never in any log
record, drop reason, repr, or persisted state. Key NAMES and server names
may be logged. Malformed / oversize / unknown-server lines are dropped and
counted, never raised on, never echoed.
"""

import asyncio
import json
import logging
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("solus.companion.credentials")

# Addendum C: credential_submit is a control frame — the §6 16 KiB cap applies.
MAX_CONTROL_FRAME_BYTES = 16 * 1024
# Bounded backlog (§7 loop-guard posture): submits queue while offline and ride
# up on (re)connect; overflow drops the newest line, never blocks stdin.
MAX_PENDING_SUBMITS = 8
_SERVER_LOG_CAP = 32
_ACK_ERROR_CAP = 200
_CREDENTIAL_LINE_FIELDS = frozenset({"type", "server", "secrets"})


def credential_submit_frame(server: str, secrets: Mapping[str, str]) -> str:
    """One Addendum C `credential_submit` frame, compact JSON."""
    return json.dumps(
        {"type": "credential_submit", "data": {"server": server, "secrets": dict(secrets)}},
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class CredentialAck:
    """One inbound `credential_ack` — key NAMES only, never values."""

    server: str
    ok: bool
    stored: tuple[str, ...]
    error: str | None


def parse_credential_ack(raw: str | bytes) -> CredentialAck | None:
    """Parse one inbound `credential_ack` frame defensively — never raises.
    Anything malformed → None (the caller logs a static reason, no echo)."""
    try:
        envelope = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(envelope, dict) or envelope.get("type") != "credential_ack":
        return None
    data = envelope.get("data")
    if not isinstance(data, dict):
        return None
    server = data.get("server")
    ok = data.get("ok")
    stored = data.get("stored")
    error = data.get("error")
    if not isinstance(server, str) or not server or not isinstance(ok, bool):
        return None
    if not isinstance(stored, list) or not all(isinstance(key, str) for key in stored):
        return None
    if error is not None and not isinstance(error, str):
        return None
    return CredentialAck(
        server=server[:_SERVER_LOG_CAP],
        ok=ok,
        stored=tuple(stored),
        error=error[:_ACK_ERROR_CAP] if error else None,
    )


class CredentialRelay:
    """Validates stdin credential lines and queues their wire frames.

    `offer` runs on the stdin path (sync, never raises); the channel drains
    `next_frame` while connected. The queue holds ready frame STRINGS so a
    value is built into its frame exactly once and lives nowhere else."""

    def __init__(self, known_servers: frozenset[str] = frozenset()) -> None:
        # The discovered-server set (ADR-031): only servers the companion
        # actually supervises may be licensed through it.
        self.known_servers = known_servers
        self.dropped: Counter[str] = Counter()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=MAX_PENDING_SUBMITS)

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    async def next_frame(self) -> str:
        """The next queued `credential_submit` wire frame (awaits one)."""
        return await self._queue.get()

    def _drop(self, kind: str, reason: str) -> bool:
        """Count and log a drop. `reason` is Solus-authored text plus at most
        server/key NAMES — never a secret value."""
        self.dropped[kind] += 1
        logger.warning("dropped credential line (%s): %s", kind, reason)
        return False

    def offer(self, message: Mapping[str, Any]) -> bool:
        """One parsed stdin credential line → at most one queued frame."""
        server = message.get("server")
        if not isinstance(server, str) or not server:
            return self._drop("malformed", "missing or non-string server name")
        label = server[:_SERVER_LOG_CAP]
        if set(message) != _CREDENTIAL_LINE_FIELDS:
            return self._drop("malformed", f"unexpected fields in line for {label!r}")
        if server not in self.known_servers:
            return self._drop("unknown_server", f"server {label!r} is not in the discovered set")
        secrets = message.get("secrets")
        if not isinstance(secrets, dict) or not secrets:
            return self._drop("malformed", f"line for {label!r} without a secrets object")
        if not all(
            isinstance(key, str) and key and isinstance(value, str)
            for key, value in secrets.items()
        ):
            return self._drop("malformed", f"non-string secret entry for {label!r}")
        frame = credential_submit_frame(server, secrets)
        if len(frame.encode("utf-8")) > MAX_CONTROL_FRAME_BYTES:
            return self._drop("oversize", f"frame for {label!r} exceeds the 16 KiB control cap")
        try:
            self._queue.put_nowait(frame)
        except asyncio.QueueFull:
            return self._drop("backlog", f"submit backlog full; line for {label!r} dropped")
        logger.info("credential line accepted for %r (keys: %s)", label, ", ".join(sorted(secrets)))
        return True


def surface_ack(ack: CredentialAck, supervisor: object) -> None:
    """Log the ack (key NAMES only) and reflect it onto the supervisor's
    status surface when it supports `note_license_ack`. The lookup is duck-
    typed on purpose: the channel's BridgeSupervisor protocol stays unwidened
    so existing protocol fakes keep working — the ack surface is best-effort
    UI feedback, never load-bearing state."""
    if ack.ok:
        logger.info(
            "license credentials stored for %r: %s", ack.server, ", ".join(ack.stored) or "(none)"
        )
    else:
        logger.warning(
            "license credentials rejected for %r: %s", ack.server, ack.error or "no reason given"
        )
    note = getattr(supervisor, "note_license_ack", None)
    if callable(note):
        note(ack.server, ack.ok, ack.stored, ack.error)


__all__ = [
    "MAX_CONTROL_FRAME_BYTES",
    "MAX_PENDING_SUBMITS",
    "CredentialAck",
    "CredentialRelay",
    "credential_submit_frame",
    "parse_credential_ack",
    "surface_ack",
]
