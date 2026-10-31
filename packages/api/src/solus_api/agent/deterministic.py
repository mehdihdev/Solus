"""SOLUSDEV-321 P1-T2 — SOL's first tier: a lookup the facts answer takes no model call.

`answer_first_tier` runs after the scope planner and before any prompt renders. It matches the
message against `INTENTS` — eleven shapes, each a pattern the whole message must match and a
handler — and answers from the planned scope (`TurnScope.graph`, the ONE pull) and the
`FactSources` seams (`agent/deterministic_facts.py`, every read scoped to the project). Nothing
here calls a model (tests/test_model_call_sites.py, comments included). It never guesses: a name
two entities in scope hold (`turn_scope.term_in_name`), a cut graph, a quantity or unit it does
not know, or a fact nobody stated returns None, and the turn falls through to the model with the
same scope. Expert mode gets the fact alone; Guide mode gets it and one fixed sentence on where
it comes from (`_GUIDE_NOTES`, CLAUDE.md §2 item 5).

What it renders is the project's data, so every ingested string passes `_quote_name` (control
and format characters out first, then redacted, backticks out, at most 80 characters, inline
code: never a fence, never a command); a citation is a fixed kind over ids, kept only when it
fullmatches `reason._CITATION_RE`; and a conversion takes its magnitude by `float()` of a
regex-matched number and a unit only when it fullmatches `_UNIT_TOKEN`, then `parse_units` —
message text never reaches pint's evaluator.
"""

from __future__ import annotations

import functools
import logging
import math
import re
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from traceback import walk_tb
from typing import Final, NamedTuple
from unicodedata import category

import pint
from solus_contracts.relations import EvidenceKind, RelationType

from solus_api.agent.context import _graph_section
from solus_api.agent.deterministic_facts import FactSources as FactSources  # re-export: runtime.py
from solus_api.agent.deterministic_facts import contents_of, robot_of
from solus_api.agent.interfaces import EdgeRead, EntityRead
from solus_api.agent.reason import _CITATION_RE
from solus_api.agent.stream import AgentEvent
from solus_api.agent.tools.untrusted import redact_text
from solus_api.agent.turn_scope import TurnScope, term_in_name
from solus_api.graph import kinds
from solus_api.models import SolMode

logger = logging.getLogger("solus.agent.deterministic")

#: Longer than this is no lookup: the pattern scan stays bounded whatever the message.
MAX_LOOKUP_CHARS: Final = 200
#: How many items one answer names before "+N more".
_LISTED: Final = 8
_NAME_CAP: Final = 80
#: A unit the person may name and pint may parse: letters (µ, Ω and ° among them) joined by `*`,
#: `/` or `·`. No digit, space, bracket or `**`: nothing pint could evaluate as an expression.
_UNIT_TOKEN: Final = re.compile(r"[A-Za-zµΩ°]+([*/·][A-Za-zµΩ°]+){0,3}")
#: Unicode categories a quoted name drops: controls (newlines among them), format characters
#: (bidi overrides, zero-width marks) and line and paragraph separators.
_INVISIBLE: Final = frozenset({"Cc", "Cf", "Zl", "Zp"})
_LEADING: Final = re.compile(r"^(?:(?:the|a|an|my|our|this|that)\s+)+", re.IGNORECASE)
#: A signal name a telemetry citation may carry; any other cites the part instead.
_SIGNAL_NAME: Final = re.compile(r"[A-Za-z0-9._-]+")
#: What a list read cut at its first rows says when more exist.
_OLDER: Final = ", and older ones"
_SEVERITIES: Final = frozenset({"info", "warning", "critical"})
_EVIDENCE_KINDS: Final = frozenset(kind.value for kind in EvidenceKind)
_BUS_RELATIONS: Final = frozenset(
    {RelationType.DRIVES.value, RelationType.HARDWARE_CONNECTED_TO.value}
)
_WHERE: Final = {
    "config": "hardware config",
    "definition": "part definition",
    "scene": "scene model",
}
#: Nodes that describe another entity — its config, a finding or a `.solus` entry about it, a
#: proposal for it — or the project's notes, and often carry an entity's name.
_DESCRIBING: Final = kinds.DESCRIPTOR_KINDS | {
    kinds.FINDING, kinds.DOCUMENT, kinds.SOLUS_CONFIG, kinds.SOLUS_SECTION,
    kinds.SOLUS_SUBSECTION, kinds.SOLUS_NOTE, kinds.SOLUS_ERROR, kinds.SOLUS_GOAL,
    kinds.SOLUS_CONSTRAINT, kinds.SOLUS_PROJECT_TOML,
}  # fmt: skip
#: Guide mode's one sentence per answer source: what the source is and where it is set. Fixed
#: Solus text: never an ingested string, never a number.
_GUIDE_NOTES: Final[Mapping[str, str]] = {
    "config": "This comes from the part's hardware config, set in the robot's hardware settings.",
    "definition": "This comes from the part's library definition: its model's datasheet values.",
    "scene": "This comes from the joint range in the robot's scene model.",
    "graph": "This comes from the relations in your project graph, kept current by each sync.",
    "telemetry": "This is the newest sample the Live Bench received from the robot.",
    "finding": "Findings come from Solus's checks; open one to see its evidence or resolve it.",
    "solus": "These are entries in the errors section of the project's .solus notes.",
    "history": "This comes from the project history, which records each graph and config change.",
    "machine": "This comes from the record the companion app keeps for each of your machines.",
    "session": "Bench sessions are started and stopped from the Live Bench.",
    "budgets": "Budgets weigh each rail's loads against its supplies' ratings, from the graph.",
    "divergences": "This compares your machine's installed packages with the environment spec.",
    "count": "This counts what the project graph holds around your question, not what is shown.",
    "unit": "This is unit arithmetic alone: nothing in your project was read.",
}
#: The shapes whose note is not their answer's first source.
_SHAPE_NOTES: Final[Mapping[str, str]] = {"count": "count", "conversion": "unit"}
#: A generic noun counts a kind; any other noun counts the names that hold it.
_PARTS: Final = frozenset({kinds.PART, kinds.COMPONENT})
_COUNTED_KINDS: Final[Mapping[str, frozenset[str]]] = {
    "part": _PARTS, "component": _PARTS, "bus": frozenset({kinds.HARDWARE_BUS}),
    "robot": frozenset({kinds.PHYSICAL_ROBOT}), "file": frozenset({kinds.CODE_FILE}),
    "machine": frozenset({kinds.MACHINE}),
}  # fmt: skip


