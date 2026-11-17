"""SOLUSDEV-321 P0-T5 — the project card: layer 2 of SOL's stable prompt prefix.

Project-wide facts (name, physical robots, sources with their catalog capabilities, `.solus`
counts) are a `ProjectCard`, cached per project and dropped on every `graph.changed` by the
fan-out (graph/graph_changed_fanout.py). Open-finding counts, the budgets line, active bench
sessions and the caller's own machine change without one, so `card_inputs` reads them per request
and nothing caches them. Tenant data bound for a prompt (CLAUDE.md §7): queries are
project-scoped, every rendered string redacted and capped, the card one section fenced as DATA;
the machine is the caller's LIVE bridge session's, only when they own its row. No vendor is named.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy import select

from solus_api.agent.layers import ContextSection
from solus_api.agent.tools.untrusted import redact_text
from solus_api.connectors.httpcache import within_bound
from solus_api.graph import kinds
from solus_api.graph.findings import count_findings_by_severity
from solus_api.graph.read_scope import IN_GRAPH, ONBOARDED_BY
from solus_api.graph.read_scope import owns_machine as owns_machine  # its readers import it here
from solus_api.models import GraphEntity, Project, Source
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.orchestration.type_estimator import chars_for_tokens, estimate_tokens
from solus_api.services.budgets import find_budgets_entry
from solus_api.services.machines import find_machine
from solus_api.services.solus_config import load_sections
from solus_api.services.solus_payloads import BudgetLine, Budgets

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from solus_api.bridge.registry import BridgeSession
    from solus_api.connectors.httpcache import CacheStore
    from solus_api.connectors.registry import ConnectorRegistry
    from solus_api.livebench.sessions import SessionManager

logger = logging.getLogger("solus.agent.project_card")

#: The card's ceiling; the layer cap (`LayerBudget.project_card`) is reported, not enforced.
CARD_MAX_TOKENS: Final = 300
CACHE_TTL_SECONDS: Final = 600
_NAME_CAP: Final = 80
_BUDGETS_CAP: Final = 120
_COMMAND_FIELD_CAP: Final = 200
_MAX_TOOL_VERSIONS: Final = 8
_MAX_COMMANDS: Final = 5
#: Waiting devices a card names, and how much of each.
_MAX_WAITING: Final = 5
_DEVICE_CAP: Final = 280  # a full headline and its quoted ref
#: A waiting device's headline and ref, as a notice caps them (`routers/sol_notice.py`).
_LABEL_CAP: Final = 128
_REF_CAP: Final = 140
#: Robots and sources read per card — far more than the ceiling can show; a full read is `50+`.
_MAX_ROWS: Final = 50
_WORST_FIRST: Final[Mapping[str, int]] = {"exceeded": 0, "unknown": 1, "ok": 2}
_ESTIMATOR = default_orchestration_config().type_estimator


class CardRobot(BaseModel):
    """No defaults (SOLUSDEV-326): a card cached before robots carried their visibility fails
    validation and is rebuilt, never shown to a member who may not see one of its robots."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: UUID
    name: str
    external_ref: str | None
    host_machine_id: str | None
    in_graph: bool
    onboarded_by: UUID | None

    def seen_by(self, viewer: UUID | None) -> bool:
        return self.in_graph or (viewer is not None and self.onboarded_by == viewer)


class CardSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    name: str
    capabilities: tuple[str, ...]


class ProjectCard(BaseModel):
    """What a `graph.changed` can change, cached as JSON; `render_card` caps every string."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    robots: tuple[CardRobot, ...]
    sources: tuple[CardSource, ...]
    #: Live `.solus` entries per section, and per subsection within it.
    solus: dict[str, int]
    subsections: dict[str, dict[str, int]]


class MachineBlock(BaseModel):
    """The caller's own machine, per request, never cached; every field redacted and capped."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hostname: str
    os: str
    arch: str
    tool_versions: tuple[tuple[str, str], ...]
    #: Newest first.
    recent_commands: tuple[dict[str, str], ...]


def _name(exc: BaseException) -> str:
    return type(exc).__name__


