"""SOLUSDEV-321 P3-T4 — netlist motifs (`checkers/netlist_motifs.py`).

The detector finds five small circuits by their shape alone. It reads the schematic connector's
components and nets, each component's pins on a net (`connected_to`), and the confirmed `reads`
edges. It never calls a model.

A motif whose role nothing evidences is a candidate (confidence 0.6), which a person's SOL turn may
label. The matrix job keeps every motif on its members (`attrs.motifs`).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path
from typing import Final

import pytest
from fixtures.matrix_divider import seed_divider
from pydantic import ValidationError
from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers import netlist_motifs
from solus_api.checkers.matrix_runner import run_matrix
from solus_api.checkers.netlist_motifs import (
    CANDIDATE,
    CONFIDENT,
    DISTINCT,
    LABEL_THRESHOLD,
    LABELS_KEY,
    MAX_SUPPLY_HALVES,
    MOTIF_KINDS,
    MOTIFS_KEY,
    detect_motifs,
    si_value,
    write_motifs,
)
from solus_api.connectors.eda import build_graph
from solus_api.connectors.kicad_netlist import parse_kicad_netlist
from solus_api.core.errors import APIError
from solus_api.models import GraphEntity
from solus_api.orchestration import gateway
from solus_api.services.solus_graph import lock_project
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

DIVIDER_NET: Final = Path(__file__).parent / "fixtures" / "kicad_divider_adc.net"


class _Schematic:
    """A netlist as a matrix run's graph holds it. It has components and nets, the
    `connected_to` edges carrying each component's pins on a net, and confirmed `reads` edges."""

    def __init__(self) -> None:
        self.entities: dict[str, EntityRead] = {}
        self.edges: list[EdgeRead] = []

    def part(self, ref: str, value: str | None = None) -> _Schematic:
        attrs = {"value": value} if value is not None else {}
        self.entities[ref] = EntityRead(
            id=uuid.uuid4(), kind="component", domain="electrical", name=ref, attrs=attrs
        )
        return self

    def wire(self, ref: str, net: str, pin: str, *, function: str | None = None) -> _Schematic:
        if net not in self.entities:
            self.entities[net] = EntityRead(
                id=uuid.uuid4(), kind="net", domain="electrical", name=net
            )
        attrs: dict[str, object] = {
            "net": net,
            "pins": [pin],
            **({"pin_functions": {pin: function}} if function else {}),
        }
        self.edges.append(self._edge(ref, net, "connected_to", attrs))
        return self

    def read(self, ref: str) -> _Schematic:
        """A code file that samples `ref`'s net, through a confirmed `reads` edge."""
        if "fw.ino" not in self.entities:
            self.entities["fw.ino"] = EntityRead(
                id=uuid.uuid4(), kind="code_file", domain="code", name="fw.ino"
            )
        self.edges.append(self._edge("fw.ino", ref, "reads", {"pin": "A0"}))
        return self

    def _edge(self, src: str, dst: str, relation: str, attrs: dict[str, object]) -> EdgeRead:
        a, b = self.entities[src], self.entities[dst]
        return EdgeRead(
            src_id=a.id,
            dst_id=b.id,
            relation_type=relation,
            domain_pair=f"{a.domain}<->{b.domain}",
            confidence=1.0,
            attrs=attrs,
        )

    def graph(self) -> GraphContext:
        return GraphContext(entities=list(self.entities.values()), edges=list(self.edges))

    def ids(self, *names: str) -> tuple[uuid.UUID, ...]:
        return tuple(self.entities[name].id for name in names)


def _fixture_context() -> tuple[GraphContext, dict[str, uuid.UUID]]:
    """`kicad_divider_adc.net` through the schematic connector's real mapping, as a run reads it:
    the ids by designator and by net name."""
    entities, relations, errors = build_graph(parse_kicad_netlist(DIVIDER_NET.read_text()))
    assert errors == []
    keys = {out.source_key: uuid.uuid4() for out in entities}
    reads = [
        EntityRead(
            id=keys[o.source_key], kind=o.type, domain="electrical", name=o.name, attrs=o.properties
        )
        for o in entities
    ]
    edges = [
        EdgeRead(
            src_id=keys[r.from_key],
            dst_id=keys[r.to_key],
            relation_type=r.type,
            domain_pair="electrical<->electrical",
            confidence=1.0,
            attrs=r.properties,
        )
        for r in relations
    ]
    return GraphContext(entities=reads, edges=edges), {e.name: e.id for e in reads}


