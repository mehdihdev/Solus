"""SOLUSDEV-321 P2-T2 — what every live-signal rule shares: the shapes, the still window, needs,
blame, and the few helpers that keep a headline honest.

A rule (`SignalRule`) is pure. It reads one part's `WindowContext` and returns `RuleHit`s; it does
no I/O, writes nothing and calls no model. The window evaluator (P2-T3) builds the context, raises
the hits as findings and records what `unmet` names on the robot (`attrs.missing_signals`).

**The window.** `samples[channel]` is a bounded rolling event-time history of one of the part's
channels, oldest first, ending at its newest sample: every channel the part streams is a key (empty
when nothing is buffered), and `TREND_HORIZON_SECONDS` is the longest span any rule reads.
`judged_through[channel]` is the newest event time an earlier tick judged (the evaluator's cursor
before this tick). A rule fires only on evidence that includes a sample newer than that, so a
condition that persists fires every tick (the finding's count rises) and one that has ended never
fires again from history. `now` and `last_sample_at` are wall clock and only `stream_gap` reads
them; every other rule works in event time. `peers` holds the same robot session's other parts
(part → channel → samples, the same shape); a rule reaches a peer only through a fact edge.
`prior_hits` holds the part's latest hit of each rule this session (only `stream_gap` reads it).

**Units.** Samples arrive in the unit of their quantity's envelope (the evaluator converts or drops
any other), a peer's in the unit its own envelope would carry; rules compare numbers and never
parse a unit. `tolerance` is the part's position tolerance, in its position unit. A reading that is
not finite or lies past `MAX_ABS_VALUE` is dropped before a rule computes with it (`sane`, which
`readings` and `peer_readings` apply), so a corrupt device value never overflows a rule.

**Needs.** A channel is named `<role>.<quantity>`; a rule finds the part's channel for a quantity by
the last dotted segment (two candidates: neither). `Needs.channels` are quantity names,
`Needs.relations` relation types — met by any fact edge of that type in `ctx.graph`, which the
evaluator builds through `to_graph_context`, so a candidate edge never reaches a rule — and
`Needs.facts` envelope slots, `<quantity>.<slot>`. A rule whose needs are unmet fires nothing.

**Blame.** The part, the bus(es) that `drives` it, the brain `hardware_connected_to` each bus. The
code site (the `commands` edge's `firmware_symbol` evidence) goes to `evidence.code_site`, never
into `subjects`; P2-T3 fills its `source_id` from the code entity's row. Every string from the graph
or a device passes `redact_text` and a one-line bound before a headline or the evidence carries it.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from collections import deque
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import groupby
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from solus_contracts.relations import EvidenceKind, MatrixCell, RelationType

from solus_api.agent.tools.untrusted import redact_text
from solus_api.checkers.interface import Severity

if TYPE_CHECKING:
    from solus_api.agent.interfaces import GraphContext
    from solus_api.graph.packet import RecentSample
    from solus_api.livebench.findings.envelopes import Bound, Envelope

#: The longest span of history any rule here reads (the temperature trend's fit). The evaluator
#: keeps at least this much of each channel.
TREND_HORIZON_SECONDS: Final = 30.0
#: A name or a channel a headline shows is one line of at most this many characters.
MAX_LABEL_CHARS: Final = 80
#: A code site's path is one line of at most this many characters (`redact_text`'s display bound).
MAX_PATH_CHARS: Final = 400
#: Nearest-sample alignment of two signals from different devices: one period at 20 Hz.
ALIGN_SECONDS: Final = 0.05
#: The goal channel's quantity: where the part is told to go.
COMMAND: Final = "commanded_position"
#: Rows a run needs, as the still window does.
MIN_ROWS: Final = 3
#: A generic numeric sanity bound on a device reading, not a fact about any motor or sensor: a
#: value past it (or not finite) is corrupt, and dropping it keeps every number a rule derives
#: (spans, sums of squares, fits) finite. ponytail: a raw 32-bit counter can pass it; scale that
#: channel or raise the bound when one does.
MAX_ABS_VALUE: Final = 1e9
_SLOTS: Final = ("nominal", "warn", "limit")
_LIMITS: Final = "in the part's config or its library definition"
_SET_IN: Final = {
    "current": f"the part's limits (`current_a`, `stall_current_a`) {_LIMITS}",
    "temperature": f"the part's limits (`temp_c`) {_LIMITS}",
    "voltage": f"the part's limits (`voltage_min_v`, `voltage_max_v`) {_LIMITS}",
    "position": (
        f"the part's limits (`position_min`, `position_max`) {_LIMITS}, "
        "or the scene joint bound to it"
    ),
    "velocity": f"the part's limits (`velocity_max`) {_LIMITS}",
}

type CauseKind = Literal["software_command", "actuator", "mechanical_load", "electrical_supply"]
#: (event time, current, position, command): one aligned row, as the run analysis builds it.
type StillRow = tuple[datetime, float, float, float]
#: (event time, value) of one signal.
type Point = tuple[datetime, float]


class FactNeed(BaseModel):
    """A fact a rule cannot judge without: `name` (`<quantity>.<slot>` for an envelope slot) and
    `set_in`, where a person states it, in words."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    set_in: str


