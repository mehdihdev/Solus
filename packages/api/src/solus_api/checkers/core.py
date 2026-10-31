"""The three core compatibility rules (SOLUS-CHK-01, SOLUSDEV-115).

Each rule is a pure ``Checker`` (ADR-003): it reads a ``GraphContext`` + the fingerprint's
canonical parts, walks linked cross-domain edges via :class:`GraphView`, evaluates part
attributes through the total/defensive extractors in :mod:`attributes`, and emits ``Warning``
values. Rules degrade gracefully — a missing attribute means SKIP that comparison, never a
guess — so an incomplete graph can raise no false positives.

``parts`` (the fingerprint output) is part of the checker signature so a rule MAY resolve a
canonical part's datasheet attributes, but v1 reads attributes straight off the graph entities
the connectors populate; it is accepted and currently unused per-rule rather than forced.
"""

from collections import defaultdict
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import UUID

from solus_contracts.relations import CANDIDATE_THRESHOLD

from solus_api.agent.interfaces import EdgeRead, EntityRead, GraphContext
from solus_api.checkers import attributes as av
from solus_api.checkers.interface import Checker, Severity, Warning, run_checkers, severity_rank
from solus_api.checkers.traversal import GraphView, domains_of
from solus_api.fingerprint.contract import FingerprintOutput
from solus_api.graph.inference.power_nets import GROUND_NET, is_power_rail_name
from solus_api.livebench.findings.rules.rule_base import Needs

if TYPE_CHECKING:
    from solus_api.checkers.fact_store import FactStore


def _worst(severities: list[Severity]) -> Severity:
    """The most severe of ``severities`` (non-empty)."""
    return max(severities, key=severity_rank)


def _confirmed(graph: GraphContext) -> GraphContext:
    """``graph`` without candidate edges: a context built through ``to_graph_context`` has none;
    one built any other way may."""
    edges = [edge for edge in graph.edges if edge.confidence >= CANDIDATE_THRESHOLD]
    return graph.model_copy(update={"edges": edges})


class OpAmpMismatchChecker(Checker):
    """Flags an op-amp that cannot satisfy the load it is wired to.

    Walks each ``wires`` edge (component ↔ component on a net). A wire has no direction — the
    netlist inference writes one edge per pair — so the op-amp is the end whose ``part_class`` is
    ``op_amp`` and the load the other; a wire with no op-amp end, or two, is skipped, and so is one
    that shares only power rails and ground (every part on a board meets there). Compares the
    op-amp's capability against the requirement the load carries: gain-bandwidth (degraded
    response → WARNING), output-current drive and supply-voltage range (won't function / may be
    damaged → CRITICAL). One warning per bad pairing, aggregating every failed dimension, at the
    most-severe severity among them."""

    checker_id = "op_amp_mismatch"
    domains = ("electrical",)

    def check(
        self, graph: GraphContext, parts: FingerprintOutput, facts: "FactStore | None" = None
    ) -> list[Warning]:
        view = GraphView(graph)
        warnings: list[Warning] = []
        seen: set[tuple[UUID, UUID]] = set()
        for edge in graph.edges:
            pair = _op_amp_and_load(view, edge)
            if pair is None or (pair[0].id, pair[1].id) in seen:
                continue
            seen.add((pair[0].id, pair[1].id))
            failures = _op_amp_failures(*pair)
            if failures:
                warnings.append(_op_amp_warning(*pair, failures))
        return warnings


def _op_amp_and_load(view: GraphView, edge: EdgeRead) -> tuple[EntityRead, EntityRead] | None:
    """(op-amp, load) of one ``wires`` edge: the end classified ``op_amp`` and the other. None for
    another relation, a dangling end, a wire that shares only rails and ground, or a wire with no
    op-amp end or two (which is the op-amp and which its load is not known)."""
    a, b = view.entity(edge.src_id), view.entity(edge.dst_id)
    if edge.relation_type != av.WIRES or a is None or b is None or _rails_only(edge):
        return None
    a_is_op_amp, b_is_op_amp = av.part_class(a) == av.OP_AMP, av.part_class(b) == av.OP_AMP
    if a_is_op_amp == b_is_op_amp:
        return None
    return (a, b) if a_is_op_amp else (b, a)