def test_divider_adc() -> None:
    """The fixture: R1 from the battery and R2 to ground split it at /VSENSE, which U1's ADC0 pin
    reads, and C1 sits there to ground. That is a settled divider whose RC is R1‖R2 · C1."""
    graph, ids = _fixture_context()

    (divider,) = [m for m in detect_motifs(graph) if m.kind == "divider_adc"]

    assert divider.members == tuple(ids[n] for n in ("R1", "R2", "C1", "U1", "/VSENSE"))
    assert (divider.confidence, divider.net) == (CONFIDENT, ids["/VSENSE"])
    assert divider.rc == pytest.approx((50_000.0, 100e-9))
    assert divider.as_attr() == {
        "kind": "divider_adc",
        "members": [str(member) for member in divider.members],
        "confidence": CONFIDENT,
    }


def test_a_divider_nothing_names_as_an_input_is_a_candidate_until_a_read_samples_it() -> None:
    bare = (
        _Schematic()
        .part("R1", "10k")
        .part("R2", "10k")
        .part("U1")
        .wire("R1", "VIN", "1")
        .wire("R1", "MID", "2")
        .wire("R2", "MID", "1")
        .wire("R2", "GND", "2")
        .wire("U1", "MID", "5")
    )
    (candidate,) = detect_motifs(bare.graph())
    assert (candidate.kind, candidate.confidence, candidate.rc) == ("divider_adc", CANDIDATE, None)

    (sampled,) = detect_motifs(bare.read("R2").graph())
    assert sampled.confidence == CONFIDENT and sampled.rc is None  # no capacitor: no RC to state


def test_rc_on_input() -> None:
    """One series resistor into an IC pin's net, a capacitor from that net to ground, and no leg to
    ground: an RC input with time constant R · C. An AIN pin settles it; without one it is a
    candidate."""
    rc = (
        _Schematic()
        .part("R3", "1k")
        .part("C3", "1uF")
        .part("U1")
        .wire("R3", "SIGNAL_IN", "1")
        .wire("R3", "FILT", "2")
        .wire("C3", "FILT", "1")
        .wire("C3", "GND", "2")
        .wire("U1", "FILT", "7", function="AIN3")
    )
    (motif,) = detect_motifs(rc.graph())
    assert (motif.kind, motif.confidence, motif.net) == (
        "rc_on_input",
        CONFIDENT,
        rc.ids("FILT")[0],
    )
    assert motif.members == rc.ids("R3", "C3", "U1", "FILT")
    assert motif.rc == pytest.approx((1_000.0, 1e-6))

    unnamed = (
        _Schematic()
        .part("R3", "1k")
        .part("C3", "1uF")
        .part("U1")
        .wire("R3", "SIGNAL_IN", "1")
        .wire("R3", "FILT", "2")
        .wire("C3", "FILT", "1")
        .wire("C3", "GND", "2")
        .wire("U1", "FILT", "7")
    )
    (candidate,) = detect_motifs(unnamed.graph())
    assert (candidate.kind, candidate.confidence) == ("rc_on_input", CANDIDATE)