@dataclass(frozen=True)
class DeterministicAnswer:
    """A first-tier answer: its text, the citations it was built from, and the fact sources it
    read (`config`, `definition`, `scene`, `graph`, `telemetry`, `finding`, `solus`, `budgets`,
    `divergences`, `history`, `machine`, `session`)."""

    text: str
    citations: tuple[str, ...]
    sources: tuple[str, ...]


Match = re.Match[str]
Answer = DeterministicAnswer | None
Handler = Callable[[Match, TurnScope, FactSources], Awaitable[Answer]]


class Intent(NamedTuple):
    """One shape: a name for the logs, the pattern a whole normalized message must match, and
    the handler that answers it from facts."""

    name: str
    pattern: re.Pattern[str]
    handler: Handler


class _Limit(NamedTuple):
    label: str
    keys: tuple[str, ...]
    unit: str | None


#: The seams a failed read is logged under (the Protocol's methods).
_SEAMS: Final = frozenset(name for name in vars(FactSources) if not name.startswith("_"))


async def answer_first_tier(
    message: str, scope: TurnScope, facts: FactSources, *, mode: SolMode
) -> Answer:
    """The answer to `message` from facts, or None — the turn goes to the model. Only the first
    shape whose pattern the whole message matches is tried. A failed read declines like a
    missing fact: the first tier never fails a turn. Guide mode adds the answer's one fixed
    note on where the fact comes from; Expert gets the fact alone."""
    text = " ".join(message.split()).rstrip("?!. ")
    if not text or len(text) > MAX_LOOKUP_CHARS:
        return None
    for intent in INTENTS:
        match = intent.pattern.fullmatch(text)
        if match is None:
            continue
        try:
            answer = await intent.handler(match, scope, facts)
        except Exception as exc:  # a failed read declines: the model answers instead
            _log_failed_read(exc, intent.name, facts.project_id)
            return None
        return _guided(answer, intent.name) if answer and mode is SolMode.GUIDE else answer
    return None


def _guided(answer: DeterministicAnswer, shape: str) -> DeterministicAnswer:
    note = _GUIDE_NOTES[_SHAPE_NOTES.get(shape) or answer.sources[0]]
    return replace(answer, text=f"{answer.text} {note}")


def _log_failed_read(exc: Exception, shape: str, project_id: uuid.UUID) -> None:
    """The seam the read failed in (the shape when no seam is on the traceback), the
    exception's type and the project: never its message or the traceback, which may carry
    the project's data."""
    frames = (frame.f_code.co_name for frame, _ in walk_tb(exc.__traceback__))
    seam = next((name for name in frames if name in _SEAMS), shape)
    logger.warning(
        "first tier declined: %s read failed (%s) project=%s",
        seam,
        type(exc).__name__,
        project_id,
    )


