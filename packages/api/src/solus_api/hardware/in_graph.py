"""SOLUSDEV-326 — Add to / Remove from the workspace graph (docs/api/hardware.md §1a).

Hardware not in the graph (`attrs.in_graph` false) is visible only to its onboarder
(`attrs.onboarded_by`; `graph/read_scope.visible_to`). A robot moves together with what Solus
keeps for it alone: the manual parts it contains, the topology nodes derived for it, the config
nodes of all of them, and its bench runs with the `.solus` documents they were filed as. A manual
part no robot contains moves alone. `stamp` is the one writer of the two keys on hardware (a run
takes its robot's at every save, `livebench/runs/store.save`); `set_in_graph` is the one service
the route and SOL's tool call.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.live import graph_changed_frame
from solus_api.graph.read_scope import (
    IN_GRAPH,
    ONBOARDED_BY,
    GraphReadScope,
    flags_of,
    visibility_attrs,
)
from solus_api.models import (
    GraphEdge,
    GraphEntity,
    Project,
    SolusEntry,
    SolusEntryKind,
    User,
    utcnow,
)
from solus_api.services.events import emit_event
from solus_api.services.physical_robots import GraphChangeCounts, ownership_edge
from solus_api.services.solus_graph import ORIGIN, lock_project

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.graph.live import LiveHub

logger = logging.getLogger("solus.hardware.in_graph")


@dataclass(frozen=True)
class InGraphChange:
    entity: GraphEntity
    #: Entities whose visibility changed; 0 when the hardware already was where it was asked to be.
    updated: int


async def stamp(
    session: AsyncSession,
    project_id: uuid.UUID,
    rows: Sequence[GraphEntity],
    flags: Mapping[str, Any],
) -> list[GraphEntity]:
    """Give `rows`, and the config nodes of those configured, exactly `flags` (the visibility
    attrs; none means in the graph); returns the rows that changed. The caller holds the lock."""
    nodes = await session.scalars(
        select(GraphEntity)
        .join(SolusEntry, SolusEntry.entity_id == GraphEntity.id)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.configured_entity_id.in_([row.id for row in rows]),
            GraphEntity.project_id == project_id,
            GraphEntity.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    changed: list[GraphEntity] = []
    for row in [*rows, *nodes]:
        kept = {
            key: value for key, value in row.attrs.items() if key not in (IN_GRAPH, ONBOARDED_BY)
        }
        if {**kept, **flags} != row.attrs:
            row.attrs = {**kept, **flags}
            changed.append(row)
    return changed


async def _members(
    session: AsyncSession, project_id: uuid.UUID, target: GraphEntity
) -> list[GraphEntity]:
    """What moves with `target`: a robot's own hardware and runs, or a manual part no robot
    contains."""
    from solus_api.hardware.store import PART_KINDS
    from solus_api.hardware.topology import derived_nodes
    from solus_api.livebench.runs.store import robot_runs

    if target.origin != ORIGIN or target.source_id is not None:
        raise APIError(409, "conflict", "Hardware from a connected source is always in the graph")
    if target.kind == kinds.PHYSICAL_ROBOT:
        parts = await session.scalars(
            select(GraphEntity)
            .where(
                GraphEntity.id.in_(
                    select(GraphEdge.dst_id).where(
                        ownership_edge(project_id), GraphEdge.src_id == target.id
                    )
                ),
                GraphEntity.kind.in_(PART_KINDS),
                GraphEntity.origin == ORIGIN,
                GraphEntity.source_id.is_(None),
                GraphEntity.deleted_at.is_(None),
            )
            .execution_options(populate_existing=True)
        )
        return [
            target,
            *parts,
            *(await derived_nodes(session, project_id, target.id))[0],
            *await robot_runs(session, project_id, target.id),
        ]
    owner = await session.scalar(
        select(GraphEdge.id).where(ownership_edge(project_id), GraphEdge.dst_id == target.id)
    )
    if owner is not None:
        raise APIError(409, "conflict", "A robot's part is added or removed with its robot")
    return [target]


ONLY_ONBOARDER = "Only the person who onboarded this hardware can take it out of the graph."


async def refuse_hiding(
    session: AsyncSession,
    project_id: uuid.UUID,
    parts: Sequence[GraphEntity],
    onboarder: uuid.UUID,
    *,
    together: Collection[uuid.UUID] = (),
) -> None:
    """409 when hiding `parts` for `onboarder` would leave a config someone else can see naming one
    (§1a: a config names only parts everyone who can see it can see), saying what to do. The
    configs of what hides `together` move with it; a refusal never names hardware the caller
    cannot see."""
    keys = {str(part.id): part for part in parts}
    if not keys:
        return
    # ponytail: one pass over the project's live configs per hide (a rare write); index the
    # bus-map part ids if a project ever holds thousands of configs.
    rows = await session.execute(
        select(SolusEntry.payload, GraphEntity.name, GraphEntity.attrs)
        .join(GraphEntity, GraphEntity.id == SolusEntry.configured_entity_id)
        .where(
            SolusEntry.project_id == project_id,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.configured_entity_id.not_in(together),
            GraphEntity.deleted_at.is_(None),
        )
    )
    for payload, name, attrs in rows:
        wired = sorted(_named(payload) & keys.keys())
        hidden = attrs.get(IN_GRAPH) is False
        if not wired or (hidden and attrs.get(ONBOARDED_BY) == str(onboarder)):
            continue  # names none of them, or only the onboarder sees that config
        part = keys[wired[0]]
        if hidden:
            raise APIError(
                409,
                "conflict",
                f"{part.name} is wired into a teammate's hardware that isn't in the graph yet. "
                "Ask them to remove it from their wiring, or to add their hardware to the graph, "
                "first.",
            )
        raise APIError(
            409,
            "conflict",
            f"{part.name} is wired into {name}, which is in the graph, so it has to stay in the "
            f"graph. Remove it from {name}'s wiring first.",
        )


def _named(payload: Mapping[str, Any] | None) -> set[str]:
    """The part ids a config payload names: bus-map rows and legacy v1 `parts` keys."""
    if not payload:
        return set()
    rows = payload.get("bus_map") or []
    named = {str(row["part_entity_id"]) for row in rows if row.get("part_entity_id")}
    return named | set(payload.get("parts") or {})


ADMIT_REFUSED = (
    "This wires hardware a teammate hasn't added to the graph yet. Ask them to add it to the "
    "graph first."
)


async def admit_wired(
    session: AsyncSession,
    project_id: uuid.UUID,
    subject: GraphEntity,
    parts: Sequence[GraphEntity],
    actor_id: uuid.UUID | None,
) -> int:
    """A config names only parts everyone who can see it can see (§1a). Parts out of the graph
    wired into `subject` in the graph join the graph, keeping their onboarder (one
    `hardware.added_to_graph` each), and so does what their own configs wire, all the way down —
    only when that onboarder is `actor_id`, whatever the read scope. Wired into `subject` out of
    the graph they must be its onboarder's. Anything else is a 409 naming nothing (a person's view
    is the 404 of an unknown part first). Returns the rows that changed."""
    out = subject.attrs.get(IN_GRAPH) is False
    owner = subject.attrs.get(ONBOARDED_BY) if out else str(actor_id) if actor_id else None
    joining = await wired_hidden(session, project_id, parts, owner, follow=not out)
    if out:
        return 0
    return sum([await _join(session, project_id, part, actor_id) for part in joining])


async def wired_hidden(
    session: AsyncSession,
    project_id: uuid.UUID,
    parts: Sequence[GraphEntity],
    owner: str | None,
    *,
    follow: bool = True,
) -> list[GraphEntity]:
    """The parts out of the graph among `parts` and (`follow`) what their own configs wire, all
    the way down — every one `owner`'s, else 409 naming nothing. Reads only: what `admit_wired`
    joins to the graph, and what SOL's set_in_graph card says joins."""
    found: dict[uuid.UUID, GraphEntity] = {}
    while hidden := [p for p in parts if p.attrs.get(IN_GRAPH) is False and p.id not in found]:
        if any(part.attrs.get(ONBOARDED_BY) != owner for part in hidden):
            raise APIError(409, "conflict", ADMIT_REFUSED)
        found.update((part.id, part) for part in hidden)
        if not follow:
            break
        parts = await _wired_parts(session, project_id, {part.id for part in hidden})
    return list(found.values())