def _rails_only(edge: EdgeRead) -> bool:
    """Whether every net a wire shares (``attrs.nets``) is a power rail or ground, where every part
    on a board meets every other. A wire that names no nets is judged."""
    nets = edge.attrs.get("nets")
    names = [net for net in nets if isinstance(net, str)] if isinstance(nets, list) else []
    return bool(names) and all(is_power_rail_name(n) or GROUND_NET.search(n) for n in names)


def _op_amp_failures(op_amp: EntityRead, load: EntityRead) -> list[dict[str, Any]]:
    """The failed capability checks for one op-amp→load pairing. A check whose inputs are absent
    is omitted (SKIP), so an under-specified graph produces no failure."""
    failures: list[dict[str, Any]] = []

    gbw = av.attr_nonneg_float(op_amp, av.GBW_HZ)
    required_gbw = av.attr_nonneg_float(load, av.REQUIRED_GBW_HZ)
    if gbw is not None and required_gbw is not None and gbw < required_gbw:
        failures.append(
            {
                "check": "gbw",
                "capability_hz": gbw,
                "required_hz": required_gbw,
                "severity": Severity.WARNING,
            }
        )

    out_current = av.attr_nonneg_float(op_amp, av.OUTPUT_CURRENT_MAX_A)
    required_current = av.attr_nonneg_float(load, av.REQUIRED_OUTPUT_CURRENT_A)
    if out_current is not None and required_current is not None and out_current < required_current:
        failures.append(
            {
                "check": "output_current",
                "capability_a": out_current,
                "required_a": required_current,
                "severity": Severity.CRITICAL,
            }
        )

    required_supply = av.attr_nonneg_float(load, av.REQUIRED_SUPPLY_V)
    if required_supply is not None:
        v_min = av.attr_nonneg_float(op_amp, av.SUPPLY_V_MIN)
        v_max = av.attr_nonneg_float(op_amp, av.SUPPLY_V_MAX)
        # Inverted bounds (v_min > v_max) are malformed connector data — SKIP, don't guess.
        bounds_ok = v_min is None or v_max is None or v_min <= v_max
        below = bounds_ok and v_min is not None and required_supply < v_min
        above = bounds_ok and v_max is not None and required_supply > v_max
        if below or above:
            failures.append(
                {
                    "check": "supply_voltage",
                    "required_v": required_supply,
                    "supply_v_min": v_min,
                    "supply_v_max": v_max,
                    "severity": Severity.CRITICAL,
                }
            )
    return failures


def _op_amp_warning(
    op_amp: EntityRead, load: EntityRead, failures: list[dict[str, Any]]
) -> Warning:
    severity = _worst([f["severity"] for f in failures])
    reasons = ", ".join(f["check"] for f in failures)
    return Warning(
        checker_id=OpAmpMismatchChecker.checker_id,
        severity=severity,
        domains=domains_of(op_amp, load),
        message=f"Op-amp '{op_amp.name}' is unfit to drive '{load.name}' ({reasons}).",
        evidence={
            "op_amp": op_amp.name,
            "load": load.name,
            "failed_checks": [
                {k: (v.value if isinstance(v, Severity) else v) for k, v in f.items()}
                for f in failures
            ],
        },
        entity_ids=(op_amp.id, load.id),
        suggested_area=f"electrical: op-amp selection for '{load.name}'",
    )


