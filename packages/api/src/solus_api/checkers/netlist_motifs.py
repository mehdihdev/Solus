"""SOLUSDEV-321 P3-T4 — netlist motifs: the small circuits a schematic is made of, found by their
shape and nothing else.

`detect_motifs` is pure (ADR-003, R57): graph in, motifs out, with no model and no I/O.

**What it reads.**

- The schematic connector's `component` and `net` entities.
- The `connected_to` edges between them: a component's pins on a net, and the pin functions the
  export names.
- The confirmed `reads` edges, which say the code samples a net.
- A component's role comes from its reference designator's letter (R, C, Q, U) and its `value`,
  read with SI prefixes.
- A net is a rail or a ground by the same names the power inference uses
  (`graph/inference/power_nets.py`).

**The five shapes.**

- `divider_adc`: a resistor from a source and one to ground meet at a net an IC pin is on,
  usually with a capacitor to ground there. Its RC is R_top‖R_bottom with that capacitance.
- `rc_on_input`: one series resistor into an IC pin's net, and a capacitor from that net to
  ground.
- `decoupling_at_pin`: a capacitor from a rail to ground, at the rail an IC is powered from.
- `h_bridge`: two half bridges on one rail and ground. On each output net, one transistor goes to
  the rail and one to ground.
- `level_shifter`: a transistor between two signal nets, each pulled up to its own rail, with its
  third terminal on the low side's rail.

**Confidence**, how sure the shape is:

- `CONFIDENT` when the role is evidenced as well: an input that a read samples, or whose pin
  function or net name says it is analog (a whole token, m2); one IC on a decoupled rail; a load
  across a bridge;
- `DISTINCT` for a bridge whose shape alone is unmistakable;
- `CANDIDATE` when nothing says the shape plays that role. A level shifter is always one: nothing
  beyond its shape says it shifts levels (m10).

A motif at `LABEL_THRESHOLD` or below is left for a person's SOL turn to label
(`agent/tools/label_motifs.py`). No rule reads one.

**Bounds (R79).** There is no all-pairs scan.

- A net's ICs are looked up once, and so is its pull-up (I1).
- At most `MAX_SUPPLY_HALVES` half bridges of one supply are paired.
- A signal net holding more than `MAX_SHIFTER_NET_PARTS` parts is no level shifter's.
- Each cap is logged when it binds.

This is shared code. It names a part by its designator's letter and a net by its name, never a
vendor, a tool or a product; both hygiene ratchets sweep `checkers/`.
"""

from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal, NamedTuple
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from solus_contracts.relations import CANDIDATE_THRESHOLD

from solus_api.checkers.attributes import CONNECTED_TO, READS
from solus_api.core.errors import APIError
from solus_api.graph import kinds
from solus_api.graph.inference.power_nets import GROUND_NET, is_power_rail_name
from solus_api.models import GraphEntity

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from solus_api.agent.interfaces import EdgeRead, GraphContext

MotifKind = Literal["divider_adc", "rc_on_input", "decoupling_at_pin", "h_bridge", "level_shifter"]
MOTIF_KINDS: Final[tuple[MotifKind, ...]] = (
    "divider_adc",
    "rc_on_input",
    "decoupling_at_pin",
    "h_bridge",
    "level_shifter",
)
#: The kinds that are an ADC input, whose RC a sample has to settle through.
INPUT_KINDS: Final[frozenset[MotifKind]] = frozenset({"divider_adc", "rc_on_input"})
CONFIDENT: Final = 0.9
DISTINCT: Final = 0.8
CANDIDATE: Final = 0.6
#: At or below this a motif is a candidate for a person's SOL turn to label; no rule reads it.
LABEL_THRESHOLD: Final = 0.7
#: A motif with more members than this is not the small circuit it looks like, and is dropped.
MAX_MOTIF_MEMBERS: Final = 16
#: At most this many half bridges of one supply are paired into bridges (R79), logged when it
#: binds: pairing is quadratic, and a supply with more is a multi-channel stage.
MAX_SUPPLY_HALVES: Final = 32
#: A level shifter's signal net holds its switch, its pull-up and a few pins. One that holds more
#: parts than this is a bus or a stress shape, so the shifter search skips it (logged): its work
#: per net stays bounded (I1, R79).
MAX_SHIFTER_NET_PARTS: Final = 64

logger = logging.getLogger("solus.checkers.netlist_motifs")