class Needs(BaseModel):
    """What a rule reads: channel quantities, relation types and facts (P3's matrix rules import
    this shape for their own needs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    channels: tuple[str, ...] = ()
    relations: tuple[str, ...] = ()
    facts: tuple[FactNeed, ...] = ()


class Cause(BaseModel):
    """One candidate cause of a hit with the evidence for and against it, in words whose numbers
    come from the samples and envelopes. On the wire the first list is named `for`."""

    model_config = ConfigDict(frozen=True, extra="forbid", serialize_by_alias=True)

    kind: CauseKind
    for_: tuple[str, ...] = Field(
        default=(), validation_alias=AliasChoices("for", "for_"), serialization_alias="for"
    )
    against: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class RuleHit:
    """What a rule found in one window. P2-T3 raises it as a finding (`source="observer"`):
    `subjects` in blame order, `evidence` the raw numbers under stable keys, `causes` the
    candidates the narration ranks."""

    rule_id: str
    severity: Severity
    headline: str
    subjects: tuple[UUID, ...]
    evidence: dict[str, Any]
    causes: tuple[Cause, ...] = ()


@dataclass(frozen=True, kw_only=True)
class WindowContext:
    """One part's window; the module docstring says what each field holds."""

    part_id: UUID
    robot_id: UUID
    session_id: UUID
    now: datetime
    samples: Mapping[str, tuple[RecentSample, ...]]
    envelopes: Mapping[str, Envelope]
    graph: GraphContext
    last_sample_at: Mapping[str, datetime] = field(default_factory=dict)
    prior_hits: tuple[RuleHit, ...] = ()
    tolerance: float
    judged_through: Mapping[str, datetime] = field(default_factory=dict)
    peers: Mapping[UUID, Mapping[str, tuple[RecentSample, ...]]] = field(default_factory=dict)


class SignalRule(Protocol):
    """A live-signal rule: what it needs, the matrix cell it speaks for, the severity of a hit
    (computed from the hit's evidence) and a pure `evaluate`, which returns [] while `unmet`
    names anything."""

    rule_id: str
    matrix_cell: MatrixCell | None
    needs: Needs

    def severity(self, evidence: Mapping[str, Any]) -> Severity: ...

    def evaluate(self, ctx: WindowContext) -> list[RuleHit]: ...


# ---------------------------------------------------------------------------- the still window


def still_window(
    rows: Iterable[StillRow],
    *,
    current_bound: float,
    tolerance: float,
    seconds: float = 5.0,
    min_seconds: float = 0.5,
) -> list[StillRow]:
    """The first stretch of rows in which the current is at least `current_bound`, the command is
    more than `tolerance` from the position, and the position stays within `tolerance` of where
    the stretch began: three rows or more spanning `min_seconds`, inside a `seconds` deque. A
    repeated timestamp with other values, or a gap over 1.5 s, starts it over. [] when none.

    The loop of `runs/analysis.py:_stall_window`, extracted as it was: the run analysis passes the
    part's stall current and the defaults; the stall rule passes the envelope's warn bound and its
    own sustain span."""
    window: deque[StillRow] = deque()
    last: StillRow | None = None
    for row in sorted(rows):
        timestamp, current, position, command = row
        if last is not None and timestamp == last[0]:
            if row != last:
                window.clear()
            continue
        if last is not None and (timestamp - last[0]).total_seconds() > 1.5:
            window.clear()
        last = row
        if current < current_bound or abs(command - position) <= tolerance:
            window.clear()
            continue
        while window and (timestamp - window[0][0]).total_seconds() > seconds:
            window.popleft()
        if window and abs(position - window[0][2]) > tolerance:
            window.clear()
        window.append(row)
        if len(window) >= 3 and (timestamp - window[0][0]).total_seconds() >= min_seconds:
            return list(window)
    return []