@pytest.mark.parametrize(
    ("name", "confidence"),
    [
        ("HEADCAM_EN", CANDIDATE),  # `adc` inside a word said it before
        ("MEASURE_EN", CANDIDATE),  # and so did `meas`
        ("VBAT_AIN0", CONFIDENT),  # the `AIN0` token was missed
        ("PRESENCE_SENSE", CONFIDENT),  # a whole SENSE token: a name alone cannot tell more
        ("/VSENSE", CONFIDENT),  # V or I before SENSE or MEAS is the same word
    ],
)
def test_a_name_says_analog_input_only_by_a_whole_token(name: str, confidence: float) -> None:
    """m2: a net name or pin function says "analog input" through a whole token, split on
    anything not a letter or a digit."""
    rc = (
        _Schematic()
        .part("R3", "1k")
        .part("C3", "1uF")
        .part("U1")
        .wire("R3", "SIGNAL_IN", "1")
        .wire("R3", name, "2")
        .wire("C3", name, "1")
        .wire("C3", "GND", "2")
        .wire("U1", name, "7")
    )
    (motif,) = detect_motifs(rc.graph())
    assert (motif.kind, motif.confidence) == ("rc_on_input", confidence)


def test_decoupling_at_pin() -> None:
    """A capacitor from a rail to ground at the rail one IC is powered from decouples that IC's
    pin. With two ICs on the rail it is a candidate that names neither IC."""
    board = (
        _Schematic()
        .part("C2", "100nF")
        .part("U1")
        .wire("C2", "+3V3", "1")
        .wire("C2", "GND", "2")
        .wire("U1", "+3V3", "1", function="VDD")
        .wire("U1", "GND", "8")
    )
    (motif,) = detect_motifs(board.graph())
    assert (motif.kind, motif.confidence) == ("decoupling_at_pin", CONFIDENT)
    assert motif.members == board.ids("C2", "U1", "+3V3", "GND")

    (shared,) = detect_motifs(board.part("U2").wire("U2", "+3V3", "4").graph())
    assert (shared.confidence, shared.members) == (CANDIDATE, board.ids("C2", "+3V3", "GND"))


def test_h_bridge() -> None:
    """Two half bridges on one rail and ground: on each output, one transistor to the rail and one
    to ground. With a load across the two outputs it is settled. Without one, the shape is still
    distinctive."""
    bridge = _Schematic()
    for ref in ("Q1", "Q2", "Q3", "Q4", "M1"):
        bridge.part(ref)
    for high, low, out, gates in (("Q1", "Q2", "OUTA", "12"), ("Q3", "Q4", "OUTB", "34")):
        bridge.wire(high, "+12V", "1").wire(high, out, "2").wire(high, f"G{gates[0]}", "3")
        bridge.wire(low, out, "1").wire(low, "GND", "2").wire(low, f"G{gates[1]}", "3")

    (unloaded,) = detect_motifs(bridge.graph())
    assert (unloaded.kind, unloaded.confidence) == ("h_bridge", DISTINCT)
    assert unloaded.members == bridge.ids("Q1", "Q2", "Q3", "Q4", "OUTA", "OUTB")

    (motif,) = detect_motifs(bridge.wire("M1", "OUTA", "1").wire("M1", "OUTB", "2").graph())
    assert (motif.kind, motif.confidence) == ("h_bridge", CONFIDENT)
    assert motif.members == bridge.ids("Q1", "Q2", "Q3", "Q4", "M1", "OUTA", "OUTB")


def test_level_shifter() -> None:
    """A transistor between two signal nets, each pulled up to its own rail, with its third
    terminal on the low side's rail: the bidirectional shifter's shape. Nothing beyond that shape
    says it shifts levels, so it is a candidate a SOL turn may label (m10)."""
    shifter = (
        _Schematic()
        .part("Q5")
        .part("R5", "10k")
        .part("R6", "10k")
        .wire("Q5", "+3V3", "1")
        .wire("Q5", "SDA_LV", "2")
        .wire("Q5", "SDA_HV", "3")
        .wire("R5", "SDA_LV", "1")
        .wire("R5", "+3V3", "2")
        .wire("R6", "SDA_HV", "1")
        .wire("R6", "+5V", "2")
    )
    (motif,) = detect_motifs(shifter.graph())
    assert (motif.kind, motif.confidence) == ("level_shifter", CANDIDATE)
    assert not motif.settled
    assert motif.net == shifter.ids("SDA_LV")[0]
    assert motif.members == shifter.ids("Q5", "R5", "R6", "SDA_LV", "SDA_HV")