_RESISTOR: Final = "R"
_CAPACITOR: Final = "C"
_TRANSISTOR: Final = "Q"
_IC: Final = frozenset({"U", "IC"})
_LETTER: Final = re.compile(r"^([A-Z]+)\d")
#: A net name or pin function token saying the net is sampled as an analog input (m2). It is matched
#: whole, on tokens split at anything not a letter or a digit: `VBAT_AIN0` says it, and
#: `HEADCAM_EN` (an `adc` inside a word) does not.
_ANALOG_TOKEN: Final = re.compile(r"(?:adc|ain|analog|[vi]?sense|[vi]?meas)\d*", re.IGNORECASE)
_TOKENS: Final = re.compile(r"[A-Za-z0-9]+")
_SI: Final[Mapping[str, float]] = {
    "p": 1e-12,
    "n": 1e-9,
    "u": 1e-6,
    "µ": 1e-6,
    "μ": 1e-6,
    "m": 1e-3,
    "": 1.0,
    "R": 1.0,
    "r": 1.0,
    "k": 1e3,
    "K": 1e3,
    "M": 1e6,
    "G": 1e9,
}
#: `10k`, `4k7` (the prefix as the decimal point), `2R2`, `100nF`, `0.1 uF`, `10kΩ`.
_VALUE: Final = re.compile(r"(\d+(?:\.\d+)?)\s*([pnuµμmkKMGRr]?)(\d*)\s*(?:F|Ω|ohms?)?")
_RAIL: Final = "rail"
_GROUND: Final = "ground"
_SIGNAL: Final = "signal"


@dataclass(frozen=True)
class NetMotif:
    """One small circuit, with these fields:

    - its kind;
    - its members: the components, then the nets;
    - how sure its shape is;
    - the net it is about;
    - for an ADC input, the RC that net settles through, as (ohms, farads). This is None when a
      value is unstated or no capacitor is there.
    """

    kind: MotifKind
    members: tuple[UUID, ...]
    confidence: float
    net: UUID
    rc: tuple[float, float] | None = None

    @property
    def settled(self) -> bool:
        """Above `LABEL_THRESHOLD`: the shape settles the role, and a rule may read it."""
        return self.confidence > LABEL_THRESHOLD

    def as_attr(self) -> dict[str, Any]:
        """The motif as its members' `attrs.motifs` keep it: `{kind, members, confidence}`."""
        return {
            "kind": self.kind,
            "members": [str(member) for member in self.members],
            "confidence": self.confidence,
        }


def detect_motifs(graph: GraphContext) -> tuple[NetMotif, ...]:
    """Every motif the graph's netlist holds, in a stable order: kind by kind in `MOTIF_KINDS`
    order, then by the net each is about. Pure."""
    return _MotifFinder(graph).motifs()


def si_value(text: str) -> float | None:
    """A component value as a number (`10k`, `4k7`, `2R2`, `100nF`, `0.1uF`). It is None when the
    value does not read: `DNP`, a range or a negative. A trailing rating (`100nF 50V`,
    `100nF/50V`) is ignored."""
    head = text.strip().split("/", 1)[0].strip()
    for candidate in (head, head.split(" ", 1)[0]):
        match = _VALUE.fullmatch(candidate)
        if match is not None:
            return _scaled(*match.groups())
    return None


def designator_letter(name: str) -> str | None:
    """A reference designator's letters (`R` for `R12`, `IC` for `IC3`); None for a name that is
    not one."""
    match = _LETTER.match(name)
    return match.group(1) if match else None


def _scaled(number: str, prefix: str, fraction: str) -> float | None:
    if fraction and "." in number:
        return None  # `4.7k7` is no value
    value = float(f"{number}.{fraction}" if fraction else number) * _SI[prefix]
    return value if math.isfinite(value) else None


class _HalfBridge(NamedTuple):
    """One output net, its transistor to the rail and its transistor to ground."""

    out: UUID
    high: UUID
    low: UUID
    rail: UUID
    ground: UUID