def first_tier_events(answer: DeterministicAnswer, scope: TurnScope) -> tuple[AgentEvent, ...]:
    """What the runner streams for an answered turn: the manifest (the scope's anchors; the
    graph the first tier read is the one layer — nothing was packed), `answer_source`, then the
    message. No tool frame: nothing was called, so no tool turn is recorded or counted."""
    graph = _graph_section(scope.graph)
    return (
        AgentEvent.context_used(
            sections=[{"kind": graph.kind, "citation": graph.citation, "tokens": graph.tokens}],
            truncated=scope.graph.truncated,
            dropped=0,
            layers=[
                {"layer": "graph", "tokens": graph.tokens, "sections": 1, "empty_reason": None}
            ],
            anchors=[{"id": str(a.id), "reason": a.reason} for a in scope.anchors],
            anchors_dropped=[
                {"id": str(a.id), "reason": a.reason, "cause": a.cause} for a in scope.dropped
            ],
        ),
        AgentEvent.answer_source("graph", sources=answer.sources, citations=answer.citations),
        AgentEvent.message(answer.text, citations=answer.citations),
    )


# ------------------------------------------------------------------------ shapes

_POSITION: Final = _Limit("Position limits", ("position_min", "position_max"), None)
#: Position limits stored with their unit: `position_min_deg` / `position_max_deg`.
_SUFFIXED: Final = ("position_min_", "position_max_")
_LIMITS: Final[Mapping[str, _Limit]] = {
    "stall current": _Limit("Stall current", ("stall_current_a",), "A"),
    "current limit": _Limit("Current limit", ("current_a",), "A"),
    "rated current": _Limit("Current limit", ("current_a",), "A"),
    "max current": _Limit("Current limit", ("current_a",), "A"),
    "temperature limit": _Limit("Temperature limit", ("temp_c",), "degC"),
    "max temperature": _Limit("Temperature limit", ("temp_c",), "degC"),
    "min voltage": _Limit("Minimum voltage", ("voltage_min_v",), "V"),
    "max voltage": _Limit("Maximum voltage", ("voltage_max_v",), "V"),
    "max torque": _Limit("Maximum torque", ("torque_nm",), "N*m"),
    "position limit": _POSITION,
    "joint limit": _POSITION,
}


