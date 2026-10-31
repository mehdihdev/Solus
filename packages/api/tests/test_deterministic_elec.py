"""SOLUSDEV-321 P4-T2 — the rung-1 electrics provider: four closed forms, each pinned to a value
worked by hand in its test.

- power sum: P = the sum of the loads' watts;
- divider: Vout = Vin * R_bottom / (R_top + R_bottom);
- RC settling: five time constants, tau = R * C;
- cable drop: V = I * (conductor length * resistance per metre).

A fact it is not given, or is given unusably, is a named missing input and never a guess. Every
run states its solver, each input with its source, and what the closed form leaves out.
"""

from __future__ import annotations

import copy
import math
import uuid
from typing import Any, Final

import pytest
from solus_api.orchestration.config import SimulationConfig
from solus_api.simulation.providers import MAX_ABS
from solus_api.simulation.providers.deterministic_elec import (
    MAX_LOADS,
    MIN_FARADS,
    MIN_OHMS,
    DeterministicElec,
)
from solus_api.simulation.sim_capability import SimInput, SimProvider, SimQuestion, SimResult
from solus_api.simulation.sim_ladder import LadderContext, SimProposal, propose_for

SUBJECT: Final = uuid.uuid4()
FACTS: Final[dict[str, Any]] = {
    "loads_w": [2.5, 7.5, 10.0],
    "divider": {"vin_v": 12.0, "r_top_ohm": 10_000.0, "r_bottom_ohm": 5_000.0},
    "rc": {"r_ohm": 10_000.0, "c_f": 1e-7},
    "cable": {"current_a": 5.0, "length_m": 4.0, "ohm_per_m": 0.01},
}
#: The quantity each fact answers.
QUANTITY_OF: Final = {
    "loads_w": "power_w",
    "divider": "divider_out_v",
    "rc": "rc_settling_s",
    "cable": "cable_drop_v",
}
_BAD_DIVIDER: Final = {"vin_v": 12.0, "r_bottom_ohm": 5_000.0}
UNUSABLE: Final = [
    pytest.param("divider", {**_BAD_DIVIDER, "r_top_ohm": 0.0}, id="a-zero-resistance"),
    pytest.param("divider", {**_BAD_DIVIDER, "r_top_ohm": -1.0}, id="a-negative-resistance"),
    pytest.param("divider", {**_BAD_DIVIDER, "r_top_ohm": float("nan")}, id="nan"),
    pytest.param("divider", {**_BAD_DIVIDER, "r_top_ohm": float("inf")}, id="infinity"),
    pytest.param("divider", {**_BAD_DIVIDER, "r_top_ohm": True}, id="a-bool-is-not-a-number"),
    pytest.param("divider", {**_BAD_DIVIDER, "r_top_ohm": "10k"}, id="a-string"),
    pytest.param("divider", _BAD_DIVIDER, id="a-key-missing"),
    pytest.param("divider", "12 V over 15 kohm", id="not-a-mapping"),
    pytest.param("divider", None, id="none"),
    pytest.param("rc", {"r_ohm": 1e12, "c_f": 1e-7}, id="past-the-sanity-bound"),
    pytest.param("rc", {"r_ohm": 10_000.0, "c_f": 0.0}, id="a-zero-capacitance"),
    pytest.param("loads_w", [], id="no-loads"),
    pytest.param("loads_w", [1.0, -2.0], id="a-negative-load"),
    pytest.param("loads_w", [1.0, float("nan")], id="a-nan-load"),
    pytest.param("loads_w", [1.0, "2"], id="a-string-load"),
    pytest.param("loads_w", "20 W", id="loads-as-text"),
    pytest.param("loads_w", [1.0] * 257, id="more-loads-than-the-bound"),
    pytest.param(
        "cable", {"current_a": 5.0, "length_m": -4.0, "ohm_per_m": 0.01}, id="a-negative-length"
    ),
    pytest.param(
        "cable", {"current_a": [5.0], "length_m": 4.0, "ohm_per_m": 0.01}, id="a-list-current"
    ),
]