class ProjectCardCache:
    """Cards in the shared store (Redis when there is one) under `solus:project_card:<id>`."""

    def __init__(self, store: CacheStore, ttl: int = CACHE_TTL_SECONDS) -> None:
        self._store = store
        self._ttl = ttl

    @staticmethod
    def _key(project_id: UUID) -> str:
        return f"solus:project_card:{project_id}"

    async def get(self, project_id: UUID) -> ProjectCard | None:
        # M13 + round 2: a stalled or failing store is a miss, never a hung or failed turn
        # (`ResearchCache` treats its store the same); the class name only, never the message.
        try:
            raw = await within_bound(self._store.get(self._key(project_id)))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "project card read failed project=%s (%s); rebuilding", project_id, _name(exc)
            )
            return None
        if raw is None:
            return None
        try:
            return ProjectCard.model_validate_json(raw)
        except ValidationError:  # another deploy's shape: rebuild rather than fail the turn
            return None

    async def put(self, project_id: UUID, card: ProjectCard) -> None:
        try:
            await within_bound(
                self._store.set(self._key(project_id), card.model_dump_json(), self._ttl)
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "project card write failed project=%s (%s); not cached", project_id, _name(exc)
            )

    async def invalidate(self, project_id: UUID) -> None:
        try:
            await within_bound(self._store.delete(self._key(project_id)))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "project card invalidation failed project=%s (%s)", project_id, _name(exc)
            )

    def invalidator(self) -> Callable[[UUID], Awaitable[None]]:
        """The `graph.changed` callback `graph_changed_callbacks` registers."""
        return self.invalidate


@dataclass(frozen=True)
class CardInputs:
    """The route's layer-2 hand-off: the cache and catalog serve a miss; the rest is per request."""

    cache: ProjectCardCache
    connectors: ConnectorRegistry
    findings: Mapping[str, int]
    machine: MachineBlock | None
    active_device_ids: frozenset[str]
    budgets: str
    #: The caller: a robot out of the graph renders on its onboarder's card alone.
    viewer_id: UUID | None = None
    #: SOLUSDEV-326 — the caller's own, never in the shared cache: devices plugged into their
    #: machine now that nothing they may see binds and they have not dismissed, and the oldest
    #: card waiting for them here.
    devices: tuple[str, ...] = ()
    open_card: str | None = None


async def build_project_card(
    session: AsyncSession, project_id: UUID, *, catalog: Sequence[Mapping[str, Any]]
) -> ProjectCard:
    """Every read scoped to `project_id`; a source can do what its type's catalog row declares.
    The card is every member's (one cache per project): it lists every robot with its visibility
    for `render_card` to filter, and counts only the `.solus` entries every member may see."""
    capabilities = {str(row["type"]): tuple(row["capabilities"]) for row in catalog}
    host = GraphEntity.attrs["host_machine_id"].astext
    hidden = GraphEntity.attrs.contains({IN_GRAPH: False})
    onboarder = GraphEntity.attrs[ONBOARDED_BY].astext
    robots = await session.execute(
        select(GraphEntity.id, GraphEntity.name, GraphEntity.external_ref, host, hidden, onboarder)
        .where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.PHYSICAL_ROBOT,
            GraphEntity.deleted_at.is_(None),
        )
        .order_by(GraphEntity.name, GraphEntity.id)
        .limit(_MAX_ROWS)
    )
    sources = await session.execute(
        select(Source.type, Source.name)
        .where(Source.project_id == project_id, Source.revision_base_source_id.is_(None))
        .order_by(Source.created_at, Source.id)
        .limit(_MAX_ROWS)
    )
    solus, subsections = _solus_counts(await load_sections(session, project_id, everyone=True))
    name = await session.scalar(select(Project.name).where(Project.id == project_id))
    return ProjectCard(
        name=name or "",
        robots=tuple(
            CardRobot(
                entity_id=entity_id,
                name=label,
                external_ref=ref,
                host_machine_id=machine,
                in_graph=not out,
                onboarded_by=UUID(by) if by else None,
            )
            for entity_id, label, ref, machine, out, by in robots.tuples()
        ),
        sources=tuple(
            CardSource(type=kind.value, name=label, capabilities=capabilities.get(kind.value, ()))
            for kind, label in sources.tuples()
        ),
        solus=solus,
        subsections=subsections,
    )


