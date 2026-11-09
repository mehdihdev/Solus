"""SOL's machine, environment and history reads (SOLUSDEV-321 P1-T4).

`get_machine` reads one machine of the project by its companion id through `find_machine`. A
machine belongs to the member who registered it (`attrs.owner_user_id`), and its recent commands
are that member's alone: another member's are never returned, whoever asks and however the
request is phrased (CLAUDE.md §7), and the result says they were withheld. The member the tool
is bound to is fixed at registration by Solus code. `get_environment_divergences` reads the
stored table through `find_divergences_entry` and only reads: the route computes it on first
read, this never writes. `get_history` is the query behind `GET /projects/{id}/history`, newest
first, for one entity if asked, over at most the last 30 days; an event's payload (connector and
member text) is never rendered. Every read is scoped to the project bound at registration.
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Mapping, Sequence
from datetime import timedelta
from functools import partial
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import select

from solus_api.agent.project_card import owned_commands, owns_machine, tool_versions
from solus_api.agent.tools.read_tool import (
    LIMIT_PARAM,
    ReadResult,
    Row,
    bounded_read_tool,
    int_arg,
    limit_arg,
    page_rows,
    uuid_arg,
)
from solus_api.agent.tools.shapes import ToolErrorCode
from solus_api.agent.tools.tool import ToolException
from solus_api.models import Activity, utcnow
from solus_api.services.environment_divergence import find_divergences_entry
from solus_api.services.machines import find_machine
from solus_api.services.solus_payloads import DivergenceItem, EnvironmentDivergencesDoc

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.agent.tools.registry import ToolRegistry

#: A machine's newest commands (the project card's five) and tool versions one result shows; the
#: companion reports ten binaries at most, so a cut of the versions is a malformed report, and
#: it is counted.
_COMMANDS: Final = 5
_TOOLS: Final = 12
#: Items named per divergence cause, entities per history row, and how far back history reaches.
_ITEMS: Final = 10
_ENTITIES: Final = 3
MAX_HISTORY_DAYS: Final = 30


def _listing_text(shown: Sequence[str], total: int) -> str:
    """The parts shown, joined, and how many more there were: a cut is never silent."""
    text = "; ".join(shown)
    return f"{text}; +{total - len(shown)} more" if total > len(shown) else text


def _tool_rows(attrs: Mapping[str, Any]) -> list[Row]:
    """The tool versions as ONE row, a mapping keyed by tool, so a secret-named key is masked
    beside its value, and a note of how many more there were."""
    reported = tool_versions(attrs, limit=sys.maxsize)  # every one, to count what is cut
    if not reported:
        return []
    rows: list[Row] = [{"tool_versions": dict(reported[:_TOOLS])}]
    if len(reported) > _TOOLS:
        rows.append(f"+{len(reported) - _TOOLS} more tool versions")
    return rows


async def get_machine_handler(
    args: dict[str, Any],
    *,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    user_id: uuid.UUID,
) -> ReadResult:
    async with sessions() as session:
        machine = await find_machine(session, project_id, str(args.get("companion_id", "")))
    if machine is None:
        raise ToolException("Machine not found", code=ToolErrorCode.NOT_FOUND)
    attrs = machine.attrs
    owned = owns_machine(attrs, user_id)
    head: Row = {
        "machine": attrs.get("hostname") or machine.name,
        "os": attrs.get("os"),
        "arch": attrs.get("arch"),
        "id": machine.id,
        "owner": "you" if owned else "another member",
    }
    rows: list[Row] = [head, *_tool_rows(attrs)]
    if owned:
        rows.extend(owned_commands(attrs, user_id, limit=_COMMANDS))
    else:
        rows.append({"recent_commands": "withheld: only the machine's owner sees them"})
    return rows


def _item_text(item: DivergenceItem) -> str:
    parts = (
        item.name,
        item.expected and f"expected {item.expected}",
        item.actual and f"actual {item.actual}",
        item.detail,
    )
    return " ".join(part for part in parts if part)


async def get_environment_divergences_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    async with sessions() as session:
        entry = await find_divergences_entry(session, project_id)
    if entry is None or entry.payload is None:
        return ["environment divergences not computed yet"]
    # ponytail: every machine of the project, as the route and the context table show it (the
    # first tier keeps to the asker's own). Filter on `owner_user_id` here if a teammate's
    # packages should stay out of the model's reach.
    document = EnvironmentDivergencesDoc.model_validate(entry.payload)
    rows: list[Row] = [{"computed_at": document.computed_at}]
    for machine in document.machines:
        who = {"machine": machine.hostname, "machine_id": machine.machine_id}
        causes: list[Row] = [
            {
                **who,
                "cause": group.cause,
                "items": _listing_text(
                    [_item_text(item) for item in group.items[:_ITEMS]], len(group.items)
                ),
            }
            for group in machine.causes
        ]
        rows += causes or [{**who, "diverges": "none"}]
    return rows


async def get_history_handler(
    args: dict[str, Any], *, sessions: async_sessionmaker[AsyncSession], project_id: uuid.UUID
) -> ReadResult:
    days = int_arg(args, "since_days", default=MAX_HISTORY_DAYS, high=MAX_HISTORY_DAYS)
    stmt = select(
        Activity.created_at, Activity.type, Activity.domain, Activity.entity_ids, Activity.why_ref
    ).where(
        Activity.project_id == project_id, Activity.created_at >= utcnow() - timedelta(days=days)
    )
    if args.get("entity_id") is not None:
        stmt = stmt.where(Activity.entity_ids.contains([str(uuid_arg(args, "entity_id"))]))
    limit = limit_arg(args)
    # One event past the limit, the route's own trick: it is how a full page says more exist.
    stmt = stmt.order_by(Activity.created_at.desc(), Activity.id.desc()).limit(limit + 1)
    async with sessions() as session:
        events = (await session.execute(stmt)).tuples().all()
    rows: list[Row] = [
        {
            "at": at,
            "type": kind,
            "domain": domain,
            "entities": _listing_text(entity_ids[:_ENTITIES], len(entity_ids)),
            "why": why_ref,
        }
        for at, kind, domain, entity_ids, why_ref in events
    ]
    return page_rows(rows, limit)


def register_machine_tools(
    registry: ToolRegistry,
    sessions: async_sessionmaker[AsyncSession],
    project_id: uuid.UUID,
    *,
    user_id: uuid.UUID,
) -> None:
    """Add the three reads, bound to ONE project and, for `get_machine`, to the member asking."""
    registry.register(
        bounded_read_tool(
            "get_machine",
            "Read one machine of this project by its companion id (32 lowercase hex characters, "
            "such as a robot's host_machine_id): hostname, OS, architecture, tool versions, and "
            "its recent commands, newest first, only when the person asking owns the machine.",
            {
                "type": "object",
                "properties": {
                    "companion_id": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{32}$",
                        "description": "The machine's companion id.",
                    }
                },
                "required": ["companion_id"],
                "additionalProperties": False,
            },
            partial(get_machine_handler, sessions=sessions, project_id=project_id, user_id=user_id),
        )
    )
    registry.register(
        bounded_read_tool(
            "get_environment_divergences",
            "Read the stored environment divergence table: for each machine of this project, how "
            "it differs from the project's environment spec (missing, version drift, platform "
            "build, extra). It does not recompute the table.",
            {"type": "object", "properties": {}, "additionalProperties": False},
            partial(get_environment_divergences_handler, sessions=sessions, project_id=project_id),
        )
    )
    registry.register(
        bounded_read_tool(
            "get_history",
            "Read this project's history, newest first: each event's type, domain and time and "
            "the entities it touched. Optionally only the events that touched one entity, over "
            f"the last N days, at most {MAX_HISTORY_DAYS}.",
            {
                "type": "object",
                "properties": {
                    "entity_id": {
                        "type": "string",
                        "format": "uuid",
                        "description": "Only events that touched this entity.",
                    },
                    "since_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_HISTORY_DAYS,
                        "description": f"How many days back; {MAX_HISTORY_DAYS} if omitted.",
                    },
                    "limit": LIMIT_PARAM,
                },
                "additionalProperties": False,
            },
            partial(get_history_handler, sessions=sessions, project_id=project_id),
        )
    )