async def _join(
    session: AsyncSession, project_id: uuid.UUID, part: GraphEntity, actor_id: uuid.UUID | None
) -> int:
    """`part` joins the graph, keeping its onboarder (`actor_id`, checked); its one event."""
    changed = await stamp(
        session, project_id, [part], visibility_attrs(in_graph=True, onboarded_by=actor_id)
    )
    actor = await session.get(User, actor_id) if actor_id is not None else None
    project = await session.get(Project, project_id)
    if actor is not None and project is not None:
        emit_event(
            session,
            user=actor,
            event_type="hardware.added_to_graph",
            team_id=project.team_id,
            project_id=project_id,
            payload={"entity_id": str(part.id), "kind": "part", "count": len(changed)},
        )
    return len(changed)


async def put_on(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    part: GraphEntity,
    actor_id: uuid.UUID | None,
) -> None:
    """An existing manual part put on `robot` takes its visibility (§1a). Out of the graph it
    takes the robot's keys (`refuse_onto` checked its onboarder first); in the graph it keeps its
    own onboarder — never the robot's, so a teammate's part never becomes someone else's — and,
    if it was out of the graph, joins it with what its config wires (`admit_wired`)."""
    if robot.attrs.get(IN_GRAPH) is False:
        await stamp(session, project_id, [part], flags_of(robot.attrs))
    else:
        await admit_wired(session, project_id, robot, [part], actor_id)