# ---------------------------------------------------------------------------- channels and time


def channels_named(samples: Mapping[str, object], quantity: str) -> list[str]:
    """Every channel named for `quantity` (`<role>.<quantity>`)."""
    return [name for name in samples if name.rsplit(".", 1)[-1] == quantity]


def channel_for(samples: Mapping[str, object], quantity: str) -> str | None:
    """The one channel named for `quantity`; None when there is none or two (which is meant is
    not known)."""
    named = channels_named(samples, quantity)
    return named[0] if len(named) == 1 else None


def sane(samples: Iterable[RecentSample]) -> tuple[RecentSample, ...]:
    """The samples a rule may compute with: finite and within `MAX_ABS_VALUE`. Every reading a
    rule computes with comes through here (`readings`, `peer_readings`), so a corrupt one is
    dropped in one place. ponytail: filters on every read; the evaluator can hand bounded samples
    if the tick budget binds."""
    return tuple(s for s in samples if math.isfinite(s.value) and abs(s.value) <= MAX_ABS_VALUE)


def readings(ctx: WindowContext, quantity: str) -> tuple[str | None, tuple[RecentSample, ...]]:
    """The part's channel for `quantity` and its sane samples; (None, ()) without one."""
    channel = channel_for(ctx.samples, quantity)
    return channel, sane(ctx.samples[channel]) if channel is not None else ()


def peer_readings(
    ctx: WindowContext, peer: UUID, quantity: str
) -> tuple[str | None, tuple[RecentSample, ...]]:
    """A peer's channel for `quantity` and its sane samples; (None, ()) without one."""
    streams = ctx.peers.get(peer, {})
    channel = channel_for(streams, quantity)
    return channel, sane(streams[channel]) if channel is not None else ()


def paired(ctx: WindowContext, *quantities: str) -> list[tuple[Any, ...]]:
    """(time, then each quantity's value in order) at every timestamp the part's channels for
    `quantities` share, as one packet carries a part's channels. ponytail: exact timestamps;
    nearest-sample pairing (`aligned`) when a part's channels arrive from two devices."""
    first, *others = (readings(ctx, quantity)[1] for quantity in quantities)
    by_time = [{s.timestamp: s.value for s in samples} for samples in others]
    return [
        (s.timestamp, s.value, *(values[s.timestamp] for values in by_time))
        for s in first
        if all(s.timestamp in values for values in by_time)
    ]


def points(samples: Iterable[RecentSample], *, magnitude: bool = False) -> list[Point]:
    """(time, value) of each sample; the value's magnitude when asked (a current drawn in reverse
    is still drawn)."""
    return [(s.timestamp, abs(s.value) if magnitude else s.value) for s in samples]


def judged(ctx: WindowContext, *channels: str) -> datetime | None:
    """The newest event time an earlier tick judged on every one of `channels`; None while any of
    them has none (every one of its samples is new)."""
    cursors = [ctx.judged_through.get(name) for name in channels]
    known = [cursor for cursor in cursors if cursor is not None]
    return min(known) if known and len(known) == len(cursors) else None


def is_new(timestamp: datetime, cut: datetime | None) -> bool:
    """Whether a sample at `timestamp` is this tick's: after the cut (no cut: all are)."""
    return cut is None or timestamp > cut


def since[T: tuple[Any, ...]](rows: Sequence[T], cut: datetime | None, seconds: float) -> list[T]:
    """The rows a run of `seconds` that reaches a new row can be made of: those after the cut less
    `seconds` (every row while nothing was judged). Rows are time-ordered, the time first."""
    if cut is None:
        return list(rows)
    start = cut - timedelta(seconds=seconds)
    return [row for row in rows if row[0] > start]


def trailing[T: tuple[Any, ...]](rows: Sequence[T], seconds: float) -> list[T]:
    """The rows within `seconds` of the newest one (time-ordered, the time first)."""
    if not rows:
        return []
    newest = rows[-1][0]
    return [row for row in rows if (newest - row[0]).total_seconds() <= seconds]


def runs[T](rows: Iterable[T], keep: Callable[[T], bool]) -> Iterator[list[T]]:
    """The maximal stretches of consecutive rows that `keep` keeps, in order."""
    for kept, group in groupby(rows, key=keep):
        if kept:
            yield list(group)