def _run(facts: dict[str, Any]) -> SimResult:
    provider = DeterministicElec()
    return provider.run(provider.inputs_for(facts))


def _reading(result: SimResult, quantity: str) -> tuple[float, str | None]:
    found = result.values[quantity]
    return found.value, found.unit


def _question(quantity: str, facts: dict[str, Any]) -> SimQuestion:
    return SimQuestion(subject_id=SUBJECT, quantity=quantity, facts=facts)


def _ladder(asked: frozenset[tuple[uuid.UUID, str]] = frozenset()) -> LadderContext:
    provider = DeterministicElec()
    return LadderContext(
        config=SimulationConfig(),
        providers=(provider,),
        available=frozenset({provider.name}),
        asked=asked,
    )


def _propose(
    facts: dict[str, Any], asked: frozenset[tuple[uuid.UUID, str]] = frozenset()
) -> SimProposal | None:
    question = _question("rc_settling_s", facts)
    return propose_for(question, trigger="user", context=_ladder(asked))


def test_power_sum_adds_the_loads() -> None:
    # 2.5 W + 7.5 W + 10 W = 20 W
    result = _run({"loads_w": [2.5, 7.5, 10.0]})
    assert _reading(result, "power_w") == (20.0, "W")
    assert result.provenance.solver == "deterministic_elec:power_sum"


def test_divider_is_vin_times_the_bottom_leg_over_the_series_sum() -> None:
    # 12 V * 5 kohm / (10 kohm + 5 kohm) = 12 * 5000 / 15000 = 4 V
    result = _run({"divider": FACTS["divider"]})
    assert _reading(result, "divider_out_v") == (4.0, "V")
    # a negative supply gives a negative output: -5 V * 1 kohm / (4 kohm + 1 kohm) = -1 V
    negative = {"vin_v": -5.0, "r_top_ohm": 4_000.0, "r_bottom_ohm": 1_000.0}
    assert _reading(_run({"divider": negative}), "divider_out_v")[0] == pytest.approx(-1.0)


def test_rc_settling_is_five_time_constants_and_says_it_assumed_the_five() -> None:
    # tau = 10 kohm * 100 nF = 1e4 * 1e-7 = 1 ms, and five of them settle in 5 ms
    result = _run({"rc": FACTS["rc"]})
    assert _reading(result, "rc_settling_s")[0] == pytest.approx(5e-3)
    assert _reading(result, "rc_settling_s")[1] == "s"
    inputs = result.provenance.inputs
    assert inputs["tau_s"].value == pytest.approx(1e-3)
    assert inputs["tau_s"].source == "derived"
    assert (inputs["settling_taus"].value, inputs["settling_taus"].source) == (5, "assumed")


@pytest.mark.parametrize(
    ("farads", "tau_s"),
    [
        # tau = R C with R = 10 kohm = 1e4 ohm
        pytest.param(4.7e-10, 4.7e-6, id="470-pF"),  # 1e4 * 4.7e-10 = 4.7 us
        pytest.param(1e-10, 1e-6, id="100-pF"),  # 1e4 * 1e-10 = 1 us
        pytest.param(1e-11, 1e-7, id="10-pF"),  # 1e4 * 1e-11 = 0.1 us
    ],
)
def test_a_capacitor_under_a_nanofarad_is_a_capacitor_and_not_a_missing_fact(
    farads: float, tau_s: float
) -> None:
    facts = {"rc": {"r_ohm": 10_000.0, "c_f": farads}}
    assert DeterministicElec().can_answer(_question("rc_settling_s", facts)).missing == ()
    result = _run(facts)
    # five time constants: 10 kohm with 100 pF settles in 5 * 1 us = 5 us
    assert result.provenance.inputs["tau_s"].value == pytest.approx(tau_s)
    assert _reading(result, "rc_settling_s")[0] == pytest.approx(5 * tau_s)


