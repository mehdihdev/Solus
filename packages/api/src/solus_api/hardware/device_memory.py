"""This machine's device memory and each member's "Not now" (SOLUSDEV-326).

A local API remembers, per project, what it has seen plugged in on ITS machine node: the
`machine:<companion id>` that this host's companion identity names (`services/machines.py`).
`attrs.devices` holds rows `{device_ref, identity_basis, headline, last_seen}` — never a path —
written by the `DeviceWatcher` when the enumeration changes and never announced as a graph change;
a device that leaves keeps its row and the time it was last seen. A row also carries the `state`
of the inspection its plug-in started (`hardware/plug_in.py`: `inspecting`, then `inspected`, `busy`
or `unknown`) for as long as the device stays plugged in. `attrs.dismissed` maps each
member to the device refs they said "Not now" to, until they clear them. Both are the machine
owner's alone to read (`read_scope.OWNER_ONLY_MACHINE_ATTRS`); `annotate` tells each reader of
the device list only what is theirs. A machine the project does not know remembers nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from solus_api.core.errors import APIError
from solus_api.graph.read_scope import IN_GRAPH, ONBOARDED_BY, owns_machine
from solus_api.hardware.bindings import binding_subjects
from solus_api.hardware.detect import robot_candidates
from solus_api.hardware.runtime import bound_refs
from solus_api.hardware.store import PART_KINDS
from solus_api.models import GraphEntity
from solus_api.services.machines import find_machine
from solus_api.services.solus_graph import lock_project

MAX_REMEMBERED: Final = 64
MAX_DISMISSED: Final = 64


def remembered(
    prior: Sequence[Any],
    devices: Sequence[Mapping[str, Any]],
    gone: Collection[str],
    at: str,
) -> list[dict[str, Any]]:
    """A machine's device memory after a change seen at `at`: each device present now, and each
    that just left (`gone`), was last seen then; every other remembered device keeps the time it
    was last seen. A device still plugged in keeps its row's `state`; one that comes back starts
    without one (a replug is a new arrival). `present` is whether a row's device is in `devices`,
    the FULL current list (SOLUSDEV-326: a device notice asks it), never inferred from `gone`,
    which is empty after a restart. A device without a ref is not remembered. Most recent first,
    bounded."""
    rows = {
        row["device_ref"]: dict(row)
        for row in prior
        if isinstance(row, Mapping) and isinstance(row.get("device_ref"), str)
    }
    for ref in gone:
        if ref in rows:
            rows[ref]["last_seen"] = at
    for device in devices:
        if key := device.get("device_ref"):
            was = rows.get(key, {})
            rows[key] = {
                "device_ref": key,
                "identity_basis": device.get("identity_basis"),
                "headline": device.get("headline"),
                "last_seen": at,
            }
            if was.get("present") and was.get("state"):
                rows[key]["state"] = was["state"]
    for key, row in rows.items():
        row["present"] = any(device.get("device_ref") == key for device in devices)
    ordered = sorted(rows.values(), key=lambda row: str(row.get("last_seen")), reverse=True)
    return ordered[:MAX_REMEMBERED]


async def this_machine(
    session: AsyncSession, project_id: uuid.UUID, host_id: str | None
) -> GraphEntity | None:
    """THIS API's machine node in the project, the one its companion identity names; None when
    the host has no identity or the project never registered it."""
    return await find_machine(session, project_id, host_id) if host_id else None


async def remember_devices(
    session: AsyncSession,
    project_id: uuid.UUID,
    host_id: str | None,
    devices: Sequence[Mapping[str, Any]],
    *,
    gone: Collection[str],
    at: str,
) -> GraphEntity | None:
    """Write what this machine sees now, and what just left, into its memory (under the project
    lock, like every machine writer). Flushes; never commits, never publishes."""
    if host_id is None:
        return None
    await lock_project(session, project_id)
    machine = await this_machine(session, project_id, host_id)
    if machine is None:
        return None
    rows = remembered(machine.attrs.get("devices") or [], devices, gone, at)
    if rows != machine.attrs.get("devices"):
        machine.attrs = {**machine.attrs, "devices": rows}
        await session.flush()
    return machine


def stamp_state(
    machine: GraphEntity, refs: Collection[str], state: str | None, *, only: str | None = None
) -> None:
    """Set the inspection `state` of each of `refs` this machine remembers as plugged in now
    (None: no state recorded) — with `only`, just the rows in that state: a device that left and
    came back starts without one, and what was heard before it left is not its result."""

    def stamped(row: Mapping[str, Any]) -> bool:
        ours = row.get("device_ref") in refs and bool(row.get("present"))
        return ours and (only is None or row.get("state") == only)

    machine.attrs = {
        **machine.attrs,
        "devices": [
            {**row, "state": state} if stamped(row) else row
            for row in machine.attrs.get("devices") or []
            if isinstance(row, Mapping)
        ],
    }


async def record_state(
    session: AsyncSession,
    project_id: uuid.UUID,
    host_id: str | None,
    device_ref: str,
    state: str | None,
    *,
    only: str | None = None,
) -> GraphEntity | None:
    """`stamp_state` for one device under the project lock, like every machine writer. Flushes;
    never commits, never publishes."""
    if host_id is None:
        return None
    await lock_project(session, project_id)
    machine = await this_machine(session, project_id, host_id)
    if machine is not None:
        stamp_state(machine, {device_ref}, state, only=only)
        await session.flush()
    return machine


async def _locked_machine(
    session: AsyncSession, project_id: uuid.UUID, host_id: str | None
) -> GraphEntity:
    if host_id is not None:
        await lock_project(session, project_id)
    machine = await this_machine(session, project_id, host_id)
    if machine is None:
        raise APIError(
            409,
            "machine_unknown",
            "This computer is not registered in this project yet; open Solus with its companion.",
        )
    return machine


async def dismiss(
    session: AsyncSession,
    project_id: uuid.UUID,
    host_id: str | None,
    user_id: uuid.UUID,
    device_ref: str,
) -> list[str]:
    """`user_id`'s "Not now" to `device_ref` on this machine: their list, newest last, the
    oldest dropped past `MAX_DISMISSED`. Flushes; the caller commits."""
    machine = await _locked_machine(session, project_id, host_id)
    dismissed = dict(machine.attrs.get("dismissed") or {})
    mine = [ref for ref in dismissed.get(str(user_id), []) if ref != device_ref] + [device_ref]
    dismissed[str(user_id)] = mine[-MAX_DISMISSED:]
    machine.attrs = {**machine.attrs, "dismissed": dismissed}
    await session.flush()
    return list(dismissed[str(user_id)])


async def clear_dismissals(
    session: AsyncSession, project_id: uuid.UUID, host_id: str | None, user_id: uuid.UUID
) -> int:
    """Forget every "Not now" `user_id` said on this machine; how many there were."""
    machine = await _locked_machine(session, project_id, host_id)
    dismissed = dict(machine.attrs.get("dismissed") or {})
    cleared = len(dismissed.pop(str(user_id), []))
    if cleared:
        machine.attrs = {**machine.attrs, "dismissed": dismissed}
        await session.flush()
    return cleared


@dataclass(frozen=True)
class DeviceContext:
    """What annotating a device list needs from the graph, read once for every reader: this
    machine's attrs (None: one the project does not know) and, per device ref, what binds it —
    the holders `bind_device` refuses (a config's binding edge, a robot's stored brain), then a
    part keyed by the ref."""

    machine: Mapping[str, Any] | None
    holders: Mapping[str, tuple[tuple[uuid.UUID, Mapping[str, Any]], ...]]


async def device_context(
    session: AsyncSession,
    project_id: uuid.UUID,
    devices: Sequence[Mapping[str, Any]],
    machine: GraphEntity | None,
) -> DeviceContext:
    refs = [ref for device in devices if (ref := device.get("device_ref"))]
    holders: dict[str, list[tuple[uuid.UUID, Mapping[str, Any]]]] = {}
    if refs:
        for ref, subject in (await binding_subjects(session, project_id, refs)).items():
            holders.setdefault(ref, []).append((subject.id, subject.attrs))
        # The bind rule's other half (`detect._refuse_bound_elsewhere`): a robot's stored brains
        # hold its devices with no binding edge, as revision a26000000002 backfills a config.
        # ponytail: resolves every robot's config per read, as that rule does; one query over the
        # CONFIG payloads if a project ever holds more than a few dozen robots.
        for candidate in await robot_candidates(session, project_id):
            for ref in bound_refs(candidate.config) & set(refs):
                robot = await session.get(GraphEntity, candidate.robot_entity_id)
                assert robot is not None  # robot_candidates just read it
                holders.setdefault(ref, []).append((robot.id, robot.attrs))
        keyed = await session.execute(
            select(GraphEntity.id, GraphEntity.external_ref, GraphEntity.attrs).where(
                GraphEntity.project_id == project_id,
                GraphEntity.kind.in_(PART_KINDS),
                GraphEntity.external_ref.in_(refs),
                GraphEntity.deleted_at.is_(None),
            )
        )
        for entity_id, ref, attrs in keyed.tuples():
            holders.setdefault(str(ref), []).append((entity_id, attrs))
    return DeviceContext(
        machine.attrs if machine is not None else None,
        {ref: tuple(rows) for ref, rows in holders.items()},
    )


def sees(attrs: Mapping[str, Any], viewer: uuid.UUID | None) -> bool:
    """`read_scope.visible_to` for a row already read: in the graph, or onboarded by `viewer`."""
    return attrs.get(IN_GRAPH) is not False or (
        viewer is not None and attrs.get(ONBOARDED_BY) == str(viewer)
    )


def annotate(
    devices: Sequence[Mapping[str, Any]], context: DeviceContext, viewer: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Each device with what `viewer` may know of it: what binds it (when they may see that),
    whether they said "Not now" to it, and — for the machine's owner — when it was last seen and
    the `state` of the inspection its plug-in started.
    `viewer` None is a reader naming no one: what is in the graph, nothing else."""
    machine = context.machine or {}
    memory = machine.get("devices") if owns_machine(machine, viewer) else None
    mine = {row.get("device_ref"): row for row in memory or [] if isinstance(row, Mapping)}
    dismissed = set((machine.get("dismissed") or {}).get(str(viewer), [])) if viewer else set()
    rows = []
    for device in devices:
        ref = device.get("device_ref")
        holders = context.holders.get(ref, ()) if ref else ()
        bound = next((str(entity) for entity, attrs in holders if sees(attrs, viewer)), None)
        row = mine.get(ref, {})
        rows.append(
            {
                **device,
                "bound_to": bound,
                "dismissed": ref in dismissed,
                "last_seen": row.get("last_seen"),
                "state": row.get("state"),
            }
        )
    return rows