def aligned(
    base: Sequence[Point], other: Sequence[Point], *, within: float = ALIGN_SECONDS
) -> list[tuple[datetime, float, float]]:
    """(time, base value, other value) for each `base` point with an `other` point at most
    `within` seconds away — the nearest one."""
    times = [point[0] for point in other]
    rows: list[tuple[datetime, float, float]] = []
    for timestamp, value in base:
        index = bisect_left(times, timestamp)
        near = [j for j in (index - 1, index) if 0 <= j < len(times)]
        best = min(near, key=lambda j: abs((times[j] - timestamp).total_seconds()), default=None)
        if best is not None and abs((times[best] - timestamp).total_seconds()) <= within:
            rows.append((timestamp, value, other[best][1]))
    return rows


def unit_of(ctx: WindowContext, quantity: str) -> str | None:
    """The unit the part's envelope for `quantity` states its numbers in (None without one)."""
    envelope = ctx.envelopes.get(quantity)
    return envelope.unit if envelope is not None else None


def limit_hi(envelope: Envelope | None) -> float | None:
    """The top of the envelope's limit (for current, the rating); None without one."""
    return envelope.limit.hi if envelope is not None and envelope.limit is not None else None


def window_evidence(first: datetime, last: datetime) -> dict[str, Any]:
    """The event-time span a hit's evidence covers."""
    return {
        "window_start": first.isoformat(),
        "window_end": last.isoformat(),
        "window_seconds": (last - first).total_seconds(),
    }


# ---------------------------------------------------------------------------- needs


def fact_need(quantity: str, slot: str) -> FactNeed:
    """The `slot` bound of `quantity`'s envelope as a fact, with where a person states it."""
    return FactNeed(name=f"{quantity}.{slot}", set_in=_SET_IN.get(quantity, "the part's limits"))


def envelope_slot(envelopes: Mapping[str, Envelope], name: str) -> Bound | None:
    """The bound a fact need names (`<quantity>.<slot>`); None when it is not stated."""
    quantity, _, slot = name.partition(".")
    envelope = envelopes.get(quantity)
    if envelope is None or slot not in _SLOTS:
        return None
    bound: Bound | None = getattr(envelope, slot)
    return bound


def _channel_gap(samples: Mapping[str, object], quantity: str) -> str | None:
    """What `unmet` says of a quantity's channel: nothing when there is one, its absence, or that
    several match (which is meant is not known)."""
    count = len(channels_named(samples, quantity))
    if count == 1:
        return None
    return f"{quantity} channel" if count == 0 else f"one {quantity} channel, not {count}"


def unmet(needs: Needs, ctx: WindowContext) -> tuple[str, ...]:
    """What `needs` asks of the window that it lacks, as the robot's `missing_signals` lists it:
    `<quantity> channel`, `<relation> relation`, `<quantity>.<slot> (set it in …)`. Empty: the
    rule can judge."""
    present = {edge.relation_type for edge in ctx.graph.edges}
    return (
        *(gap for q in needs.channels if (gap := _channel_gap(ctx.samples, q)) is not None),
        *(f"{r} relation" for r in needs.relations if r not in present),
        *(
            f"{fact.name} (set it in {fact.set_in})"
            for fact in needs.facts
            if envelope_slot(ctx.envelopes, fact.name) is None
        ),
    )


# ---------------------------------------------------------------------------- blame


def linked(graph: GraphContext, relation: str, entity_id: UUID, *, into: bool = True) -> list[UUID]:
    """The far ends of the `relation` fact edges into `entity_id` (`into`: their sources) or out
    of it (their targets), by id."""
    ends = {
        edge.src_id if into else edge.dst_id
        for edge in graph.edges
        if edge.relation_type == relation and (edge.dst_id if into else edge.src_id) == entity_id
    }
    return sorted(ends, key=str)


def blame(ctx: WindowContext, part_id: UUID) -> tuple[tuple[UUID, ...], dict[str, Any] | None]:
    """`part_id`, the bus(es) that drive it, the brain of each bus — and the code site that
    commands it (`{entity_id, source_id: None, path, line}`, or None)."""
    buses = linked(ctx.graph, RelationType.DRIVES, part_id)
    brains = [
        b for bus in buses for b in linked(ctx.graph, RelationType.HARDWARE_CONNECTED_TO, bus)
    ]
    return tuple(dict.fromkeys((part_id, *buses, *brains))), code_site(ctx.graph, part_id)


