"""SOLUSDEV-326 — the device notice: "something was plugged in" as a turn Solus writes.

`MessageCreate.notice {kind: "device", device_ref}` (docs/contracts/action-gate.md §Cards 4). The
device must be present now on a machine the caller owns, by that machine's device memory
(`hardware/device_memory.py`, `attrs.devices`, the owner's alone): another member's machine, a
device that left, or a ref no machine of theirs saw is 422, worded the same and naming nothing.
The server writes the turn's words itself, from the remembered headline (Solus-authored by the
enumeration, never device text) and the ref, which can be device text, so it goes in cleaned and
quoted as data — never client text — and stores the user turn with
`attrs.authored_by = "solus"`; no `sol.message` is logged for it, since the person typed nothing,
and it never resets the continuation chain that caps resumes and wakes (`sol_resume._chain_length`).
One notice per device per person per two seconds: a second inside the window is 409
`notice_debounced` and writes nothing. The window starts when a notice is admitted, so one
refused for credits or frequency (402, 429) does not spend it.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.agent.cards import single_line
from solus_api.agent.conversation import ConversationService
from solus_api.contracts.action_gate import DeviceNotice
from solus_api.core.errors import APIError
from solus_api.deps import ProjectCtx
from solus_api.graph import kinds
from solus_api.graph.read_scope import owns_machine
from solus_api.models import GraphEntity, TurnRole

NOTICE_DEBOUNCE_SECONDS: Final = 2.0
#: The fixed sentence. `label` is the remembered headline, one printable line. `device_ref` can be
#: device text: a serial-basis ref is the device's own USB serial, which the device (or a sketch
#: flashed onto it) chooses — bidi overrides, zero-width and control characters, instructions. So
#: it is one printable line, JSON-quoted as data like a resume's card title, never raw.
_NOTICE: Final = "Solus noticed a device plugged into this computer: {label} ({device_ref})."
_LABEL_CAP: Final = 128
#: A device ref is `<transport>:<binding>` with a binding of at most 128 characters: never cut.
_REF_CAP: Final = 140
_SERVICE = ConversationService()
#: (person, device ref) → when its last notice was admitted, on `_now`'s clock.
#: ponytail: per process — only the local API that sees a device admits its notice; a multi-process
#: API would keep this window in Redis.
_last_notice: dict[tuple[uuid.UUID, str], float] = {}
_now = time.monotonic


async def _present_row(
    session: AsyncSession, project_id: uuid.UUID, user_id: uuid.UUID, device_ref: str
) -> Mapping[str, Any] | None:
    """The device memory's row for `device_ref` on a machine `user_id` owns here, when it says the
    device is present now; None otherwise."""
    machines = await session.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.MACHINE,
            GraphEntity.deleted_at.is_(None),
        )
    )
    rows = (
        row
        for machine in machines
        if owns_machine(machine.attrs, user_id)
        for row in machine.attrs.get("devices") or []
        if isinstance(row, Mapping)
    )
    return next(
        (row for row in rows if row.get("device_ref") == device_ref and row.get("present") is True),
        None,
    )


def _debounced(user_id: uuid.UUID, device_ref: str, *, claim: bool) -> bool:
    """True when this person announced this device less than the window ago; else, with `claim`,
    the window starts now. No await between the check and the claim, so two notices in one tick
    cannot both pass."""
    now = _now()
    for key in [key for key, at in _last_notice.items() if now - at >= NOTICE_DEBOUNCE_SECONDS]:
        del _last_notice[key]
    if (user_id, device_ref) in _last_notice:
        return True
    if claim:
        _last_notice[(user_id, device_ref)] = now
    return False


def _refuse_debounced(user_id: uuid.UUID, device_ref: str, *, claim: bool) -> None:
    if _debounced(user_id, device_ref, claim=claim):
        raise APIError(409, "notice_debounced", "That device was just announced.")


async def notice_prompt(session: AsyncSession, ctx: ProjectCtx, notice: DeviceNotice) -> str:
    """The notice's words, after its checks: 422 unless the device is present now on a machine
    the caller owns, then 409 inside the debounce window. The window is only read here: it is
    claimed when the notice is admitted (`record_notice`)."""
    row = await _present_row(session, ctx.project.id, ctx.user.id, notice.device_ref)
    if row is None:
        raise APIError(
            422, "validation_error", "That device is not plugged into your computer now."
        )
    _refuse_debounced(ctx.user.id, notice.device_ref, claim=False)
    label = single_line(row.get("headline") or "", _LABEL_CAP) or "a device"
    ref = json.dumps(single_line(notice.device_ref, _REF_CAP))
    return _NOTICE.format(label=label, device_ref=ref)


async def record_notice(
    session: AsyncSession,
    ctx: ProjectCtx,
    conversation_id: uuid.UUID,
    text: str,
    notice: DeviceNotice,
) -> None:
    """Store the notice as the caller's turn, authored by Solus, and start its debounce window:
    here, after the credit and frequency gates, so a notice refused by one never spends it. 409
    when another notice of the device was admitted since this one was checked. Flushes; the
    route commits."""
    _refuse_debounced(ctx.user.id, notice.device_ref, claim=True)
    await _SERVICE.append_turn(
        session,
        conversation_id=conversation_id,
        project_id=ctx.project.id,
        role=TurnRole.USER,
        content=text,
        attrs={"authored_by": "solus", "notice": notice.model_dump()},
    )