async def _wired_parts(
    session: AsyncSession, project_id: uuid.UUID, subjects: Collection[uuid.UUID]
) -> list[GraphEntity]:
    """The live parts the configs of `subjects` name (bus-map rows, legacy v1 `parts` keys)."""
    from solus_api.hardware.store import PART_KINDS

    payloads = await session.scalars(
        select(SolusEntry.payload).where(
            SolusEntry.project_id == project_id,
            SolusEntry.kind == SolusEntryKind.CONFIG,
            SolusEntry.deleted_at.is_(None),
            SolusEntry.configured_entity_id.in_(subjects),
        )
    )
    ids = {key for payload in payloads for key in _named(payload)}
    rows = await session.scalars(
        select(GraphEntity)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.id.in_([uuid.UUID(key) for key in ids]),
            GraphEntity.kind.in_(PART_KINDS),
            GraphEntity.deleted_at.is_(None),
        )
        .execution_options(populate_existing=True)
    )
    return list(rows)


async def refuse_onto(
    session: AsyncSession,
    project_id: uuid.UUID,
    robot: GraphEntity,
    parts: Sequence[GraphEntity],
) -> None:
    """A manual part put on `robot` takes its visibility (§1a). On a robot out of the graph that
    hides the part, which only the part's own onboarder may do, and never while a config someone
    else can see names it: 409, saying what to do, before anything is written."""
    flags = flags_of(robot.attrs)
    if flags.get(IN_GRAPH) is not False or not parts:
        return
    owner = flags.get(ONBOARDED_BY)
    for part in parts:
        if owner is None or part.attrs.get(ONBOARDED_BY) != owner:
            raise APIError(
                409,
                "conflict",
                f"{part.name} is in the graph, so your team can see it. Add {robot.name} to the "
                f"graph first, then put {part.name} on it.",
            )
    ids = {part.id for part in parts}
    await refuse_hiding(session, project_id, parts, uuid.UUID(owner), together=ids)


async def set_in_graph(
    session: AsyncSession,
    project: Project,
    viewer: User,
    entity_id: uuid.UUID,
    in_graph: bool,
    *,
    hub: LiveHub,
) -> InGraphChange:
    """Add a robot or a lone manual part to the graph, or take it out, as `viewer` — who must be
    able to see it (else 404, like an unknown id). Only its recorded onboarder takes hardware out
    (403 otherwise, hardware nobody onboarded included), and out of the graph it stays visible to
    them; it stays in while a config someone else can see names one of its parts (409). Commits;
    one data event and one `graph.changed` after the commit, only when something changed."""
    from solus_api.hardware.store import hardware_entity
    from solus_api.services.environment_divergence import recompute_divergences_guarded

    await lock_project(session, project.id)
    target = await hardware_entity(session, project.id, entity_id)
    if GraphReadScope(project.id, viewer_id=viewer.id).hides(target.attrs):
        raise APIError(404, "not_found", "Hardware entity not found")
    stored = target.attrs.get(ONBOARDED_BY)
    if not in_graph and stored != str(viewer.id):
        raise APIError(403, "forbidden", ONLY_ONBOARDER)
    flags = visibility_attrs(in_graph=in_graph, onboarded_by=uuid.UUID(stored) if stored else None)
    members = await _members(session, project.id, target)
    if not in_graph:
        await _refuse_out(session, project.id, target, members, viewer.id)
        changed = await stamp(session, project.id, members, flags)
    else:
        changed = await _stamp_in(session, project.id, target, members, flags, viewer.id)
    count = len(changed) + await _follow(session, project.id, target, members, viewer.id)
    if count:  # the project's environment spec is every member's: it follows at once
        await recompute_divergences_guarded(session, project.id)
    if changed:
        emit_event(
            session,
            user=viewer,
            event_type="hardware.added_to_graph" if in_graph else "hardware.removed_from_graph",
            team_id=project.team_id,
            project_id=project.id,
            payload={
                "entity_id": str(target.id),
                "kind": "robot" if target.kind == kinds.PHYSICAL_ROBOT else "part",
                "count": len(changed),
            },
        )
    await session.commit()
    if count:
        await _publish(hub, project.id, count)
    return InGraphChange(entity=target, updated=count)