class _MotifFinder:
    """The netlist a graph states, read once: each component's pins on each net."""

    def __init__(self, graph: GraphContext) -> None:
        self.names = {entity.id: entity.name for entity in graph.entities}
        self.parts = {e.id: e for e in graph.entities if e.kind == kinds.COMPONENT}
        self.roles = {e.id: self._role_of(e.name) for e in graph.entities if e.kind == kinds.NET}
        self.pins: dict[UUID, dict[UUID, tuple[str, ...]]] = defaultdict(dict)
        self.functions: dict[tuple[UUID, UUID], tuple[str, ...]] = {}
        self.read: set[UUID] = set()
        on: dict[UUID, list[UUID]] = defaultdict(list)
        for edge in graph.edges:
            if self._take(edge):
                on[edge.dst_id].append(edge.src_id)
        self.on = {net: sorted(set(parts), key=self._order) for net, parts in on.items()}
        self._ics: dict[UUID, list[UUID]] = {}
        self._pulls: dict[UUID, tuple[UUID, UUID] | None] = {}

    def _ics_on(self, net: UUID) -> list[UUID]:
        """The ICs on `net`, looked up once a net (R79): a rail can hold a thousand capacitors,
        and each asks it."""
        if net not in self._ics:
            self._ics[net] = self._on(net, _IC)
        return self._ics[net]

    def _take(self, edge: EdgeRead) -> bool:
        """Record what one edge states; True for a component's membership of a net."""
        if edge.confidence < CANDIDATE_THRESHOLD:
            return False
        if edge.relation_type == READS:
            self.read.add(edge.dst_id)
            return False
        if edge.relation_type != CONNECTED_TO or edge.src_id not in self.parts:
            return False
        if edge.dst_id not in self.roles:
            return False
        pins, functions = edge.attrs.get("pins"), edge.attrs.get("pin_functions")
        stated = tuple(str(pin) for pin in pins) if isinstance(pins, list) else ()
        self.pins[edge.src_id][edge.dst_id] = stated
        named = functions.values() if isinstance(functions, Mapping) else ()
        self.functions[(edge.src_id, edge.dst_id)] = tuple(str(f) for f in named)
        return True

    @staticmethod
    def _role_of(name: str) -> str:
        bare = name.removeprefix("/")  # a sheet-local label's path prefix
        if GROUND_NET.search(bare):
            return _GROUND
        return _RAIL if is_power_rail_name(bare) else _SIGNAL

    def _order(self, entity_id: UUID) -> tuple[str, str]:
        return self.names.get(entity_id, ""), str(entity_id)

    def _letter(self, part: UUID) -> str | None:
        return designator_letter(self.parts[part].name)

    def _parts_with(self, letter: str) -> list[UUID]:
        return sorted((p for p in self.parts if self._letter(p) == letter), key=self._order)

    def _on(self, net: UUID, letters: frozenset[str]) -> list[UUID]:
        """The parts on `net` whose designator letter is one of `letters`."""
        return [part for part in self.on.get(net, ()) if self._letter(part) in letters]

    def _nets_of(self, part: UUID) -> list[UUID]:
        return sorted(self.pins.get(part, {}), key=self._order)

    def _other(self, part: UUID, net: UUID) -> UUID | None:
        """A two-terminal part's net other than `net`; None for any other part."""
        nets = self.pins.get(part, {})
        if len(nets) != 2 or net not in nets:
            return None
        return next(other for other in nets if other != net)

    def _value(self, part: UUID) -> float | None:
        value = self.parts[part].attrs.get("value")
        return si_value(value) if isinstance(value, str) else None

    def motifs(self) -> tuple[NetMotif, ...]:
        found = [*self._inputs(), *self._decouplings(), *self._bridges(), *self._shifters()]
        kept = {(m.kind, m.members): m for m in found if len(m.members) <= MAX_MOTIF_MEMBERS}
        return tuple(
            sorted(
                kept.values(),
                key=lambda m: (MOTIF_KINDS.index(m.kind), self._order(m.net), m.members),
            )
        )

    # ------------------------------------------------------------------ ADC inputs

    def _inputs(self) -> Iterator[NetMotif]:
        for net in sorted(self.roles, key=self._order):
            motif = self._input(net) if self.roles[net] == _SIGNAL else None
            if motif is not None:
                yield motif

    def _input(self, net: UUID) -> NetMotif | None:
        ics = self._ics_on(net)
        if not ics:  # no IC samples it: skip the legs scan, a crowded net's second pass
            return None
        tops, bottoms, caps = self._legs(net)
        if len(tops) != 1 or len(bottoms) > 1 or not (bottoms or caps):
            return None
        kind: MotifKind = "divider_adc" if bottoms else "rc_on_input"
        confidence = CONFIDENT if self._sampled(net, ics) else CANDIDATE
        members = (*tops, *bottoms, *caps, *ics, net)
        return NetMotif(kind, members, confidence, net, self._rc(tops[0], bottoms, caps))

    def _legs(self, net: UUID) -> tuple[list[UUID], list[UUID], list[UUID]]:
        """The two-terminal parts on `net`: resistors from elsewhere (tops), and resistors and
        capacitors to ground."""
        tops: list[UUID] = []
        bottoms: list[UUID] = []
        caps: list[UUID] = []
        for part in self.on.get(net, ()):
            other, letter = self._other(part, net), self._letter(part)
            grounded = other is not None and self.roles[other] == _GROUND
            if other is None or letter not in (_RESISTOR, _CAPACITOR):
                continue
            if letter == _RESISTOR:
                (bottoms if grounded else tops).append(part)
            elif grounded:
                caps.append(part)
        return tops, bottoms, caps

    def _sampled(self, net: UUID, ics: Sequence[UUID]) -> bool:
        """Whether something says `net` is sampled: a confirmed read lands on a part on it, or its
        name or an IC pin's function there says it is an analog input."""
        if any(part in self.read for part in self.on.get(net, ())):
            return True
        functions = (f for ic in ics for f in self.functions.get((ic, net), ()))
        names = (self.names[net], *functions)
        return any(_ANALOG_TOKEN.fullmatch(t) for name in names for t in _TOKENS.findall(name))

    def _rc(
        self, top: UUID, bottoms: Sequence[UUID], caps: Sequence[UUID]
    ) -> tuple[float, float] | None:
        """(ohms, farads): what the input's capacitance charges through, R_top‖R_bottom or the
        series R, and that capacitance. None without a capacitor or when a value is unstated."""
        rs = [r for part in (top, *bottoms) if (r := self._value(part)) is not None]
        cs = [c for part in caps if (c := self._value(part)) is not None]
        if not caps or len(rs) != 1 + len(bottoms) or len(cs) != len(caps):
            return None
        if len(rs) == 1:
            return rs[0], sum(cs)
        total = rs[0] + rs[1]
        return (rs[0] * rs[1] / total if total > 0 else 0.0), sum(cs)

    # ------------------------------------------------------------------ decoupling

    def _decouplings(self) -> Iterator[NetMotif]:
        for cap in self._parts_with(_CAPACITOR):
            nets = {self.roles[net]: net for net in self._nets_of(cap)}
            if len(self.pins.get(cap, {})) != 2 or set(nets) != {_RAIL, _GROUND}:
                continue
            rail, ground = nets[_RAIL], nets[_GROUND]
            ics = self._ics_on(rail)
            if len(ics) == 1:
                yield NetMotif("decoupling_at_pin", (cap, ics[0], rail, ground), CONFIDENT, rail)
            elif ics:  # whose pin it decouples needs the board's placement: a candidate
                yield NetMotif("decoupling_at_pin", (cap, rail, ground), CANDIDATE, rail)

    # ------------------------------------------------------------------ bridges

    def _bridges(self) -> Iterator[NetMotif]:
        by_supply: dict[tuple[UUID, UUID], list[_HalfBridge]] = defaultdict(list)
        for half in sorted(self._half_bridges(), key=lambda h: self._order(h.out)):
            by_supply[(half.rail, half.ground)].append(half)
        for group in by_supply.values():
            if len(group) > MAX_SUPPLY_HALVES:
                logger.warning(
                    "netlist motifs: %d half bridges share one supply; pairing the first %d",
                    len(group),
                    MAX_SUPPLY_HALVES,
                )
            yield from self._paired(group[:MAX_SUPPLY_HALVES])

    def _half_bridges(self) -> Iterator[_HalfBridge]:
        """Each signal net with exactly two transistors on it, one also on a rail and the other
        on a ground."""
        transistor = frozenset({_TRANSISTOR})
        for net, role in self.roles.items():
            switches = self._on(net, transistor) if role == _SIGNAL else []
            if len(switches) != 2:
                continue
            highs = [(q, n) for q in switches for n in self._nets_of(q) if self.roles[n] == _RAIL]
            lows = [(q, n) for q in switches for n in self._nets_of(q) if self.roles[n] == _GROUND]
            if len(highs) == 1 and len(lows) == 1 and highs[0][0] != lows[0][0]:
                yield _HalfBridge(net, highs[0][0], lows[0][0], highs[0][1], lows[0][1])

    def _paired(self, group: Sequence[_HalfBridge]) -> list[NetMotif]:
        """Two halves of one supply sharing a load across their outputs make a settled bridge. A
        supply holding exactly two halves and no shared load is one by shape alone. More halves
        and no load (a three-phase stage, a complementary pair's gate net) make none."""
        pairs = [
            (a, b)
            for i, a in enumerate(group)
            for b in group[i + 1 :]
            if not {a.high, a.low} & {b.high, b.low}
        ]
        loaded = [(a, b, loads) for a, b in pairs if (loads := self._loads(a, b))]
        if loaded:
            return [self._bridge(a, b, loads[:1], CONFIDENT) for a, b, loads in loaded]
        return [self._bridge(*pairs[0], [], DISTINCT)] if len(group) == 2 and pairs else []

    def _loads(self, a: _HalfBridge, b: _HalfBridge) -> list[UUID]:
        switches = {a.high, a.low, b.high, b.low}
        across = set(self.on.get(b.out, ()))
        return [p for p in self.on.get(a.out, ()) if p in across and p not in switches]

    @staticmethod
    def _bridge(
        a: _HalfBridge, b: _HalfBridge, loads: Sequence[UUID], confidence: float
    ) -> NetMotif:
        members = (a.high, a.low, b.high, b.low, *loads, a.out, b.out)
        return NetMotif("h_bridge", members, confidence, a.out)

    # ------------------------------------------------------------------ level shifters

    def _shifters(self) -> Iterator[NetMotif]:
        for switch in self._parts_with(_TRANSISTOR):
            motif = self._shifter(switch)
            if motif is not None:
                yield motif

    def _shifter(self, switch: UUID) -> NetMotif | None:
        nets = self._nets_of(switch)
        rails = [net for net in nets if self.roles[net] == _RAIL]
        signals = [net for net in nets if self.roles[net] == _SIGNAL]
        if len(nets) != 3 or len(rails) != 1 or len(signals) != 2:
            return None
        ups = [(s, pull) for s in signals if (pull := self._pull_up(s)) is not None]
        low = [(s, r) for s, (r, rail) in ups if rail == rails[0]]
        high = [(s, r) for s, (r, rail) in ups if rail != rails[0]]
        if len(low) != 1 or len(high) != 1:
            return None
        (low_net, low_up), (high_net, high_up) = low[0], high[0]
        members = (switch, low_up, high_up, low_net, high_net)
        # m10: the shape alone, with nothing evidencing the role, is a candidate to label
        return NetMotif("level_shifter", members, CANDIDATE, low_net)

    def _pull_up(self, signal: UUID) -> tuple[UUID, UUID] | None:
        """The one resistor on `signal` whose other net is a rail, and that rail; looked up once a
        net (I1, R79). Every switch on the net asks, so an uncached scan was switches × parts. A
        net holding more than `MAX_SHIFTER_NET_PARTS` parts is no shifter's and gets none."""
        if signal in self._pulls:
            return self._pulls[signal]
        crowd = len(self.on.get(signal, ()))
        if crowd > MAX_SHIFTER_NET_PARTS:
            logger.warning(
                "netlist motifs: %d parts on one signal net; it is no level shifter's", crowd
            )
            self._pulls[signal] = None
            return None
        ups = [
            (r, other)
            for r in self._on(signal, frozenset({_RESISTOR}))
            if (other := self._other(r, signal)) is not None and self.roles[other] == _RAIL
        ]
        self._pulls[signal] = ups[0] if len(ups) == 1 else None
        return self._pulls[signal]


