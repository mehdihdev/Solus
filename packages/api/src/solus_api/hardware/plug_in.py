"""The plug-in path (SOLUSDEV-326 P2-T6; docs/api/hardware.md §4): a device that arrives on this
machine is inspected before anyone asks, with no model call.

When the `DeviceWatcher` writes a change into this machine's device memory, each device plugged in
now that nothing binds and the machine's owner has not said "Not now" to is an arrival: the watcher
marks its row `inspecting` and runs `inspect_arrival`, which listens through the same service as
SOL's `hardware.inspect_device` and keeps the inspection for the owner in that project
(`inspections.INSPECTIONS`), where the tool's first call answers it while fresh. "Binds" is what
the owner may see (§1a): a device only a teammate's hardware out of the graph holds is inspected
like one nothing holds, so its row never tells the owner that hardware exists. The row then says
`inspected`, `busy` (someone holds the port) or `unknown` (not listened to: it would restart a
running board, it left, or the runner failed). An inspection is the owner's alone and is made only
while they read the project on this machine.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Collection, Mapping
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from solus_api.core.errors import APIError
from solus_api.hardware import inspections
from solus_api.hardware.device_memory import DeviceContext, sees

logger = logging.getLogger("solus.hardware.plug_in")

INSPECTING: Final = "inspecting"
INSPECTED: Final = "inspected"
BUSY: Final = "busy"
UNKNOWN: Final = "unknown"


def machine_owner(machine: Mapping[str, Any]) -> uuid.UUID | None:
    """The member who registered the machine these attrs belong to, by `read_scope.owns_machine`'s
    own rule: the stored string is exactly their canonical id. Any other spelling is nobody."""
    raw = machine.get("owner_user_id")
    try:
        owner = uuid.UUID(raw) if isinstance(raw, str) else None
    except ValueError:
        return None
    return owner if str(owner) == raw else None


def arrivals(
    machine: Mapping[str, Any], context: DeviceContext, running: Collection[str]
) -> list[str]:
    """The devices this machine remembers as plugged in now that are owed an inspection: nothing
    its owner may see binds them (`annotate`'s `bound_to`, so hardware hidden from the owner
    changes nothing they read), the owner has not said "Not now", and no inspection has settled
    since they arrived or is among `running` — one marked `inspecting` that is not running was
    left behind by a process that died."""
    owner = machine_owner(machine)
    dismissed = set((machine.get("dismissed") or {}).get(str(owner), []))
    owed = []
    for row in machine.get("devices") or []:
        if not isinstance(row, Mapping) or not row.get("present"):
            continue
        ref = str(row.get("device_ref"))
        settled = row.get("state") not in (None, INSPECTING) or ref in running
        bound = any(sees(attrs, owner) for _, attrs in context.holders.get(ref, ()))
        if not settled and ref not in dismissed and not bound:
            owed.append(ref)
    return owed


async def inspect_arrival(
    sessions: async_sessionmaker[AsyncSession],
    local: Any,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    device_ref: str,
) -> str:
    """Listen to `device_ref` for its machine's owner and keep what was found for them; the state
    to record. Never raises (cancellation aside): what cannot be listened to is `unknown`."""
    try:
        # A board that was already running is never restarted here: SOL's own inspect_device
        # parks that as an approval card.
        if await asyncio.to_thread(local.listen_restarts, device_ref):
            return UNKNOWN
        async with sessions() as session:
            await inspections.inspect_device(
                session,
                local,
                project_id=project_id,
                user_id=user_id,
                device_ref=device_ref,
                unasked=True,
            )
            await session.commit()
    except APIError as exc:
        return BUSY if exc.code == "device_busy" else UNKNOWN
    except Exception as exc:  # noqa: BLE001 — a runner that fails must not end the watch
        logger.warning("plug-in inspection failed: %s", type(exc).__name__)
        return UNKNOWN
    return INSPECTED


__all__ = [
    "BUSY",
    "INSPECTED",
    "INSPECTING",
    "UNKNOWN",
    "arrivals",
    "inspect_arrival",
    "machine_owner",
]