async def _stamp_in(
    session: AsyncSession,
    project_id: uuid.UUID,
    target: GraphEntity,
    members: Sequence[GraphEntity],
    flags: Mapping[str, Any],
    viewer_id: uuid.UUID,
) -> list[GraphEntity]:
    """Adding stamps `target` and what is its own with its keys, never a part's onboarder: a part
    on the robot keeps its own, and one out of the graph joins only as the viewer's."""
    from solus_api.hardware.store import PART_KINDS

    parts = [row for row in members if row.kind in PART_KINDS and row.id != target.id]
    hidden = [part for part in parts if part.attrs.get(IN_GRAPH) is False]
    if any(part.attrs.get(ONBOARDED_BY) != str(viewer_id) for part in hidden):
        raise APIError(409, "conflict", ADMIT_REFUSED)
    rest = [row for row in members if row not in parts]
    joined = visibility_attrs(in_graph=True, onboarded_by=viewer_id)
    return [
        *await stamp(session, project_id, rest, flags),
        *await stamp(session, project_id, hidden, joined),
    ]


async def _refuse_out(
    session: AsyncSession,
    project_id: uuid.UUID,
    target: GraphEntity,
    members: Sequence[GraphEntity],
    viewer_id: uuid.UUID,
) -> None:
    """What `target` takes out of the graph with it must be the viewer's to take out (a part
    someone else onboarded, or nobody, is put on a robot keeping its own onboarder: 409, saying
    what to do), and no config someone else can see may name one of its parts."""
    from solus_api.hardware.store import PART_KINDS

    parts = [row for row in members if row.kind in PART_KINDS]
    for part in parts:
        if part.attrs.get(ONBOARDED_BY) != str(viewer_id):
            raise APIError(
                409,
                "conflict",
                f"{part.name} on {target.name} isn't yours to take out of the graph. Take it off "
                f"{target.name} first.",
            )
    await refuse_hiding(session, project_id, parts, viewer_id, together={r.id for r in members})


async def _follow(
    session: AsyncSession,
    project_id: uuid.UUID,
    target: GraphEntity,
    members: Sequence[GraphEntity],
    viewer_id: uuid.UUID,
) -> int:
    """What follows `target` beyond its members: the topology it shares (with every robot that
    reaches it) and, once it is in the graph, the parts its configs wire. Rows changed."""
    count = 0
    if target.kind == kinds.PHYSICAL_ROBOT:
        from solus_api.hardware.topology import derived_nodes, stamp_shared

        _, shared = await derived_nodes(session, project_id, target.id)
        count += await stamp_shared(session, project_id, target, shared)
    if target.attrs.get(IN_GRAPH) is not False:
        wired = await _wired_parts(session, project_id, {row.id for row in members})
        count += await admit_wired(session, project_id, target, wired, viewer_id)
    return count


async def _publish(hub: LiveHub, project_id: uuid.UUID, updated: int) -> None:
    """After the commit, in its own guard: a failed fan-out never undoes the change."""
    frame = graph_changed_frame(
        project_id=project_id,
        source_id=None,
        sync_id=None,
        counts=GraphChangeCounts(entities_updated=updated),
        at=utcnow().isoformat(),
    )
    try:
        await hub.publish(project_id, frame)
    except Exception:  # noqa: BLE001 — the change is committed; fan-out is never worth a lie
        logger.exception("graph fan-out failed project=%s (the change stands)", project_id)
