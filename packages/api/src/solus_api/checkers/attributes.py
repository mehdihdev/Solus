"""Electrical / temporal attribute vocabulary read from ``graph_entity.attrs`` (SOLUS-CHK-01).

No connector populates these yet — the EDA connectors (KiCad / SPICE / Altium) are unbuilt —
so this module DEFINES the keys the compatibility rules expect and is the spec those
connectors must later honour (see ``docs/contracts/checker-interface.md``).

Two invariants make the rules safe on real, incomplete graphs:

- **Total + defensive extraction.** ``attrs`` is untrusted, connector-ingested data
  (CLAUDE.md §7); we COERCE, never trust its declared type. A missing or malformed value
  yields ``None`` so a rule SKIPS rather than false-positives.
- **Named keys, no magic strings** in the rules — every key and well-known value lives here.
"""

import math
from typing import Any

from solus_api.agent.interfaces import EntityRead

# --- entity classification (value of `part_class`) ----------------------------------------
PART_CLASS = "part_class"
OP_AMP = "op_amp"
SENSOR = "sensor"
SUPPLY = "supply"
LOAD = "load"
BUS = "bus"

# --- op-amp capability --------------------------------------------------------------------
GBW_HZ = "gbw_hz"  # gain-bandwidth product
OUTPUT_CURRENT_MAX_A = "output_current_max_a"
SUPPLY_V_MIN = "supply_v_min"
SUPPLY_V_MAX = "supply_v_max"

# --- driven-load / circuit-role requirement (carried by the entity an op-amp `drives`) ----
REQUIRED_GBW_HZ = "required_gbw_hz"
REQUIRED_OUTPUT_CURRENT_A = "required_output_current_a"
REQUIRED_SUPPLY_V = "required_supply_v"

# --- supply -------------------------------------------------------------------------------
VOLTAGE_NOMINAL_V = "voltage_nominal_v"
VOLTAGE_TOLERANCE_PCT = "voltage_tolerance_pct"
CURRENT_MAX_A = "current_max_a"

# --- power load ---------------------------------------------------------------------------
VOLTAGE_REQUIRED_V = "voltage_required_v"
CURRENT_DRAW_A = "current_draw_a"

# --- sensor / timing ----------------------------------------------------------------------
SAMPLE_RATE_HZ = "sample_rate_hz"  # rate at which the sensor produces new data
MIN_SAMPLE_RATE_HZ = "min_sample_rate_hz"  # Nyquist floor for the sensor's signal
BUS_MAX_HZ = "bus_max_hz"  # max throughput of the bus the sensor sits on

# --- code / control loop ------------------------------------------------------------------
LOOP_RATE_HZ = "loop_rate_hz"  # rate at which code reads / polls

# --- relation types the rules traverse (well-known `graph_edge.relation_type` values) -----
DRIVES = "drives"  # op-amp -> load it drives
READS_FROM = "reads_from"  # code -> sensor it samples
POWERS = "powers"  # supply -> load it powers
CONNECTED_TO = "connected_to"  # generic electrical connection (e.g. sensor <-> bus)

#: default supply-voltage tolerance when an entity does not declare its own (percent).
DEFAULT_VOLTAGE_TOLERANCE_PCT = 5.0


def _as_float(value: Any) -> float | None:
    """Coerce an untrusted attrs value to a FINITE float, or None. ``bool`` is rejected (it is an
    ``int`` subclass, and ``True`` as ``1.0`` volts would be a silent trap), and non-finite values
    (``nan`` / ``inf`` / ``-inf``, incl. overflow like ``"1e400"``) are rejected too: every
    comparison with ``nan`` is ``False``, which would invert a rule's "skip unless clearly a
    violation" logic into "emit a violation" on malformed connector data (CLAUDE.md §7)."""
    if isinstance(value, bool):
        return None
    result: float | None = None
    if isinstance(value, int | float):
        result = float(value)
    elif isinstance(value, str):
        try:
            result = float(value.strip())
        except ValueError:
            return None
    if result is None or not math.isfinite(result):
        return None
    return result


def attr_float(entity: EntityRead, key: str) -> float | None:
    """Finite numeric attribute, coerced and validated; ``None`` when absent or non-numeric."""
    return _as_float(entity.attrs.get(key))


def attr_nonneg_float(entity: EntityRead, key: str) -> float | None:
    """Non-negative finite numeric attribute; ``None`` when absent, non-numeric, or negative.

    The physical quantities the rules compare — frequencies, voltages, currents, tolerance
    percentages — cannot be negative. A negative value is malformed, attacker-influenceable
    connector data (CLAUDE.md §7): coercing it would BOTH fabricate spurious warnings (a negative
    tolerance inverts the acceptance band) and SUPPRESS real ones (a negative draw masks a genuine
    over-budget total). Treat it as absent so the rule SKIPS rather than distorts a check."""
    value = attr_float(entity, key)
    return value if value is not None and value >= 0 else None


def attr_str(entity: EntityRead, key: str) -> str | None:
    """String attribute; ``None`` when absent or not a string."""
    value = entity.attrs.get(key)
    return value if isinstance(value, str) else None


def part_class(entity: EntityRead) -> str | None:
    """The entity's declared part class (``op_amp`` / ``sensor`` / ``supply`` / ...)."""
    return attr_str(entity, PART_CLASS)