def _solus_counts(
    sections: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Entries per non-empty section, and per subsection (by name) where there are any."""
    totals = {section: len(entries) for section, entries in sections.items() if entries}
    detail = {
        section: dict(sorted(Counter(e["subsection"] for e in entries if e["subsection"]).items()))
        for section, entries in sections.items()
    }
    return totals, {section: counts for section, counts in detail.items() if counts}


async def _budget_text(session: AsyncSession, project_id: UUID) -> str:
    """The stored `constraints/budgets` lines, worst status first, as one capped line. Per
    request: the debounced recompute rewrites them without a `graph.changed`."""
    entry = await find_budgets_entry(session, project_id)
    if entry is None or entry.payload is None:
        return "no budgets"
    lines = sorted(
        Budgets.model_validate(entry.payload).budgets, key=lambda line: _WORST_FIRST[line.status]
    )
    return _capped("; ".join(_budget_line(line) for line in lines), _BUDGETS_CAP) or "no budgets"


def _budget_line(line: BudgetLine) -> str:
    amount = "/".join(
        "?" if value is None else f"{value:g}" for value in (line.current, line.limit)
    )
    return " ".join(part for part in (line.name, amount, line.unit, f"({line.status})") if part)


def owned_commands(
    attrs: Mapping[str, Any], user_id: UUID | None, *, limit: int
) -> tuple[dict[str, str], ...]:
    """The machine's `limit` (at least 1) newest recorded commands, newest first, each through
    `_command_fields` (redacted, capped) — for its owner alone. For anyone else, nothing: another
    member's commands are never returned, and are not even read (CLAUDE.md §7). The one reader of
    them, so the card, the first tier and the `get_machine` tool cannot disagree."""
    if not owns_machine(attrs, user_id):
        return ()
    history = attrs.get("recent_commands")
    commands = [c for c in history if isinstance(c, dict)] if isinstance(history, list) else []
    return tuple(_command_fields(c) for c in reversed(commands[-limit:]))


def tool_versions(attrs: Mapping[str, Any], *, limit: int) -> tuple[tuple[str, str], ...]:
    """The machine's reported tool versions, sorted by tool name, the first `limit`, as strings.
    The companion's own report and so untrusted: a caller redacts and caps before it renders."""
    versions = attrs.get("tool_versions")
    shown = sorted(versions.items())[:limit] if isinstance(versions, dict) else []
    return tuple((str(tool), str(version)) for tool, version in shown)


async def machine_block(
    session: AsyncSession, *, project_id: UUID, user_id: UUID, live: BridgeSession | None
) -> MachineBlock | None:
    """The machine the caller's LIVE bridge session in this project runs on, only when they own
    its row. A companion id is client-supplied: one claiming a teammate's machine gets None."""
    if live is None or live.project_id != project_id:
        return None
    machine = await find_machine(session, project_id, live.companion_instance_id)
    if machine is None or not owns_machine(machine.attrs, user_id):
        return None
    attrs = machine.attrs
    return MachineBlock(
        hostname=_capped(str(attrs.get("hostname") or machine.name), _NAME_CAP),
        os=_capped(str(attrs.get("os") or "?"), _NAME_CAP),
        arch=_capped(str(attrs.get("arch") or "?"), _NAME_CAP),
        tool_versions=tuple(
            (_capped(tool, _NAME_CAP), _capped(version, _NAME_CAP))
            for tool, version in tool_versions(attrs, limit=_MAX_TOOL_VERSIONS)
        ),
        recent_commands=owned_commands(attrs, user_id, limit=_MAX_COMMANDS),
    )


def _command_fields(entry: Mapping[str, Any]) -> dict[str, str]:
    """Text fields redacted and capped, the exit code when it is one; other keys ignored."""
    code = entry.get("exit_code")
    values = {
        "command_redacted": entry.get("command_redacted"),
        "cwd": entry.get("cwd"),
        "exit_code": str(code) if isinstance(code, int) and not isinstance(code, bool) else None,
        "output_tail": entry.get("output_tail"),
    }
    return {k: _capped(v, _COMMAND_FIELD_CAP) for k, v in values.items() if isinstance(v, str)}


async def card_inputs(
    session: AsyncSession,
    *,
    project_id: UUID,
    user_id: UUID,
    live: BridgeSession | None,
    cache: ProjectCardCache,
    sessions: SessionManager | None,
    connectors: ConnectorRegistry,
) -> CardInputs | None:
    """The per-request reads, or None — no card this turn — when one fails: logged, never raised
    into the message. `live` is the caller's own bridge session (the route's lookup of the
    server-derived scope); `sessions` is the bench session manager some apps lack."""
    try:
        active = sessions.list(project_id, status="active") if sessions is not None else []
        return CardInputs(
            cache=cache,
            connectors=connectors,
            findings=await count_findings_by_severity(session, project_id),
            machine=await machine_block(session, project_id=project_id, user_id=user_id, live=live),
            active_device_ids=frozenset(device for bench in active for device in bench.device_ids),
            budgets=await _budget_text(session, project_id),
            viewer_id=user_id,
            devices=await _waiting_devices(session, project_id, user_id),
            open_card=await _open_card_text(session, project_id, user_id),
        )
    except Exception:  # noqa: BLE001 — a card read must never fail the message
        logger.exception("project card inputs failed project=%s", project_id)
        return None


async def project_card_section(
    sessionmaker: async_sessionmaker[AsyncSession], project_id: UUID, inputs: CardInputs | None
) -> ContextSection | None:
    """The cached card (built on a miss) rendered with this request's inputs. None — "no project
    card" — without inputs (tests, other runners) or on a failure: logged, never raised."""
    if inputs is None:
        return None
    try:
        card = await inputs.cache.get(project_id)
        if card is None:
            async with sessionmaker() as session:
                card = await build_project_card(
                    session, project_id, catalog=inputs.connectors.catalog()
                )
            # ponytail: a graph.changed landing between that read and this put leaves a stale
            # card for up to the TTL; a per-project generation counter closes it if it matters.
            await inputs.cache.put(project_id, card)
        text = render_card(
            card,
            findings=inputs.findings,
            machine=inputs.machine,
            active_device_ids=inputs.active_device_ids,
            budgets=inputs.budgets,
            viewer=inputs.viewer_id,
            devices=inputs.devices,
            open_card=inputs.open_card,
        )
    except Exception:  # noqa: BLE001 — a missing card must never fail the turn
        logger.exception("project card failed project=%s", project_id)
        return None
    tokens = estimate_tokens(text, config=_ESTIMATOR)
    return ContextSection(kind="project_card", text=text, tokens=tokens, score=1.0)


def render_card(
    card: ProjectCard,
    *,
    findings: Mapping[str, int],
    machine: MachineBlock | None,
    active_device_ids: frozenset[str],
    budgets: str,
    viewer: UUID | None = None,
    devices: Sequence[str] = (),
    open_card: str | None = None,
) -> str:
    """Lines of DATA, at most CARD_MAX_TOKENS, every string redacted and capped. Over it, `.solus`
    subsection detail goes first, then source capabilities, then every robot and every source but
    the first (an active robot sorts first); what still overflows is clipped, oldest command
    last. A robot out of the graph is listed for its onboarder (`viewer`) alone; `devices` and
    `open_card` are that viewer's own (`CardInputs`)."""
    visible = [robot for robot in card.robots if robot.seen_by(viewer)]
    ordered = sorted(visible, key=lambda robot: robot.external_ref not in active_device_ids)
    robots = [_robot_text(robot, active_device_ids) for robot in ordered]
    text = ""
    for dropped in range(4):
        sources = [_source_text(source, capabilities=dropped < 2) for source in card.sources]
        shown = 1 if dropped > 2 else None
        text = "\n".join(
            (
                f"project: {_capped(card.name, _NAME_CAP)}",
                _findings_line(findings),
                f"budgets: {_capped(budgets, _BUDGETS_CAP)}",
                _listing("robots", robots, shown),
                _listing("sources", sources, shown),
                _solus_line(card, subsections=dropped < 1),
                *_waiting_lines(devices, open_card),
                *_machine_lines(machine),
            )
        )
        if estimate_tokens(text, config=_ESTIMATOR) <= CARD_MAX_TOKENS:
            return text
    return text[: chars_for_tokens(CARD_MAX_TOKENS, config=_ESTIMATOR) - 1] + "…"


def _capped(value: str, cap: int) -> str:
    """Redacted, then clipped: a secret cut in half no longer reads as one."""
    text = redact_text(value)
    return text if len(text) <= cap else text[: cap - 1] + "…"


def _findings_line(findings: Mapping[str, int]) -> str:
    counts = ", ".join(f"{_capped(name, _NAME_CAP)} {n}" for name, n in sorted(findings.items()))
    return f"open findings: {counts or 'none'}"


def _listing(label: str, items: Sequence[str], shown: int | None) -> str:
    """`label (N): a; b; +K more` — N reads `50+` when the read hit its row limit."""
    if not items:
        return f"{label}: none"
    count = f"{len(items)}+" if len(items) >= _MAX_ROWS else str(len(items))
    kept = items[:shown]
    more = f"; +{len(items) - len(kept)} more" if len(kept) < len(items) else ""
    return f"{label} ({count}): {'; '.join(kept)}{more}"


def _robot_text(robot: CardRobot, active: frozenset[str]) -> str:
    state = " [bench session active]" if robot.external_ref in active else ""
    known = (
        ("id", str(robot.entity_id)),
        ("ref", robot.external_ref),
        ("host", robot.host_machine_id),
    )
    facts = ", ".join(f"{label} {_capped(value, _NAME_CAP)}" for label, value in known if value)
    return f"{_capped(robot.name, _NAME_CAP)}{state} ({facts})"


def _source_text(source: CardSource, *, capabilities: bool) -> str:
    text = f'{_capped(source.type, _NAME_CAP)} "{_capped(source.name, _NAME_CAP)}"'
    if capabilities and source.capabilities:
        text += " [" + ", ".join(_capped(c, _NAME_CAP) for c in source.capabilities) + "]"
    return text


def _solus_line(card: ProjectCard, *, subsections: bool) -> str:
    if not card.solus:
        return ".solus: no entries"
    parts = []
    for section, count in card.solus.items():
        detail = card.subsections.get(section) if subsections else None
        inner = ", ".join(f"{_capped(name, _NAME_CAP)} {n}" for name, n in (detail or {}).items())
        label = f"{_capped(section, _NAME_CAP)} {count}"
        parts.append(f"{label} ({inner})" if inner else label)
    return ".solus: " + "; ".join(parts)


def _waiting_lines(devices: Sequence[str], open_card: str | None) -> list[str]:
    lines = []
    if devices:
        shown = "; ".join(_capped(device, _DEVICE_CAP) for device in devices)
        lines.append(f"plugged into this person's machine, not added or dismissed: {shown}")
    if open_card is not None:
        lines.append(f"card waiting for this person: {_capped(open_card, _COMMAND_FIELD_CAP)}")
    return lines


async def _waiting_devices(
    session: AsyncSession, project_id: UUID, user_id: UUID
) -> tuple[str, ...]:
    """`headline ("device ref")` for each device a machine `user_id` owns here remembers as
    plugged in now, that nothing they may see binds and they did not dismiss — the device
    memory, the machine owner's alone (`hardware/device_memory.py`)."""
    from solus_api.agent.cards import single_line
    from solus_api.hardware import device_memory
    from solus_api.hardware.device_memory import annotate

    machines = await session.scalars(
        select(GraphEntity).where(
            GraphEntity.project_id == project_id,
            GraphEntity.kind == kinds.MACHINE,
            GraphEntity.deleted_at.is_(None),
        )
    )
    waiting: list[str] = []
    for machine in machines:
        if not owns_machine(machine.attrs, user_id):
            continue  # a teammate's machine is never read for this person
        present = [
            row
            for row in machine.attrs.get("devices") or []
            if isinstance(row, Mapping) and row.get("present") is True and row.get("device_ref")
        ]
        context = await device_memory.device_context(session, project_id, present, machine)
        # A serial-basis ref is the device's own USB serial: one printable line, JSON-quoted as
        # data, exactly as a notice says it (`routers/sol_notice.py`).
        waiting += [
            f"{single_line(row.get('headline') or '', _LABEL_CAP) or 'a device'} "
            f"({json.dumps(single_line(row['device_ref'], _REF_CAP))})"
            for row in annotate(present, context, user_id)
            if row["bound_to"] is None and not row["dismissed"]
        ]
    return tuple(waiting[:_MAX_WAITING])


async def _open_card_text(session: AsyncSession, project_id: UUID, user_id: UUID) -> str | None:
    """The oldest card waiting for `user_id` here — the one the slot shows
    (`cards.oldest_showable_card`) — and the count."""
    from solus_api.agent.cards import oldest_showable_card

    found = await oldest_showable_card(session, project_id, user_id)
    if found is None:
        return None
    row, card, total = found
    more = f"; {total - 1} more waiting" if total > 1 else ""
    return f"{card.title} ({row.tool}, {card.kind}){more}"


def _machine_lines(machine: MachineBlock | None) -> list[str]:
    if machine is None:
        return []
    tools = ", ".join(
        f"{_capped(tool, _NAME_CAP)} {_capped(version, _NAME_CAP)}"
        for tool, version in machine.tool_versions
    )
    where = f"{_capped(machine.os, _NAME_CAP)}/{_capped(machine.arch, _NAME_CAP)}"
    head = f"this person's machine: {_capped(machine.hostname, _NAME_CAP)} ({where})"
    lines = [f"{head}; tools: {tools}" if tools else head]
    if machine.recent_commands:
        lines.append("recent commands on it, newest first:")
        lines += [
            "- "
            + ", ".join(
                f"{_capped(key, _NAME_CAP)}: {_capped(value, _COMMAND_FIELD_CAP)}"
                for key, value in command.items()
            )
            for command in machine.recent_commands
        ]
    return lines