# ------------------------------------------------------------------ keeping them (R57, R78)

#: The job's key on each member: every motif it belongs to, rewritten by each run.
MOTIFS_KEY: Final = "motifs"
#: A model's labels for candidates, written by `label_motifs` in a SOL turn and never by the job.
#: No rule reads it (R78).
LABELS_KEY: Final = "motif_labels"
LabelKind = Literal[MotifKind, "unknown"]
#: The closed set a label must be in before it is written: the five kinds, and `unknown`.
LABEL_KINDS: Final[tuple[str, ...]] = (*MOTIF_KINDS, "unknown")
#: At most this many motifs, or labels, a member keeps, the most confident first. Logged when it
#: binds, because a rail's only IC can decouple through dozens of capacitors.
MAX_ENTITY_MOTIFS: Final = 16


class MotifEntry(BaseModel):
    """One `attrs.motifs` item, as the job writes it (R57)."""

    model_config = ConfigDict(extra="forbid")

    kind: MotifKind
    members: list[UUID] = Field(min_length=1, max_length=MAX_MOTIF_MEMBERS)
    confidence: float = Field(ge=0, le=1)


class MotifLabel(BaseModel):
    """One `attrs.motif_labels` item: a model's label for a candidate in a SOL turn (R78). Only a
    candidate is labelled, so its confidence is at most `LABEL_THRESHOLD`."""

    model_config = ConfigDict(extra="forbid")

    kind: LabelKind
    members: list[UUID] = Field(min_length=1, max_length=MAX_MOTIF_MEMBERS)
    confidence: float = Field(ge=0, le=LABEL_THRESHOLD)
    labelled_by: Literal["model"]
    turn_id: UUID