def test_detection_is_deterministic_and_reads_only_the_netlist() -> None:
    """The same graph in any order gives the same motifs. A graph with no `connected_to` edge
    holds none. Candidates sit at or below the labelling threshold, and settled motifs above it."""
    graph, _ = _fixture_context()
    shuffled = GraphContext(entities=graph.entities[::-1], edges=graph.edges[::-1])

    assert detect_motifs(shuffled) == detect_motifs(graph)
    assert [m.kind for m in detect_motifs(graph)] == ["divider_adc", "decoupling_at_pin"]
    assert detect_motifs(GraphContext(entities=graph.entities, edges=[])) == ()
    assert CANDIDATE <= LABEL_THRESHOLD < DISTINCT < CONFIDENT
    assert MOTIF_KINDS == (
        "divider_adc",
        "rc_on_input",
        "decoupling_at_pin",
        "h_bridge",
        "level_shifter",
    )


def test_a_crowded_netlist_bounds_its_work(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """R79: the detector runs no all-pairs scan.

    - 1,000 decoupling capacitors on one rail look the rail's ICs up once, so the designator
      lookups stay linear in the parts, never parts × rail members.
    - 100 half bridges on one supply pair only the first `MAX_SUPPLY_HALVES`, logged.
    - I1, the review's shape: 3,330 switches share one pulled-up signal pair (under
      `MAX_EDGE_SCAN` on their own). Each net's pull-up is looked up once, and a net that crowded
      is no level shifter's, logged. It cost 22,211,110 lookups before.
    """
    board = _Schematic().part("U1").wire("U1", "+3V3", "1").wire("U1", "GND", "2")
    for n in range(1_000):
        board.part(f"C{n}", "100nF").wire(f"C{n}", "+3V3", "1").wire(f"C{n}", "GND", "2")
    for n in range(100):
        high, low, out = f"Q{2 * n}", f"Q{2 * n + 1}", f"OUT{n}"
        board.part(high).part(low)
        board.wire(high, "+12V", "1").wire(high, out, "2").wire(high, f"GH{n}", "3")
        board.wire(low, out, "1").wire(low, "GND", "2").wire(low, f"GL{n}", "3")
    board.part("R1", "10k").wire("R1", "S1", "1").wire("R1", "+3V3", "2")
    board.part("R2", "10k").wire("R2", "S2", "1").wire("R2", "+5V", "2")
    for n in range(3_330):
        switch = f"Q{1_000 + n}"
        board.part(switch).wire(switch, "+3V3", "1").wire(switch, "S1", "2").wire(switch, "S2", "3")
    letters = loads = 0
    letter, paired = netlist_motifs.designator_letter, netlist_motifs._MotifFinder._loads

    def counted_letter(name: str) -> str | None:
        nonlocal letters
        letters += 1
        return letter(name)

    def counted_loads(finder: object, a: object, b: object) -> list[uuid.UUID]:
        nonlocal loads
        loads += 1
        return paired(finder, a, b)  # type: ignore[arg-type]

    monkeypatch.setattr(netlist_motifs, "designator_letter", counted_letter)
    monkeypatch.setattr(netlist_motifs._MotifFinder, "_loads", counted_loads)
    with caplog.at_level(logging.WARNING, logger="solus.checkers.netlist_motifs"):
        motifs = detect_motifs(board.graph())

    parts = sum(entity.kind == "component" for entity in board.entities.values())
    assert sum(m.kind == "decoupling_at_pin" for m in motifs) == 1_000
    assert letters <= 8 * parts
    assert 0 < loads <= MAX_SUPPLY_HALVES * (MAX_SUPPLY_HALVES - 1) // 2
    assert "100 half bridges share one supply; pairing the first" in caplog.text
    assert not any(motif.kind == "level_shifter" for motif in motifs)
    assert "3331 parts on one signal net; it is no level shifter's" in caplog.text


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("10k", 1e4),
        ("4k7", 4.7e3),
        ("4.7k", 4.7e3),
        ("100", 100.0),
        ("100R", 100.0),
        ("2R2", 2.2),
        ("1M", 1e6),
        ("10 k", 1e4),
        ("100nF", 1e-7),
        ("100n", 1e-7),
        ("0.1uF", 1e-7),
        ("4.7µF", 4.7e-6),
        ("100nF 50V", 1e-7),
        ("100nF/50V", 1e-7),
    ],
)
def test_component_values_read_with_their_si_prefix(text: str, value: float) -> None:
    assert si_value(text) == pytest.approx(value)