def test_cable_drop_is_the_current_through_the_resistance_of_the_run() -> None:
    # R = 4 m * 0.01 ohm/m = 0.04 ohm, and 5 A through 0.04 ohm drops 0.2 V
    result = _run({"cable": FACTS["cable"]})
    assert _reading(result, "cable_drop_v")[0] == pytest.approx(0.2)
    assert _reading(result, "cable_drop_v")[1] == "V"
    resistance = result.provenance.inputs["resistance_ohm"]
    assert resistance.value == pytest.approx(0.04)
    assert resistance.source == "derived"


def test_a_run_states_its_solver_each_input_with_its_source_and_what_it_leaves_out() -> None:
    result = _run(FACTS)
    assert result.provenance.solver == (
        "deterministic_elec:power_sum+divider+rc_settling+cable_drop"
    )
    assert {name: item.source for name, item in result.provenance.inputs.items()} == {
        "loads_w": "known",
        "divider": "known",
        "rc": "known",
        "cable": "known",
        "tau_s": "derived",
        "resistance_ohm": "derived",
        "settling_taus": "assumed",
    }
    assert result.provenance.inputs["divider"].value == FACTS["divider"]
    assert "the load on the divider output" in result.provenance.leaves_out
    assert set(result.values) == DeterministicElec().quantities


def test_a_missing_attr_is_named_and_covered_is_spelled_as_the_quantities() -> None:
    provider = DeterministicElec()
    facts = {"loads_w": [1.0], "rc": FACTS["rc"]}
    lacks = provider.can_answer(_question("divider_out_v", facts))
    assert [need.name for need in lacks.missing] == ["divider"]
    assert "{vin_v, r_top_ohm, r_bottom_ohm}" in lacks.missing[0].set_in
    assert lacks.covered == ("power_w", "rc_settling_s")
    assert set(lacks.covered) <= provider.quantities
    assert lacks.derivable == ()
    whole = provider.can_answer(_question("divider_out_v", FACTS))
    assert whole.missing == () and whole.covered == tuple(sorted(provider.quantities))


@pytest.mark.parametrize(("attr", "unusable"), UNUSABLE)
def test_an_unusable_value_is_a_missing_input_and_never_an_error(attr: str, unusable: Any) -> None:
    quantity = QUANTITY_OF[attr]
    lacks = DeterministicElec().can_answer(_question(quantity, {**FACTS, attr: unusable}))
    assert [need.name for need in lacks.missing] == [attr]
    assert quantity not in lacks.covered
    assert set(lacks.covered) == set(QUANTITY_OF.values()) - {quantity}


@pytest.mark.parametrize(
    ("attr", "key", "floor"),
    [
        pytest.param("divider", "r_top_ohm", MIN_OHMS, id="the-top-resistor"),
        pytest.param("divider", "r_bottom_ohm", MIN_OHMS, id="the-bottom-resistor"),
        pytest.param("rc", "r_ohm", MIN_OHMS, id="the-rc-resistance"),
        pytest.param("rc", "c_f", MIN_FARADS, id="the-capacitance"),
    ],
)
def test_each_floor_takes_its_own_value_and_refuses_the_next_one_down(
    attr: str, key: str, floor: float
) -> None:
    def missing(value: float) -> list[str]:
        facts = {**FACTS, attr: {**FACTS[attr], key: value}}
        lacks = DeterministicElec().can_answer(_question(QUANTITY_OF[attr], facts))
        return [need.name for need in lacks.missing]

    assert missing(floor) == []
    assert missing(math.nextafter(floor, 0.0)) == [attr]
    # and the ceiling, which every unit shares: a gigaohm is the most it takes
    assert missing(MAX_ABS) == []
    assert missing(math.nextafter(MAX_ABS, math.inf)) == [attr]


