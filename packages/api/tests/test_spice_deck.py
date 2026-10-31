"""SOLUSDEV-321 P4-T3 — the closed grammar a rung-3 SPICE deck is built from (R85, R101).

The netlist is the companion's schematic export: untrusted device output. Only element cards of
a fixed shape survive it, dropped lines are never followed, every other dot line and every
command word is refused with its line number, models come only from `hardware/definitions/spice/`,
and Solus writes the title, the one analysis line and `.end` itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest
from solus_api.simulation.providers.spice_deck import (
    MAX_CARDS,
    MAX_LISTED,
    DeckRefusedError,
    ModelNotFoundError,
    SpiceAnalysis,
    SpiceCard,
    SpiceDeck,
    load_definitions,
)

FIXTURES: Final = Path(__file__).parent / "fixtures"
ANALYSIS: Final = SpiceAnalysis(step_s=1e-5, stop_s=1e-3)


def _refused(text: str) -> tuple[tuple[int, str], ...]:
    with pytest.raises(DeckRefusedError) as refused:
        SpiceDeck.parse(text)
    return refused.value.refusals


def test_red_team_netlist_directives_are_refused() -> None:
    text = (FIXTURES / "spice_red_team.net").read_text()
    with pytest.raises(DeckRefusedError) as refused:
        SpiceDeck.parse(text)
    # every line of the control block is refused by its own number; the title, the include and
    # the end are dropped, and the three cards are fine
    assert refused.value.refusals == (
        (3, "`.control` is refused"),
        (4, "`shell` is refused"),
        (5, "`wrdata` is refused"),
        (6, "`codemodel` is refused"),
        (7, "`source` is refused"),
        (8, "`.endc` is refused"),
    )
    message = str(refused.value)
    assert message.startswith("the SPICE export is refused: line 3: `.control` is refused;")
    # nothing of what the hostile lines say is echoed back
    for said in ("passwd", "rm -rf", "/tmp", "payload", "exfiltrated"):
        assert said not in message
    # without the control block the same export runs: the include is dropped, never followed
    harmless = "\n".join(line for number, line in enumerate(text.splitlines(), 1) if number < 3)
    harmless += "\n" + "\n".join(text.splitlines()[8:]) + "\n"
    deck = SpiceDeck.parse(harmless)
    assert deck.dropped == ((1, ".title"), (2, ".include"), (6, ".end"))
    assert deck.render(ANALYSIS, definitions={}).splitlines() == [
        "solus rung-3 deck",
        "V1 /in 0 DC 12",
        "R1 /in /out 10k",
        "R2 /out 0 10k",
        ".tran 1e-05 0.001 uic",
        ".end",
    ]


@pytest.mark.parametrize(
    "line",
    [
        ".control",
        ".endc",
        ".param gain=2",
        ".csparam x=1",
        ".func double(x) {2*x}",
        ".option noinit",
        ".options klu",
        ".temp 85",
        ".ic v(/a)=0",
        ".nodeset v(/a)=1",
        ".save all",
        ".print tran v(/a)",
        ".probe alli",
        ".meas tran peak max v(/a)",
        ".global gnd",
        ".model d1 D(is=1e-12)",
        ".subckt amp in out",
        ".ends",
        ".endl",
        ".if (1)",
        ".sens v(/a)",
        '.include"/etc/passwd"',
        "codemodel /tmp/payload.cm",
        "shell rm -rf ~",
        "source /tmp/payload.cir",
        "write /tmp/out v(/a)",
        "wrdata /tmp/out v(/a)",
        "wrs2p /tmp/out",
    ],
)
def test_every_other_dot_line_and_command_word_is_refused_with_its_line(line: str) -> None:
    refusals = _refused(f"R1 /a 0 1k\n{line}\n")
    assert len(refusals) == 1
    number, why = refusals[0]
    assert number == 2 and why.endswith("is refused")
    # a refused word is named by its leading letters only, never the rest of the line
    assert "passwd" not in why and "/tmp" not in why


@pytest.mark.parametrize(
    "dropped",
    [".title KiCad schematic", ".end", ".tran 1u 1m", ".ac dec 10 1 1meg", ".dc v1 0 5 0.1"]
    + [".op", ".noise v(/a) v1 dec 10 1 1k", ".tf v(/a) v1", ".include x.lib", ".lib x.lib typ"],
)
def test_title_end_the_schematics_own_analysis_and_includes_are_dropped(dropped: str) -> None:
    deck = SpiceDeck.parse(f"R1 /a 0 1k\n{dropped}\n")
    assert deck.dropped == ((2, dropped.split()[0]),)
    rendered = deck.render(ANALYSIS, definitions={})
    # the export's line is gone; the only `.end` and `.tran` lines are Solus's own
    assert rendered.splitlines().count(dropped) == (1 if dropped == ".end" else 0)
    assert rendered.count(".tran") == 1 and rendered.endswith(".tran 1e-05 0.001 uic\n.end\n")


def test_models_only_from_definitions(tmp_path: Path) -> None:
    # an export's own models and subcircuits are refused, whatever they hold
    assert _refused(".model d_generic D(is=1)\n.subckt amp in out\nR1 in out 1k\n.ends\n") == (
        (1, "`.model` is refused"),
        (2, "`.subckt` is refused"),
        (4, "`.ends` is refused"),
    )
    # a card naming a seed's model: the deck holds the seed's own line, and only what is named
    deck = SpiceDeck.parse("V1 /a 0 DC 5\nR1 /a /b 1k\nD1 /b 0 d_generic\n")
    lines = deck.render(ANALYSIS).splitlines()
    assert ".model d_generic D(is=1e-14 n=1 rs=0.1)" in lines
    assert sum(line.startswith(".model") for line in lines) == 1
    # a model the seeds do not hold fails at run time as not found; so does one of another kind
    with pytest.raises(ModelNotFoundError, match="line 1: model `1n4148` not found"):
        SpiceDeck.parse("D1 /b 0 1N4148\n").render(ANALYSIS)
    with pytest.raises(ModelNotFoundError, match="not a model for a Q card"):
        SpiceDeck.parse("Q1 /c /b 0 d_generic\n").render(ANALYSIS)
    # a subcircuit comes from a seed too, with the models its cards name, matched by its pins
    (tmp_path / "clamp.lib").write_text(
        "* a seed\n.model dx D(is=1e-12)\n.subckt clamp in out\nR1 in mid 1k\nD1 mid out dx\n"
        ".ends clamp\n"
    )
    catalog = load_definitions(tmp_path)
    rendered = SpiceDeck.parse("V1 /in 0 5\nX1 /in 0 clamp\n").render(ANALYSIS, definitions=catalog)
    for line in (".model dx D(is=1e-12)", ".subckt clamp in out", "D1 mid out dx", ".ends clamp"):
        assert line in rendered.splitlines()
    with pytest.raises(ModelNotFoundError, match="has 2 pins, the card 1"):
        SpiceDeck.parse("X1 /in clamp\n").render(ANALYSIS, definitions=catalog)


@pytest.mark.parametrize(
    ("seed", "why"),
    [
        pytest.param(".model ok D\n.control\nshell ls\n.endc\n", "evil.lib line 2", id="control"),
        pytest.param(".include /etc/passwd\n", "evil.lib line 1", id="include"),
        pytest.param(".subckt s a b\nB1 a b V=1\n.ends\n", "evil.lib line 2", id="behavioural"),
        pytest.param(".subckt s a b\nR1 a b 1k\n", "without `.ends`", id="unclosed"),
        pytest.param(".model ok D\n.model ok D\n", "defined twice", id="twice"),
        pytest.param(".subckt s a b\nD1 a b nowhere\n.ends\n", "nowhere", id="undefined-use"),
    ],
)
def test_a_seed_that_holds_anything_else_fails_loudly(tmp_path: Path, seed: str, why: str) -> None:
    (tmp_path / "evil.lib").write_text(seed)
    with pytest.raises(ValueError, match=why):
        load_definitions(tmp_path)


def test_the_shipped_seeds_load() -> None:
    catalog = load_definitions()
    assert {"d_generic", "npn_generic", "pnp_generic", "nmos_generic", "pmos_generic"} <= set(
        catalog
    )
    assert catalog["d_generic"].kind == "D"


@pytest.mark.parametrize(
    "line",
    [
        "R1 /VIN Net-_R1-Pad2_ 1k",
        "C1 /a 0 100n",
        "L1 /a /b 1m",
        "V1 /VBAT 0 DC 12",
        "V2 /a 0 5",
        "V3 /a 0 dc 0 ac 1",
        "V4 /a 0 AC 1 90",
        "I1 0 /a 1m",
        "D1 0 /a d_generic",
        "Q1 /c /b 0 npn_generic",
        "Q2 /c /b 0 0 npn_generic",
        "M1 /d /g 0 0 nmos_generic",
        "X1 /a /b 0 opamp",
        "r9 +5V GND 4.7k",
        "C2 /sheet/n.1 NC-3 2.2e-3",
        "R3   /a\t0   1Meg",
    ],
)
def test_kicad_shaped_cards_are_kept_token_for_token(line: str) -> None:
    deck = SpiceDeck.parse(line + "\n")
    assert [card.text() for card in deck.cards] == [" ".join(line.split())]
    assert deck.cards[0].line == 1


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("R1 /a /b {1k*2}", "not a R card"),
        ("R1 /a /b 1k tc1=0.1", "not a R card"),
        ("V1 /a 0 PULSE(0 5 0 1n 1n 1m 2m)", "not a V card"),
        ("V1 /a 0 SIN(0 1 1k)", "not a V card"),
        ("R1 /a //b 1k", "not a R card"),
        ("R1 /a /b 1k ; .control", "not a R card"),
        ("R1 /a /b 1k $ comment", "not a R card"),
        ("R1 /a /b '1k'", "not a R card"),
        ("D1 /a /b", "not a D card"),
        ("X1 opamp", "not a X card"),
        ("M1 /d /g 0 0 nmos_generic L=1u", "not a M card"),
        ("B1 /a 0 V=1", "not an element card"),
        ("E1 /a 0 /b 0 2", "not an element card"),
        ("A1 [/a] [/b] model", "not an element card"),
        ("K1 L1 L2 0.9", "not an element card"),
        ("Rsolus_motor /a /b 1", "Solus's own"),
        ("R1 /a solus_motor_l 1", "Solus's own"),
        ("R1 /a /b 1k\nr1 /c /d 2k", "used twice"),
        ("R1 /a /b 1ké", "printable ASCII"),
        ("R1 /a /b 1k\rR2 /c /d 1k", "printable ASCII"),
        ("+ 1k", "continues no element card"),
        (".title x\n+ R1 /a /b 1k", "continues no element card"),
        ("R1 /a /b 1k\n.end\nR2 /c /d 1k", "after `.end`"),
    ],
)
def test_a_card_outside_the_grammar_is_refused_with_its_line(text: str, why: str) -> None:
    refusals = _refused(text)
    assert any(why in reason for _, reason in refusals), refusals
    assert all(number >= 1 for number, _ in refusals)


def test_a_continuation_joins_the_card_before_it_and_is_held_to_the_same_grammar() -> None:
    deck = SpiceDeck.parse("X1 /a /b\n* a comment between\n+ /c 0 opamp\n")
    assert deck.cards == (SpiceCard(1, ("X1", "/a", "/b", "/c", "0", "opamp")),)
    assert _refused("R1 /a /b\n+ {1k}\n") == ((1, "not a R card of the closed grammar"),)


def test_the_export_is_bounded() -> None:
    assert "bytes" in _refused("R1 /a /b 1k\n" * 30_000)[0][1]
    assert "lines" in _refused("*\n" * 4_001)[0][1]
    too_many = "".join(f"R{index} /a /b 1k\n" for index in range(MAX_CARDS + 1))
    assert _refused(too_many) == ((MAX_CARDS + 1, f"more than {MAX_CARDS:,} element cards"),)
    # a refusal names the first refused lines and counts the rest, never holding them all
    with pytest.raises(DeckRefusedError) as refused:
        SpiceDeck.parse("".join(".param x=1\n" for _ in range(100)))
    assert len(refused.value.refusals) == MAX_LISTED
    assert str(refused.value).endswith(f"; and {100 - MAX_LISTED} more")


def test_the_one_analysis_line_is_solus_and_bounded() -> None:
    assert SpiceAnalysis(step_s=1e-5, stop_s=0.02).line() == ".tran 1e-05 0.02 uic"
    for step, stop in ((0.0, 1e-3), (1e-3, 1e-4), (1e-6, 2.0), (1e-9, 1e-3), (float("nan"), 1.0)):
        with pytest.raises(ValueError, match="a transient needs"):
            SpiceAnalysis(step_s=step, stop_s=stop)
    deck = SpiceDeck.parse((FIXTURES / "spice_motor_drive.net").read_text())
    assert deck.dropped == ((1, ".title"), (2, ".include"), (3, ".tran"), (11, ".end"))
    extra = (SpiceCard(0, ("Rsolus_motor", "/M+", "0", "2.5")),)
    lines = deck.render(SpiceAnalysis(step_s=1e-5, stop_s=0.02), extra=extra).splitlines()
    assert lines[0] == "solus rung-3 deck"
    assert lines[-3:] == ["Rsolus_motor /M+ 0 2.5", ".tran 1e-05 0.02 uic", ".end"]
    assert lines.count(".model d_generic D(is=1e-14 n=1 rs=0.1)") == 1
    assert sum(line.startswith(".tran") for line in lines) == 1