@pytest.mark.parametrize("text", ["", "DNP", "-1k", "4.7k7", "1e400", "10kk", "~"])
def test_a_value_that_does_not_read_states_nothing(text: str) -> None:
    assert si_value(text) is None


# ------------------------------------------------------------ the job and the writer (DB)


async def test_job_never_calls_a_model(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """R57: the matrix job finds the divider fixture's motifs and keeps them on their members as
    `attrs.motifs = [{kind, members, confidence}]`, with no model call at all. A model's earlier
    labels sit under another key (`attrs.motif_labels`), which the job never rewrites."""
    called: list[str] = []

    def no_model(*_: object, **__: object) -> None:
        called.append("model")
        raise AssertionError("the matrix job called a model")

    monkeypatch.setattr(gateway, "complete", no_model)
    monkeypatch.setattr(gateway, "stream", no_model)
    divider = await seed_divider(db)
    label = {
        "kind": "unknown",
        "members": [str(divider.parts["J1"])],
        "confidence": CANDIDATE,
        "labelled_by": "model",
        "turn_id": str(uuid.uuid4()),
    }
    j1 = await db.get(GraphEntity, divider.parts["J1"])
    assert j1 is not None
    j1.attrs = {**j1.attrs, LABELS_KEY: [label]}
    await db.commit()

    report = await run_matrix(db, divider.project_id)
    await db.commit()

    assert called == []
    members = [*(divider.parts[n] for n in ("R1", "R2", "C1", "U1")), divider.nets["/VSENSE"]]
    expected = {"kind": "divider_adc", "members": [str(m) for m in members], "confidence": 0.9}
    for member in members:
        row = await db.get(GraphEntity, member)
        assert row is not None and expected in row.attrs[MOTIFS_KEY]
    assert j1.attrs[LABELS_KEY] == [label] and MOTIFS_KEY not in j1.attrs
    assert report.motifs_written == 8  # the divider's five members and the decoupling's three more


async def test_write_motifs_keeps_another_writers_attrs_and_never_waits(
    db: AsyncSession, engine: AsyncEngine
) -> None:
    """R78, as `annotate_edge`:
    - the writer re-reads the row fresh under a row lock, so attrs another writer committed since
      the caller read it are kept;
    - a row another transaction holds is not waited for, and None says so;
    - a foreign entity is 404;
    - an entry outside the motif vocabulary is refused before anything is written."""
    divider = await seed_divider(db)
    r1 = await db.get(GraphEntity, divider.parts["R1"])  # the caller's copy, soon stale
    assert r1 is not None
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as other:
        theirs = await other.get(GraphEntity, r1.id)
        assert theirs is not None
        theirs.attrs = {**theirs.attrs, "value": "120k"}
        await other.commit()
    entry = {"kind": "divider_adc", "members": [str(r1.id)], "confidence": CONFIDENT}

    await lock_project(db, divider.project_id)
    kept = await write_motifs(db, divider.project_id, r1.id, [entry])
    await db.commit()

    assert kept is not None and kept.attrs["value"] == "120k" and kept.attrs[MOTIFS_KEY] == [entry]
    async with maker() as holder:
        held_row = select(GraphEntity.id).where(GraphEntity.id == r1.id).with_for_update()
        await holder.execute(held_row)
        await lock_project(db, divider.project_id)
        held = await asyncio.wait_for(write_motifs(db, divider.project_id, r1.id, []), 10)
        await holder.rollback()
    assert held is None
    with pytest.raises(APIError):
        await write_motifs(db, uuid.uuid4(), r1.id, [])
    with pytest.raises(ValidationError):
        await write_motifs(db, divider.project_id, r1.id, [{**entry, "kind": "flux_capacitor"}])
    await db.rollback()