def motif_entries(motifs: Sequence[NetMotif]) -> dict[UUID, list[dict[str, Any]]]:
    """Each member's `attrs.motifs`: the motifs it belongs to, most confident first, at most
    `MAX_ENTITY_MOTIFS`."""
    held: dict[UUID, list[NetMotif]] = defaultdict(list)
    for motif in motifs:
        for member in motif.members:
            held[member].append(motif)
    crowded = sum(len(of) > MAX_ENTITY_MOTIFS for of in held.values())
    if crowded:
        logger.warning(
            "netlist motifs: %d member(s) in more than %d motifs; keeping the most confident",
            crowded,
            MAX_ENTITY_MOTIFS,
        )
    return {
        member: [m.as_attr() for m in sorted(of, key=lambda m: -m.confidence)[:MAX_ENTITY_MOTIFS]]
        for member, of in held.items()
    }


async def write_motifs(
    session: AsyncSession,
    project_id: UUID,
    entity_id: UUID,
    entries: Sequence[Mapping[str, Any]],
) -> GraphEntity | None:
    """Keep the job's motifs on a live entity of this project. `attrs.motifs` is reassigned to the
    `entries`, validated first (an empty list drops the key). Nothing else on the row moves, and
    `version` goes up by 1.

    It works as `graph/edges.py:annotate_edge` does (R78):

    - callers hold `lock_project`;
    - the row is re-read fresh under a row lock, so attrs another writer committed since the
      caller read it are kept;
    - it never waits for that lock: a row another transaction holds is not written, and None says
      so;
    - a gone, foreign or deleted entity is 404.

    It flushes and never commits. It publishes nothing: a GraphEntity flush derives no live frame
    except a finding's."""
    items = [MotifEntry.model_validate(entry).model_dump(mode="json") for entry in entries]
    entity = await _fresh_entity(session, project_id, entity_id)
    if entity is not None and entity.attrs.get(MOTIFS_KEY, []) != items:
        kept = {key: value for key, value in entity.attrs.items() if key != MOTIFS_KEY}
        entity.attrs = {**kept, MOTIFS_KEY: items} if items else kept
        entity.version += 1
        await session.flush()
    return entity