class SensorFrequencyConflictChecker(Checker):
    """Flags a sampling-rate conflict spanning the sensor (circuit) and the code that reads it.

    Walks each confirmed ``reads`` edge (code → sensor) — an inferred one is written at 0.55, a
    candidate below the threshold that counts only once a person confirms it — and checks three
    independent conflicts: the code polling below the signal's Nyquist floor (aliasing →
    WARNING), the code polling faster than the sensor updates (stale/duplicate reads → WARNING),
    and the sensor producing data faster than its bus can carry (dropped samples → CRITICAL)."""

    checker_id = "sensor_frequency_conflict"
    domains = ("code", "electrical")
    #: What it reads, in the matrix rules' shape: a candidate ``reads`` edge is not one.
    needs: ClassVar[Needs] = Needs(relations=(av.READS,))

    def check(
        self, graph: GraphContext, parts: FingerprintOutput, facts: "FactStore | None" = None
    ) -> list[Warning]:
        view = GraphView(_confirmed(graph))
        warnings: list[Warning] = []
        for reader, sensor in view.edges_of_type(av.READS):
            warnings.extend(self._conflicts(reader, sensor))
        return warnings

    def _conflicts(self, reader: EntityRead, sensor: EntityRead) -> list[Warning]:
        loop_rate = av.attr_nonneg_float(reader, av.LOOP_RATE_HZ)
        sample_rate = av.attr_nonneg_float(sensor, av.SAMPLE_RATE_HZ)
        min_rate = av.attr_nonneg_float(sensor, av.MIN_SAMPLE_RATE_HZ)
        bus_max = av.attr_nonneg_float(sensor, av.BUS_MAX_HZ)
        warnings: list[Warning] = []

        if loop_rate is not None and min_rate is not None and loop_rate < min_rate:
            warnings.append(
                self._warning(
                    Severity.WARNING,
                    domains_of(reader, sensor),
                    f"Code '{reader.name}' polls '{sensor.name}' at {loop_rate:g} Hz, below the "
                    f"{min_rate:g} Hz Nyquist floor — the signal will alias.",
                    {
                        "conflict": "undersampling",
                        "loop_rate_hz": loop_rate,
                        "min_sample_rate_hz": min_rate,
                    },
                    (reader.id, sensor.id),
                    f"code: raise '{reader.name}' loop rate to at least {min_rate:g} Hz",
                )
            )

        if loop_rate is not None and sample_rate is not None and loop_rate > sample_rate:
            warnings.append(
                self._warning(
                    Severity.WARNING,
                    domains_of(reader, sensor),
                    f"Code '{reader.name}' reads '{sensor.name}' at {loop_rate:g} Hz but the "
                    f"sensor only updates at {sample_rate:g} Hz — reads will be stale/duplicated.",
                    {
                        "conflict": "over_polling",
                        "loop_rate_hz": loop_rate,
                        "sample_rate_hz": sample_rate,
                    },
                    (reader.id, sensor.id),
                    f"code: cap '{reader.name}' loop rate at the sensor rate ({sample_rate:g} Hz)",
                )
            )

        if sample_rate is not None and bus_max is not None and sample_rate > bus_max:
            warnings.append(
                self._warning(
                    Severity.CRITICAL,
                    domains_of(sensor),
                    f"Sensor '{sensor.name}' samples at {sample_rate:g} Hz, exceeding its "
                    f"{bus_max:g} Hz bus — samples will be dropped.",
                    {
                        "conflict": "bus_saturation",
                        "sample_rate_hz": sample_rate,
                        "bus_max_hz": bus_max,
                    },
                    (sensor.id,),
                    f"electrical: move '{sensor.name}' to a faster bus or lower its sample rate",
                )
            )
        return warnings

    @staticmethod
    def _warning(
        severity: Severity,
        domains: tuple[str, ...],
        message: str,
        evidence: dict[str, Any],
        entity_ids: tuple[UUID, ...],
        suggested_area: str,
    ) -> Warning:
        return Warning(
            checker_id=SensorFrequencyConflictChecker.checker_id,
            severity=severity,
            domains=domains,
            message=message,
            evidence=evidence,
            entity_ids=entity_ids,
            suggested_area=suggested_area,
        )


