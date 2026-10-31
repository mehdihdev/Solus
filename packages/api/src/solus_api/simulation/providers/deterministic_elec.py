"""SOLUSDEV-321 P4-T2 — rung 1, electrics: four closed forms over the attrs of a net or a part
(docs/api/simulation.md §6).

- `power_sum` gives `power_w` from `loads_w`, a list of watts: their sum.
- `divider` gives `divider_out_v` from `divider` {vin_v, r_top_ohm, r_bottom_ohm}:
  vin * r_bottom / (r_top + r_bottom).
- `rc_settling` gives `rc_settling_s` from `rc` {r_ohm, c_f}: 5 * r * c.
- `cable_drop` gives `cable_drop_v` from `cable` {current_a, length_m, ohm_per_m}:
  current * length * ohm_per_m.

`length_m` is the conductor length the current flows through, so a two-wire run counts twice.
A resistance is at least `MIN_OHMS` and a capacitance at least `MIN_FARADS` (each in its own unit,
far below any part); a current, a length and a load are not negative; a divider's supply may be.

The five time constants are the one `assumed` input: settling is a convention (e^-5, 99.3 % of the
way), the one the matrix rule `sample_rate_vs_adc_settling` also uses.
"""

from __future__ import annotations

import math
from typing import Any, Final

from solus_api.simulation.providers import (
    ClosedForm,
    Computed,
    Facts,
    Formula,
    Need,
    at_least,
    list_of,
    numbers_of,
    real_number,
    unsigned_number,
)
from solus_api.simulation.sim_capability import SimValue

#: A rail with more loads than this is not one rail.
MAX_LOADS: Final = 256
#: Settling is five time constants.
SETTLING_TAUS: Final = 5
#: Floors, each in the unit it guards and far below any part (a milliohm shunt, a picofarad pad).
#: They keep a zero or a denormal out of a product, and never refuse a part for being small.
MIN_OHMS: Final = 1e-9
MIN_FARADS: Final = 1e-15


def read_loads(facts: Facts) -> list[float] | None:
    """The `loads_w` attr: one to `MAX_LOADS` watts, none of them negative."""
    return list_of(facts.get("loads_w"), unsigned_number, range(1, MAX_LOADS + 1))


def power_sum(found: dict[str, Any]) -> Computed:
    return Computed(values={"power_w": SimValue(value=math.fsum(found["loads_w"]), unit="W")})


def voltage_divider(found: dict[str, Any]) -> Computed:
    divider = found["divider"]
    out = (
        divider["vin_v"]
        * divider["r_bottom_ohm"]
        / (divider["r_top_ohm"] + divider["r_bottom_ohm"])
    )
    return Computed(values={"divider_out_v": SimValue(value=out, unit="V")})


def rc_settling(found: dict[str, Any]) -> Computed:
    tau = found["rc"]["r_ohm"] * found["rc"]["c_f"]
    return Computed(
        values={"rc_settling_s": SimValue(value=SETTLING_TAUS * tau, unit="s")},
        derived={"tau_s": tau},
        assumed={"settling_taus": SETTLING_TAUS},
    )


def cable_drop(found: dict[str, Any]) -> Computed:
    cable = found["cable"]
    resistance = cable["length_m"] * cable["ohm_per_m"]
    return Computed(
        values={"cable_drop_v": SimValue(value=cable["current_a"] * resistance, unit="V")},
        derived={"resistance_ohm": resistance},
    )


LOADS: Final = Need(
    "loads_w",
    "the net's or part's `loads_w` attr: the watts of each load on it, as a list",
    read_loads,
)
DIVIDER: Final = Need(
    "divider",
    "the part's `divider` attr: {vin_v, r_top_ohm, r_bottom_ohm}",
    numbers_of(
        "divider",
        vin_v=real_number,
        r_top_ohm=at_least(MIN_OHMS),
        r_bottom_ohm=at_least(MIN_OHMS),
    ),
)
RC: Final = Need(
    "rc",
    "the net's `rc` attr: {r_ohm, c_f}",
    numbers_of("rc", r_ohm=at_least(MIN_OHMS), c_f=at_least(MIN_FARADS)),
)
CABLE: Final = Need(
    "cable",
    "the cable's `cable` attr: {current_a, length_m, ohm_per_m}",
    numbers_of(
        "cable", current_a=unsigned_number, length_m=unsigned_number, ohm_per_m=unsigned_number
    ),
)


class DeterministicElec(ClosedForm):
    """The electrics closed forms as a rung-1 provider."""

    name = "deterministic_elec"
    domain = "electrical"
    formulas = (
        Formula(
            "power_sum",
            (LOADS,),
            ("power_w",),
            ("converter efficiency and inrush", "load duty cycle"),
            power_sum,
        ),
        Formula(
            "divider",
            (DIVIDER,),
            ("divider_out_v",),
            ("the load on the divider output", "resistor tolerance"),
            voltage_divider,
        ),
        Formula(
            "rc_settling",
            (RC,),
            ("rc_settling_s",),
            ("component tolerance", "any other load on the node"),
            rc_settling,
        ),
        Formula(
            "cable_drop",
            (CABLE,),
            ("cable_drop_v",),
            ("conductor heating", "connector and contact resistance", "AC skin effect"),
            cable_drop,
        ),
    )