async def add_motif_label(
    session: AsyncSession, project_id: UUID, entity_id: UUID, label: Mapping[str, Any]
) -> GraphEntity | None:
    """Add a model's label to a live entity's `attrs.motif_labels`, checked against the closed set
    first (`MotifLabel`). It replaces a label for the same members, keeps the others, and holds at
    most `MAX_ENTITY_MOTIFS`. The row discipline is `write_motifs`'s, and `attrs.motifs` is never
    touched."""
    item = MotifLabel.model_validate(label).model_dump(mode="json")
    entity = await _fresh_entity(session, project_id, entity_id)
    if entity is None:
        return None
    old = entity.attrs.get(LABELS_KEY)
    others = [
        prior
        for prior in (old if isinstance(old, list) else [])
        if not (isinstance(prior, dict) and prior.get("members") == item["members"])
    ]
    entity.attrs = {**entity.attrs, LABELS_KEY: [*others, item][-MAX_ENTITY_MOTIFS:]}
    entity.version += 1
    await session.flush()
    return entity


async def _fresh_entity(
    session: AsyncSession, project_id: UUID, entity_id: UUID
) -> GraphEntity | None:
    """A live entity of this project, re-read under a row lock that is never waited for. None for
    a row another transaction holds; 404 for a gone, foreign or deleted one."""
    entity = await session.get(
        GraphEntity, entity_id, populate_existing=True, with_for_update={"skip_locked": True}
    )
    if entity is not None and entity.project_id == project_id and entity.deleted_at is None:
        return entity
    held = await session.get(GraphEntity, entity_id, populate_existing=True)
    if held is None or held.project_id != project_id or held.deleted_at is not None:
        raise APIError(404, "not_found", "Entity not found")
    return None