def code_site(graph: GraphContext, part_id: UUID) -> dict[str, Any] | None:
    """The first `commands` fact edge into the part (by code entity id) whose `firmware_symbol`
    evidence names a `path:line`: the code entity, the path as `redact_text` shows a display path
    and the line. `source_id` is the evaluator's to fill (the context does not carry it)."""
    commanding = sorted(
        (
            e
            for e in graph.edges
            if e.relation_type == RelationType.COMMANDS and e.dst_id == part_id
        ),
        key=lambda edge: str(edge.src_id),
    )
    for edge in commanding:
        for path, line in _symbol_refs(edge.attrs.get("evidence")):
            return {"entity_id": str(edge.src_id), "source_id": None, "path": path, "line": line}
    return None


def _symbol_refs(evidence: object) -> Iterator[tuple[str, int]]:
    """(path, line) of each `firmware_symbol` item of an edge's evidence. The parse of
    `graph/inference/common.py:split_source_ref` — that module reads the database, so this pure
    package does not import it — with the line held to ASCII digits."""
    items = evidence if isinstance(evidence, list) else []
    refs = [
        item.get("ref")
        for item in items
        if isinstance(item, dict) and item.get("kind") == EvidenceKind.FIRMWARE_SYMBOL
    ]
    for ref in refs:
        head, sep, tail = ref.rpartition(":") if isinstance(ref, str) else ("", "", "")
        if not (sep and head and tail.isascii() and tail.isdigit() and len(tail) <= 9):
            continue
        path = one_line(redact_text(head, allowed_paths=frozenset({head})), MAX_PATH_CHARS)
        if path:
            yield path, int(tail)


# ---------------------------------------------------------------------------- text


def one_line(text: str, limit: int = MAX_LABEL_CHARS) -> str:
    """`text` on one printable line: control characters and runs of whitespace become one space,
    cut to `limit` characters (an ellipsis marks the cut)."""
    flat = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def shown(text: str) -> str:
    """A string from the graph or a device as a headline may carry it: redacted, then one line."""
    return one_line(redact_text(text))


def entity_label(graph: GraphContext, entity_id: UUID) -> str:
    """The entity's name as a headline shows it; its short id when the context names it not."""
    name = next((entity.name for entity in graph.entities if entity.id == entity_id), "")
    return shown(name) or f"entity {str(entity_id)[:8]}"


def amount(value: float, unit: str | None = None) -> str:
    """`value` to four significant digits with its unit: `2.4 A`, `2.004 A`, `150.0 deg`. A ".0"
    marks a whole number only when the digits shown are the value itself."""
    text = f"{value:.4g}"
    if "." not in text and "e" not in text and float(text) == value:
        text += ".0"
    return f"{text} {unit}" if unit else text


def outside(value: float, band: Bound, tolerance: float = 0.0) -> tuple[float, str] | None:
    """The edge of `band` that `value` lies past by more than `tolerance`, and which side it is;
    None inside the band."""
    if band.hi is not None and value > band.hi + tolerance:
        return band.hi, "upper"
    if band.lo is not None and value < band.lo - tolerance:
        return band.lo, "lower"
    return None


def past(
    samples: Iterable[RecentSample], band: Bound, tolerance: float, cut: datetime | None
) -> list[tuple[RecentSample, float, str]]:
    """This tick's samples past `band` by more than `tolerance`, each with the edge and side."""
    found: list[tuple[RecentSample, float, str]] = []
    for sample in samples:
        edge = outside(sample.value, band, tolerance)
        if edge is not None and is_new(sample.timestamp, cut):
            found.append((sample, *edge))
    return found


def make_hit(
    rule: SignalRule,
    ctx: WindowContext,
    *,
    headline: str,
    evidence: Mapping[str, Any],
    causes: Iterable[Cause] = (),
    subjects: Sequence[UUID] | None = None,
) -> RuleHit:
    """A hit on the window's part: the blamed subjects unless the rule names its own, the code
    site in the evidence, and the severity the rule computes from that evidence."""
    blamed, site = blame(ctx, ctx.part_id)
    full = {**evidence, **({"code_site": site} if site is not None else {})}
    return RuleHit(
        rule_id=rule.rule_id,
        severity=rule.severity(full),
        headline=headline,
        subjects=tuple(subjects) if subjects is not None else blamed,
        evidence=full,
        causes=tuple(causes),
    )