async def _limit(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """What is the stall current of servo 3 (in mA)? Config, definition, then scene joint."""
    entity = _subject(match["subject"], scope, facts)
    limit = _LIMITS[_phrase(match["quantity"])]
    found = await _stated_limit(entity, limit, facts) if entity is not None else None
    if entity is None or found is None:
        return None
    values, unit, source, citation = found
    if match["unit"] is not None:
        converted = [_in_unit(value, unit, match["unit"]) for value in values]
        values = tuple(value for value in converted if value is not None)
        if len(values) != len(converted):
            return None
        unit = match["unit"]
    text = (
        f"{limit.label} of {_quote_name(entity.name)}: {_range_text(values, unit)} "
        f"(its {_WHERE[source]})."
    )
    return _answered(text, [citation], (source,))


async def _stated_limit(
    entity: EntityRead, limit: _Limit, facts: FactSources
) -> tuple[tuple[float, ...], str | None, str, str | None] | None:
    """(values, unit, source, citation) from the first source that states every key. Position
    limits the config holds only under unit suffixes it cannot read decline outright."""
    configured = await facts.part_limits(entity)
    found = _config_reading(configured, limit)
    if found is not None:
        return *found, "config", _cite("config", entity.id)
    if limit is _POSITION and any(key.startswith(_SUFFIXED) for key in configured):
        return None
    definition = await facts.definition(entity)
    stated = definition.limits if definition is not None else None
    values = _stated([getattr(stated, key, None) for key in limit.keys])
    if values is not None:
        return values, limit.unit, "definition", _cite("entity", entity.id)
    joint = await facts.scene_joint(entity) if limit is _POSITION else None
    if joint is not None:
        return (joint.lower, joint.upper), joint.unit, "scene", _cite("entity", joint.scene_id)
    return None


async def _latest(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """What is the latest current of servo 3? The newest buffered sample of its channel."""
    entity = _subject(match["subject"], scope, facts)
    quantity = "_".join(match["quantity"].lower().split())
    reading = await facts.latest(entity, quantity) if entity is not None else None
    if entity is None or reading is None:
        return None
    value, unit = reading.value, _unit(reading.unit)
    if match["unit"] is not None:
        converted = _in_unit(value, unit, match["unit"])
        if converted is None:
            return None
        value, unit = converted, match["unit"]
    text = (
        f"Latest {quantity.replace('_', ' ')} of {_quote_name(entity.name)}: "
        f"{_range_text((value,), unit)} at {_when(reading.at)} "
        f"(signal {_quote_name(reading.signal)})."
    )
    citation = (
        _cite("telemetry", entity.id, reading.signal)
        if _SIGNAL_NAME.fullmatch(reading.signal)
        else _cite("entity", entity.id)
    )
    return _answered(text, [citation], ("telemetry",))


async def _related(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """What commands actuator 5? The fact edges of that relation into it, with evidence."""
    graph = facts.edges(scope)
    target = _subject(match["subject"], scope, facts)
    if target is None:
        return None
    relation = match["relation"].lower()
    named = {entity.id: entity for entity in graph.entities}
    edges = sorted(
        (
            edge
            for edge in graph.edges
            if edge.relation_type == relation and edge.dst_id == target.id and edge.src_id in named
        ),
        key=lambda edge: (named[edge.src_id].name, str(edge.src_id)),
    )
    said = [
        f"{_quote_name(named[edge.src_id].name)} {relation} {_quote_name(target.name)}"
        + _evidence_note(edge)
        for edge in edges[:_LISTED]
    ]
    citations = [*(_cite("entity", edge.src_id) for edge in edges[:_LISTED])]
    text = "; ".join(said) + _more(len(edges)) + "."
    return _answered(text, [*citations, _cite("entity", target.id)], ("graph",)) if edges else None


async def _pins(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Which pins on the brain support PWM? The part definition's pins."""
    entity = _subject(match["subject"], scope, facts)
    definition = await facts.definition(entity) if entity is not None else None
    if entity is None or definition is None or definition.pins is None:
        return None
    capability = match["capability"].lower()
    pins = [pin.name for pin in definition.pins if capability in pin.capabilities]
    where = f"(its part definition, {len(definition.pins)} pins)"
    listed = ", ".join(_quote_name(pin) for pin in pins[:_LISTED]) + _more(len(pins))
    name = _quote_name(entity.name)
    text = (
        f"{capability.upper()} pins on {name}: {listed} {where}."
        if pins
        else f"No pin on {name} supports {capability.upper()} {where}."
    )
    return _answered(text, [_cite("entity", entity.id)], ("definition",))


async def _bus(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Which bus is servo 3 on? The one bus in scope that drives it."""
    graph = facts.edges(scope)
    part = _subject(match["subject"], scope, facts)
    buses = {entity.id: entity for entity in graph.entities if entity.kind == kinds.HARDWARE_BUS}
    on = {
        edge.src_id
        for edge in graph.edges
        if part is not None
        and edge.dst_id == part.id
        and edge.src_id in buses
        and edge.relation_type in _BUS_RELATIONS
    }
    if part is None or len(on) != 1:
        return None
    (bus_id,) = on
    text = f"{_quote_name(part.name)} is on bus {_quote_name(buses[bus_id].name)}."
    return _answered(text, [_cite("entity", bus_id), _cite("entity", part.id)], ("graph",))


async def _host(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Which machine is the arm on? Its robot's host; the last command only for the owner."""
    graph = facts.edges(scope)
    robot = robot_of(_subject(match["subject"], scope, facts), graph)
    host = robot.attrs.get("host_machine_id") if robot is not None else None
    machine = await facts.machine(host) if isinstance(host, str) and host else None
    if robot is None or machine is None:
        return None
    text = (
        f"{_quote_name(robot.name)} runs on machine {_quote_name(machine.hostname)} "
        f"({_quote_name(machine.os)}/{_quote_name(machine.arch)})."
    )
    if machine.recent_commands:
        newest = machine.recent_commands[0]
        code = newest.get("exit_code")
        text += f" Its last command: {_quote_name(newest.get('command_redacted', '?'))}"
        text += f" (exit {code})." if code is not None else "."
    return _answered(text, [_cite("entity", machine.id)], ("machine",))


async def _conversion(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Convert 2.5 A to mA: arithmetic on a number and two unit tokens; nothing to cite."""
    value = float(match["number"])
    converted = _in_unit(value, match["source"], match["target"])
    if converted is None:
        return None
    text = f"{_amount(value)} {match['source']} = {_amount(converted)} {match['target']}."
    return _answered(text, (), ())


async def _budget(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Can the 5V rail run the load? The stored power budget of the one rail named."""
    budgets = await facts.budgets()
    rail = _term(match["rail"])
    lines = [
        line
        for line in (budgets.lines if budgets is not None else ())
        if line.name.startswith("power:") and term_in_name(rail, line.name.removeprefix("power:"))
    ]
    line = lines[0] if len(lines) == 1 else None
    if budgets is None or line is None or line.current is None or line.limit is None:
        return None
    if line.status == "unknown":  # the graph leaves the load or the rating unstated
        return None
    net, unit = _quote_name(line.name.removeprefix("power:")), _unit(line.unit)
    load, rating = _range_text((line.current,), unit), _range_text((line.limit,), unit)
    verdict = (
        f"Yes: the {net} rail's load is {load} of its {rating} rating"
        if line.status == "ok"
        else f"No: the {net} rail's load is {load}, over its {rating} rating"
    )
    return _answered(
        f"{verdict} (budgets computed {_when(budgets.computed_at)}).",
        [_cite("solus", "constraints", budgets.entry_id)],
        ("budgets",),
    )


async def _findings(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Any open findings on servo 2? None found is the answer too; a cut list says so."""
    entity = _subject(match["subject"], scope, facts)
    if entity is None:
        return None
    page = await facts.findings(entity.id)
    name = _quote_name(entity.name)
    if not page.rows:
        return _answered(f"No open findings on {name}.", [_cite("entity", entity.id)], ("finding",))
    listed = "; ".join(
        f"{_quote_name(finding.headline)} "
        f"({finding.severity if finding.severity in _SEVERITIES else 'unrated'})"
        for finding in page.rows
    )
    return _answered(
        f"Open findings on {name}: {listed}{_OLDER if page.more else ''}.",
        [_cite("finding", finding.id) for finding in page.rows],
        ("finding",),
    )


async def _errors(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Any errors on servo 2? The `.solus` errors that blame it."""
    entity = _subject(match["subject"], scope, facts)
    found = await facts.errors(entity.id) if entity is not None else ()
    if entity is None:
        return None
    name = _quote_name(entity.name)
    if not found:
        return _answered(
            f"No `.solus` errors blame {name}.", [_cite("entity", entity.id)], ("solus",)
        )
    listed = "; ".join(
        f"{_quote_name(error.text)} ({error.status}, seen {error.count}×)"
        for error in found[:_LISTED]
    )
    return _answered(
        f"`.solus` errors blaming {name}: {listed}{_more(len(found))}.",
        [_cite("solus", "errors", error.id) for error in found[:_LISTED]],
        ("solus",),
    )


async def _history(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """What changed on servo 2 in the last 2 hours? The project history rows naming it."""
    entity = _subject(match["subject"], scope, facts)
    if entity is None:
        return None
    since = _since(match)
    page = await facts.history(since, entity.id)
    name = _quote_name(entity.name)
    window = f" since {_when(since)}" if since is not None else ""
    listed = "; ".join(f"{_quote_name(row.type)} at {_when(row.at)}" for row in page.rows)
    text = (
        f"History of {name}{window}, newest first: {listed}{_OLDER if page.more else ''}."
        if page.rows
        else f"Nothing in the project history names {name}{window}."
    )
    return _answered(text, [_cite("entity", entity.id)], ("history",))


async def _here(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Will it run here? The asker's one machine in the stored divergences table."""
    table = await facts.divergences()
    if table is None or len(table.machines) != 1:
        return None
    (machine,) = table.machines
    host, when = _quote_name(machine.hostname), _when(table.computed_at)
    causes = [
        f"{group.cause.replace('_', ' ')} "
        + ", ".join(_quote_name(item.name) for item in group.items[:_LISTED])
        + _more(len(group.items))
        for group in machine.causes
        if group.items
    ]
    text = (
        f"{host} diverges from the environment spec: {'; '.join(causes)} (computed {when})."
        if causes
        else f"No divergence from the environment spec on {host} (computed {when})."
    )
    return _answered(text, [_cite("solus", "environment", table.entry_id)], ("divergences",))


async def _status(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """Is the arm running? The bench sessions streaming its device ref."""
    robot = _subject(match["subject"], scope, facts)
    if robot is None or robot.kind != kinds.PHYSICAL_ROBOT:
        return None
    sessions = await facts.sessions(robot)
    if sessions is None:
        return None
    name, citations = _quote_name(robot.name), [_cite("entity", robot.id)]
    if not sessions:
        return _answered(f"{name} has no active bench session.", citations, ("session",))
    newest = max(sessions, key=lambda bench: bench.created_at)
    others = f"; {len(sessions)} active in all" if len(sessions) > 1 else ""
    text = (
        f"{name} is live: {_quote_name(newest.label)}, a {newest.mode} bench session "
        f"({_quote_name(newest.provider)}) since {_when(newest.created_at)}{others}."
    )
    return _answered(text, citations, ("session",))


async def _count(match: Match, scope: TurnScope, facts: FactSources) -> Answer:
    """How many servos does the arm have? Counted in the planned scope, never from a render
    (`TurnScope.counting`), inside the named holder when there is one."""
    graph = facts.edges(scope)
    named = match["owner"] or match["container"]
    holder = _subject(named, scope, facts) if named else None
    if not scope.counting or graph.truncated or (named and holder is None):
        return None
    pool = _things(contents_of(holder, graph) if holder is not None else graph.entities)
    noun = _singular(match["noun"])
    counted = sorted(
        (entity for entity in pool if _is_a(noun, entity)),
        key=lambda entity: (entity.name, str(entity.id)),
    )
    if not counted:
        return None
    where = f" in {_quote_name(holder.name)}" if holder is not None else " in this turn's scope"
    listed = ", ".join(_quote_name(entity.name) for entity in counted[:_LISTED])
    shown = [holder] if holder is not None else counted[:_LISTED]
    return _answered(
        f"{len(counted)} {match['noun'].lower()}{where}: {listed}{_more(len(counted))}.",
        [_cite("entity", entity.id) for entity in shown],
        ("graph",),
    )


# ---------------------------------------------------------------------- patterns

_NAME: Final = r"(?P<subject>.{1,80}?)"
_OF: Final = r"\s+(?:of|for|on)\s+"
_UNIT: Final = r"(?:\s+in\s+(?P<unit>\S{1,24}))?"
_WHAT: Final = r"(?:what(?:'s|\s+is|\s+are)\s+)?(?:the\s+)?"
_WHICH: Final = r"(?:which|what)\s+"
_ANY: Final = r"(?:(?:are\s+there|any)\s+)?"
_QUANTITY: Final = (
    r"(?P<quantity>stall\s+current|current\s+limit|rated\s+current|max(?:imum)?\s+current"
    r"|temperature\s+limit|max(?:imum)?\s+temperature|min(?:imum)?\s+voltage"
    r"|max(?:imum)?\s+voltage|max(?:imum)?\s+torque|(?:position|joint)\s+limits?)"
)
_SIGNAL: Final = r"(?P<quantity>commanded\s+position|position|current|temperature|voltage)"
_RELATION: Final = r"(?P<relation>commands|drives|reads|powers)"
_CAPABILITY: Final = r"(?P<capability>pwm|adc|dac|i2c|spi|uart|can|gpio)"
_SUPPORTS: Final = r"\s+(?:are|support|supports|can\s+do|do)\s+"
_RAIL: Final = r"(?P<rail>.{1,40}?)\s+(?:rail|supply|power\s+supply|regulator)"
_POWERS: Final = r"(?:run|power|supply|handle|carry|support|drive)"
_LOAD: Final = (
    r"(?:(?:the|this|that|my|our|all(?:\s+the)?)\s+)?"
    r"(?:load|loads|servos|motors|actuators|arm|robot|everything|it|them|parts)"
)
_SINCE: Final = (
    r"(?:\s+(?:since\s+(?P<since>yesterday|today)"
    r"|in\s+the\s+last\s+(?P<count>\d{1,3})\s+(?P<span>hours?|days?)))?"
)
_IT: Final = r"(?:it|this|that|my\s+code|the\s+(?:code|project|build|firmware))"
_HOLDER: Final = (
    r"(?:\s+(?:are\s+there|(?:does|do)\s+(?P<owner>.{1,80}?)\s+have"
    r"|(?:are\s+)?(?:in|on)\s+(?P<container>.{1,80}?)))?"
)
_NUMBER: Final = r"(?P<number>[-+]?\d{1,9}(?:\.\d{1,9})?)"
_UNITS: Final = r"\s*(?P<source>\S{1,24}?)\s+(?:in|to|into)\s+(?P<target>\S{1,24})"
_PINS_OF: Final = r"\s+pins\s+(?:does|do|are\s+on)\s+"
_ON: Final = r"\s+(?:on|connected\s+to|attached\s+to|plugged\s+into)"
_ABOUT: Final = r"\s+(?:on|for|about|with)\s+"
_HERE: Final = r"\s+(?:run|work|build)\s+(?:here|on\s+(?:this|my)\s+machine)"
_LIVE: Final = r"\s+(?:running|live|connected|streaming|online)"

#: The eleven shapes, some spelled two ways, tried in order; the first full match decides.
INTENTS: Final[tuple[Intent, ...]] = tuple(
    Intent(name, re.compile(pattern, re.IGNORECASE), handler)
    for name, handler, pattern in (
        ("limit", _limit, rf"{_WHAT}{_QUANTITY}{_OF}{_NAME}{_UNIT}"),
        ("latest", _latest, rf"{_WHAT}(?:latest|current|last|live)\s+{_SIGNAL}{_OF}{_NAME}{_UNIT}"),
        ("relation", _related, rf"(?:what|which(?:\s+\w+)?)\s+{_RELATION}\s+{_NAME}"),
        ("pins", _pins, rf"{_WHICH}pins\s+(?:on|of)\s+{_NAME}{_SUPPORTS}{_CAPABILITY}"),
        ("pins", _pins, rf"{_WHICH}{_CAPABILITY}{_PINS_OF}{_NAME}(?:\s+have)?"),
        ("bus", _bus, rf"{_WHICH}bus\s+is\s+{_NAME}{_ON}"),
        ("machine", _host, rf"{_WHICH}machine\s+is\s+{_NAME}{_ON}"),
        ("machine", _host, rf"{_WHICH}machine\s+(?:hosts|runs)\s+{_NAME}"),
        ("budget", _budget, rf"can\s+(?:the\s+|my\s+|our\s+)?{_RAIL}\s+{_POWERS}\s+{_LOAD}"),
        ("findings", _findings, rf"{_ANY}(?:open\s+)?findings{_ABOUT}{_NAME}"),
        ("errors", _errors, rf"{_ANY}(?:recorded\s+|logged\s+)?errors{_ABOUT}{_NAME}"),
        ("history", _history, rf"what\s+changed\s+(?:on|in|for|with)\s+{_NAME}{_SINCE}"),
        ("history", _history, rf"(?:show\s+(?:me\s+)?)?(?:the\s+)?history\s+(?:of|for)\s+{_NAME}"),
        ("here", _here, rf"(?:will|would|does|can)\s+{_IT}{_HERE}"),
        ("status", _status, rf"(?:is|are)\s+(?:the\s+)?{_NAME}{_LIVE}"),
        ("status", _status, rf"what(?:'s|\s+is)\s+the\s+status\s+of\s+{_NAME}"),
        ("count", _count, rf"how\s+many\s+(?P<noun>[a-z]{{2,24}}){_HOLDER}"),
        ("conversion", _conversion, rf"(?:convert\s+|what(?:'s|\s+is)\s+)?{_NUMBER}{_UNITS}"),
    )
)  # fmt: skip


# ---------------------------------------------------------------------- helpers


def _subject(raw: str | None, scope: TurnScope, facts: FactSources) -> EntityRead | None:
    """The one entity in scope whose name holds the subject as whole words — the planner's own
    rule (`term_in_name`). None when none does, when two do (a tie is declined, never guessed:
    review focus 4), and on a cut graph, which may have dropped the entity it ties with."""
    graph, term = facts.edges(scope), _term(raw)
    if graph.truncated or not term:
        return None
    named = [entity for entity in _things(graph.entities) if term_in_name(term, entity.name)]
    return named[0] if len(named) == 1 else None


def _things(entities: Iterable[EntityRead]) -> list[EntityRead]:
    """The entities a name can mean: a node that describes another carries its name by
    construction (`Hardware config — servo 3 (joint 3)`) and is context, never the subject."""
    return [entity for entity in entities if entity.kind not in _DESCRIBING]


def _term(raw: str | None) -> str:
    """The subject as the person wrote it: no leading article, `@` (the composer's mention
    syntax typed out) or possessive."""
    return _LEADING.sub("", (raw or "").strip()).lstrip("@").removesuffix("'s").strip()


def _phrase(quantity: str) -> str:
    """`Maximum  Voltage` → `max voltage`, `position limits` → `position limit`."""
    return " ".join(quantity.lower().split()).replace("imum", "").removesuffix("s")


def _singular(noun: str) -> str:
    word = noun.lower()
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _is_a(noun: str, entity: EntityRead) -> bool:
    counted = _COUNTED_KINDS.get(noun)
    return entity.kind in counted if counted is not None else term_in_name(noun, entity.name)


def _since(match: Match) -> datetime | None:
    """The start of the window the message names: the last N hours or days, today, yesterday."""
    groups = match.groupdict()
    now = datetime.now(UTC)
    if groups.get("count"):
        per_day = str(groups.get("span") or "").lower().startswith("day")
        return now - timedelta(hours=int(groups["count"]) * (24 if per_day else 1))
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    since = str(groups.get("since") or "").lower()
    if since == "today":
        return midnight
    return midnight - timedelta(days=1) if since == "yesterday" else None


def _evidence_note(edge: EdgeRead) -> str:
    """The edge's newest stored evidence, at most three items, as ` — kind ref`."""
    stored = edge.attrs.get("evidence")
    items = [
        f"{item['kind']} {_quote_name(item['ref'])}"
        for item in (stored if isinstance(stored, list) else [])[-3:]
        if isinstance(item, dict) and item.get("kind") in _EVIDENCE_KINDS and item.get("ref")
    ]
    return f" — {', '.join(items)}" if items else ""


def _quote_name(value: object) -> str:
    """An ingested string as one span of inline code: control and format characters (newlines,
    zero-width marks) out FIRST, so none can split a secret past redaction; then redacted; each
    backtick turned into `'` so it can neither close the span nor open a fence; at most
    `_NAME_CAP` characters."""
    visible = "".join(char for char in str(value) if category(char) not in _INVISIBLE)
    text = redact_text(visible).replace("`", "'").strip()
    if len(text) > _NAME_CAP:
        text = text[: _NAME_CAP - 1] + "…"
    return f"`{text or '?'}`"


def _cite(kind: str, *ids: object) -> str | None:
    """`[kind:id…]` when it fullmatches the citation grammar; None otherwise, never rendered."""
    token = "[" + ":".join((kind, *map(str, ids))) + "]"
    return token if _CITATION_RE.fullmatch(token) else None


def _answered(
    text: str, citations: Iterable[str | None], sources: tuple[str, ...]
) -> DeterministicAnswer:
    """Citations in order, each once; one the grammar refused is already None and dropped."""
    kept = tuple(dict.fromkeys(citation for citation in citations if citation))
    return DeterministicAnswer(text=text, citations=kept, sources=sources)


def _more(total: int) -> str:
    return f", +{total - _LISTED} more" if total > _LISTED else ""


def _config_reading(
    limits: Mapping[str, float | int], limit: _Limit
) -> tuple[tuple[float, ...], str | None] | None:
    """The limit's values in the part's config, with their unit. Position limits held only as
    one `position_min_<u>`/`position_max_<u>` pair read in `u` (unitless when `u` is no unit
    token); two suffixes, or half a pair, are no reading."""
    values = _stated([limits.get(key) for key in limit.keys])
    if values is not None or limit is not _POSITION:
        return (values, limit.unit) if values is not None else None
    units = {key.removeprefix(fix) for key in limits for fix in _SUFFIXED if key.startswith(fix)}
    paired = _stated([limits.get(fix + unit) for unit in units for fix in _SUFFIXED])
    return (paired, _unit(next(iter(units)))) if paired is not None and len(units) == 1 else None


def _stated(values: Sequence[object]) -> tuple[float, ...] | None:
    """Every value a finite number (a bool is not one), or None."""
    numbers = [
        float(value)
        for value in values
        if isinstance(value, int | float) and not isinstance(value, bool)
    ]
    if not values or len(numbers) != len(values) or not all(map(math.isfinite, numbers)):
        return None
    return tuple(numbers)


def _amount(value: float) -> str:
    """Six significant digits, so float noise never shows (`157.99999999999994` reads 158)."""
    return f"{value:.6g}"


def _range_text(values: Sequence[float], unit: str | None) -> str:
    text = " to ".join(map(_amount, values))
    return f"{text} {unit}" if unit else text


def _when(at: datetime) -> str:
    aware = at if at.tzinfo is not None else at.replace(tzinfo=UTC)
    return f"{aware.astimezone(UTC):%Y-%m-%d %H:%M:%S} UTC"


def _unit(token: str | None) -> str | None:
    """A unit only when it fullmatches `_UNIT_TOKEN`: one that does not is never rendered and
    never parsed."""
    return token if token is not None and _UNIT_TOKEN.fullmatch(token) else None


@functools.cache
def _unit_registry() -> pint.UnitRegistry:
    """Built once, on the first conversion: parsing pint's definitions is not free."""
    return pint.UnitRegistry()


def _in_unit(value: float, unit: str | None, target: str) -> float | None:
    """`value` from `unit` into `target`, or None — a refused or unknown unit, another
    dimension. Only fullmatched tokens reach `parse_units`; the magnitude is a float already."""
    source, wanted = _unit(unit), _unit(target)
    if source is None or wanted is None:
        return None
    registry = _unit_registry()
    try:
        converted = registry.Quantity(value, registry.parse_units(source)).to(
            registry.parse_units(wanted)
        )
        magnitude = float(converted.magnitude)
    except Exception:  # an unknown unit, another dimension, a parse edge: declined
        return None
    return magnitude if math.isfinite(magnitude) else None