class PowerCompatibilityChecker(Checker):
    """Flags a supply that cannot meet its load's demand.

    Per ``powers`` edge, checks each load's required voltage against the supply's tolerance band
    (wrong voltage → CRITICAL); per supply, checks the SUMMED current draw of everything it powers
    against its rated max (over-budget / under-rated supply → CRITICAL)."""

    checker_id = "power_compatibility"
    domains = ("electrical",)

    def check(
        self, graph: GraphContext, parts: FingerprintOutput, facts: "FactStore | None" = None
    ) -> list[Warning]:
        view = GraphView(graph)
        loads_by_supply: dict[UUID, list[EntityRead]] = defaultdict(list)
        supply_by_id: dict[UUID, EntityRead] = {}
        for supply, load in view.edges_of_type(av.POWERS):
            supply_by_id[supply.id] = supply
            loads_by_supply[supply.id].append(load)

        warnings: list[Warning] = []
        for supply_id, loads in loads_by_supply.items():
            supply = supply_by_id[supply_id]
            warnings.extend(_voltage_warnings(supply, loads))
            budget = _current_budget_warning(supply, loads)
            if budget is not None:
                warnings.append(budget)
        return warnings


def _voltage_warnings(supply: EntityRead, loads: list[EntityRead]) -> list[Warning]:
    nominal = av.attr_nonneg_float(supply, av.VOLTAGE_NOMINAL_V)
    if nominal is None:
        return []
    tolerance_pct = av.attr_nonneg_float(supply, av.VOLTAGE_TOLERANCE_PCT)
    if tolerance_pct is None:
        tolerance_pct = av.DEFAULT_VOLTAGE_TOLERANCE_PCT
    margin = nominal * tolerance_pct / 100.0
    low, high = nominal - margin, nominal + margin

    warnings: list[Warning] = []
    for load in loads:
        required = av.attr_nonneg_float(load, av.VOLTAGE_REQUIRED_V)
        if required is not None and not (low <= required <= high):
            warnings.append(
                Warning(
                    checker_id=PowerCompatibilityChecker.checker_id,
                    severity=Severity.CRITICAL,
                    domains=domains_of(supply, load),
                    message=(
                        f"Supply '{supply.name}' delivers {nominal:g} V (±{tolerance_pct:g}%) but "
                        f"'{load.name}' needs {required:g} V."
                    ),
                    evidence={
                        "conflict": "voltage",
                        "supply": supply.name,
                        "load": load.name,
                        "voltage_nominal_v": nominal,
                        "tolerance_pct": tolerance_pct,
                        "voltage_required_v": required,
                    },
                    entity_ids=(supply.id, load.id),
                    suggested_area=f"electrical: match '{load.name}' voltage to '{supply.name}'",
                )
            )
    return warnings


def _current_budget_warning(supply: EntityRead, loads: list[EntityRead]) -> Warning | None:
    current_max = av.attr_nonneg_float(supply, av.CURRENT_MAX_A)
    if current_max is None:
        return None
    draws = [(load, av.attr_nonneg_float(load, av.CURRENT_DRAW_A)) for load in loads]
    known = [(load, draw) for load, draw in draws if draw is not None]
    if not known:
        return None
    total = sum(draw for _, draw in known)
    if total <= current_max:
        return None
    implicated = (supply, *[load for load, _ in known])
    return Warning(
        checker_id=PowerCompatibilityChecker.checker_id,
        severity=Severity.CRITICAL,
        domains=domains_of(*implicated),
        message=(
            f"Supply '{supply.name}' is rated {current_max:g} A but its loads "
            f"draw {total:g} A total."
        ),
        evidence={
            "conflict": "current_budget",
            "supply": supply.name,
            "current_max_a": current_max,
            "total_draw_a": total,
            "loads": [{"name": load.name, "current_draw_a": draw} for load, draw in known],
        },
        entity_ids=tuple(e.id for e in implicated),
        suggested_area=f"electrical: raise '{supply.name}' rating or shed load",
    )


#: the default rule set, in a stable order. The pin conflict is the matrix's
#: `package_version_conflict` (`checkers/cells/software_software.py`), so it is raised once.
DEFAULT_CHECKERS: tuple[Checker, ...] = (
    OpAmpMismatchChecker(),
    SensorFrequencyConflictChecker(),
    PowerCompatibilityChecker(),
)


def run_all(graph: GraphContext, parts: FingerprintOutput) -> list[Warning]:
    """Run every default checker over the graph; warnings most-severe first."""
    return run_checkers(graph, parts, DEFAULT_CHECKERS)