def test_the_smallest_real_parts_are_not_refused() -> None:
    # a 1 mohm shunt as the bottom leg, and a 1 pF pad on a 1 mohm source: both far above a floor
    shunt = {"divider": {"vin_v": 12.0, "r_top_ohm": 10.0, "r_bottom_ohm": 1e-3}}
    pad = {"rc": {"r_ohm": 1e-3, "c_f": 1e-12}}
    provider = DeterministicElec()
    assert provider.can_answer(_question("divider_out_v", shunt)).missing == ()
    assert provider.can_answer(_question("rc_settling_s", pad)).missing == ()
    # 12 V * 1 mohm / (10 ohm + 1 mohm) = 0.012 / 10.001 V
    assert _reading(_run(shunt), "divider_out_v")[0] == pytest.approx(0.012 / 10.001)
    # tau = 1e-3 ohm * 1e-12 F = 1e-15 s, and five of them settle in 5e-15 s
    assert _reading(_run(pad), "rc_settling_s")[0] == pytest.approx(5e-15)


def test_a_rail_takes_the_loads_up_to_the_bound_and_no_more() -> None:
    def missing(loads: int) -> list[str]:
        lacks = DeterministicElec().can_answer(_question("power_w", {"loads_w": [1.0] * loads}))
        return [need.name for need in lacks.missing]

    assert missing(MAX_LOADS) == []
    assert missing(MAX_LOADS + 1) == ["loads_w"]


def test_a_run_computes_what_it_can_and_states_the_gap() -> None:
    broken = {**FACTS, "divider": {**_BAD_DIVIDER, "r_top_ohm": 0.0}}
    result = _run(broken)
    assert set(result.values) == {"power_w", "rc_settling_s", "cable_drop_v"}
    assert "divider_out_v not computed: divider unknown" in result.provenance.leaves_out
    assert "divider" not in result.provenance.inputs
    assert "divider" not in result.provenance.solver


def test_a_run_with_nothing_to_compute_refuses_naming_the_missing_attrs() -> None:
    with pytest.raises(ValueError, match="deterministic_elec has nothing to compute.*loads_w"):
        _run({"unrelated": 1})


def test_another_providers_quantity_is_refused() -> None:
    with pytest.raises(ValueError, match="deterministic_elec does not compute 'stress_mpa'"):
        DeterministicElec().can_answer(_question("stress_mpa", FACTS))


def test_a_run_is_pure_and_repeatable_and_reads_only_what_it_needs() -> None:
    facts = copy.deepcopy(FACTS)
    facts["unrelated"] = {"huge": "x" * 100_000}
    provider = DeterministicElec()
    inputs = provider.inputs_for(facts)
    assert set(inputs) == set(QUANTITY_OF)
    assert all(item.source == "known" for item in inputs.values())
    first, second = provider.run(inputs), provider.run(inputs)
    assert first == second
    assert {name: facts[name] for name in QUANTITY_OF} == FACTS
    assert "unrelated" not in first.provenance.inputs


def test_the_source_the_caller_states_is_the_source_the_provenance_carries() -> None:
    provider = DeterministicElec()
    inputs = provider.inputs_for(FACTS)
    inputs["rc"] = SimInput(value=FACTS["rc"], source="assumed")
    result = provider.run(inputs)
    assert result.provenance.inputs["rc"].source == "assumed"
    assert result.provenance.inputs["cable"].source == "known"


def test_it_is_a_sim_provider_the_ladder_runs_then_asks_once_then_stops() -> None:
    provider: SimProvider = DeterministicElec()
    assert (provider.name, provider.domain, provider.rung) == (
        "deterministic_elec",
        "electrical",
        1,
    )
    whole = _propose(FACTS)
    assert whole is not None
    assert (whole.decision, whole.rung, whole.target, whole.available) == (
        "run",
        1,
        "deterministic_elec",
        True,
    )
    assert whole.remember_as == "simulate rc_settling_s with deterministic_elec"
    without_rc = {name: item for name, item in FACTS.items() if name != "rc"}
    first = _propose(without_rc)
    assert first is not None and first.decision == "ask"
    assert [need.name for need in first.missing] == ["rc"]
    # asked already, and the other three formulas do not answer the asked quantity: nothing runs
    again = _propose(without_rc, frozenset({(SUBJECT, "rc")}))
    assert again is not None and again.decision == "missing_input"
    assert [need.name for need in again.missing] == ["rc"]
