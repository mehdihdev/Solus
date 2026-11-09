"""SOLUSDEV-321 P4-T3 — rung 3, electrics: a transient of the schematic's circuit, with the motor
as R, L and a back-EMF source, run by the pinned circuit simulator (docs/api/simulation.md §7;
R86).

`NgspiceProvider` is a `SimProvider` at rung 3 (`name = "spice_transient"`, electrical). It reads:

- `spice_netlist`: the companion's schematic SPICE export, untrusted. Its closed grammar
  (`spice_deck`) decides what reaches the simulator;
- `spice_probe` {node, source}: the node whose voltage is read, and the V element the current is
  read through. Without a `source`, the current is the motor's;
- `motor` (optional) {nodes: [plus, minus], resistance_ohm, inductance_h, back_emf_v_per_rad_s,
  speed_rad_s}: Solus writes it as three cards of its own, R and L in series with a DC source for
  the back-EMF. The source's value is `derived`: the constant times the speed;
- `spice_analysis` (optional) {step_s, stop_s}: the transient, `assumed` 10 µs steps to 20 ms
  otherwise.

It gives `peak_current_a` and `final_current_a`, the largest and the last magnitude of the current,
and `min_node_voltage_v`.

**It runs only inside its ARQ job, `run_ngspice_sim`; nothing runs in the request path.**

- The binary is the one `settings.ngspice_bin` pins, resolved: an absolute path to a regular,
  executable file. Anything else, or unset, is "not available on this machine". Nothing is ever
  looked up on PATH.
- Solus writes the deck it rendered into a private temporary directory (0700). That directory is
  the cwd, and it is removed afterwards.
- The argv is a fixed list, never a shell: `<bin> -b -n -r out.raw -o out.log deck.cir`. `-b` is
  batch mode; `-n` skips every `.spiceinit`, which would otherwise run as a control script.
- The environment holds three names: `HOME` (the private directory), `SPICE_ASCIIRAWFILE=1` and
  `LC_ALL=C`. stdin is closed.
- The child runs under the tessellation child's CPU and memory limits
  (`step_tessellation._apply_resource_limits`), a cap on every file it writes (`RLIMIT_FSIZE` at
  `MAX_OUTPUT_BYTES`, stdout and stderr included), and a wall timeout (`WALL_SECONDS`).
- The rawfile is read through bounds. At most `LOG_TAIL_BYTES` of the log, made printable, reaches
  a log line or a result.
- A worker without the binary records nothing and raises the standing info
  `simulation_not_available` on the subject instead (`run_or_flag`, M140), which the trajectory job
  shares: the queue keeps no result, so this is what a person sees.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import resource
import stat
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import numpy as np
from numpy.typing import NDArray
from pydantic import JsonValue

from solus_api.checkers.interface import Severity
from solus_api.connectors.step_tessellation import _apply_resource_limits
from solus_api.core.errors import APIError
from solus_api.graph.findings import FindingSpec, raise_finding
from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.models import Domain
from solus_api.simulation.providers import at_least, numbers_of, real_number, unsigned_number
from solus_api.simulation.providers.deterministic_elec import MIN_OHMS
from solus_api.simulation.providers.spice_deck import (
    MAX_NETLIST_BYTES,
    NODE,
    RESERVED,
    SpiceAnalysis,
    SpiceCard,
    SpiceDeck,
)
from solus_api.simulation.sim_capability import (
    MissingInputs,
    SimInput,
    SimProvenance,
    SimQuestion,
    SimResult,
    SimulationFailedError,
    SimulationRefusedError,
    SimValue,
)
from solus_api.simulation.sim_facts import RunnableProvider, SimJobRequest, run_and_record

if TYPE_CHECKING:
    from solus_api.core.config import Settings

logger = logging.getLogger(__name__)

type Vectors = dict[tuple[str, str], NDArray[np.float64]]

NOT_AVAILABLE: Final = "the circuit simulator is not available on this machine"
#: The run's bounds: its wall time, every file it writes, and what reaches a log or a result.
WALL_SECONDS: Final = 60
MAX_OUTPUT_BYTES: Final = 8 * 1024 * 1024
LOG_TAIL_BYTES: Final = 2048
#: The rawfile's bounds.
MAX_VECTORS: Final = 512
MAX_POINTS: Final = 100_001
#: The files of one run, all inside its private directory.
DECK: Final = "deck.cir"
RAWFILE: Final = "out.raw"
LOGFILE: Final = "out.log"
DEFAULT_ANALYSIS: Final = SpiceAnalysis(step_s=1e-5, stop_s=0.02)
#: The motor's back-EMF source, which its current flows through.
MOTOR_SOURCE: Final = "Vsolus_bemf"
#: A floor in henries, a picohenry: it keeps a zero out of the inductor, never refuses a real one.
MIN_HENRIES: Final = 1e-12
QUANTITIES: Final = frozenset({"peak_current_a", "final_current_a", "min_node_voltage_v"})
CURRENTS: Final = frozenset({"peak_current_a", "final_current_a"})
#: The facts a run reads.
READS: Final = ("spice_netlist", "spice_probe", "motor", "spice_analysis")
SOURCE_NAME: Final = re.compile(r"[Vv][A-Za-z0-9_]{0,63}")
NUMERIC: Final = re.compile(r"[\s0-9eE+\-.]*")
UNPRINTABLE: Final = re.compile(r"[^\x20-\x7e]")
NETLIST: Final = FactNeed(
    name="spice_netlist", set_in="the schematic's SPICE export from the companion (its `content`)"
)
PROBE: Final = FactNeed(
    name="spice_probe",
    set_in="the question's `spice_probe`: {node, source}, the node whose voltage is read and the V "
    "element the current flows through (no source is needed when a `motor` is stated)",
)
MOTOR: Final = FactNeed(
    name="motor",
    set_in="the motor's `motor` attr: {nodes: [plus, minus], resistance_ohm, inductance_h, "
    "back_emf_v_per_rad_s, speed_rad_s}",
)
ANALYSIS: Final = FactNeed(
    name="spice_analysis",
    set_in="the question's `spice_analysis`: {step_s, stop_s}, a transient of at most 1 s and "
    "100,000 points",
)
MOTOR_NUMBERS: Final = numbers_of(
    "motor",
    resistance_ohm=at_least(MIN_OHMS),
    inductance_h=at_least(MIN_HENRIES),
    back_emf_v_per_rad_s=unsigned_number,
    speed_rad_s=real_number,
)
WINDOW: Final = numbers_of("spice_analysis", step_s=real_number, stop_s=real_number)


def number(value: float) -> str:
    """A number as a card Solus writes holds it."""
    return f"{value:.9g}"


@dataclass(frozen=True)
class SpiceProbe:
    """Where a run is read: a node's voltage, and the V element whose current is measured."""

    node: str | None
    source: str | None


@dataclass(frozen=True)
class SpiceMotor:
    """A motor as Solus writes it: R and L in series with a DC source for its back-EMF, between two
    nodes of the schematic."""

    plus: str
    minus: str
    resistance_ohm: float
    inductance_h: float
    back_emf_v_per_rad_s: float
    speed_rad_s: float

    @property
    def back_emf_v(self) -> float:
        return self.back_emf_v_per_rad_s * self.speed_rad_s

    def cards(self) -> tuple[SpiceCard, ...]:
        return (
            SpiceCard(0, ("Rsolus_motor", self.plus, "solus_motor_l", number(self.resistance_ohm))),
            SpiceCard(
                0, ("Lsolus_motor", "solus_motor_l", "solus_motor_e", number(self.inductance_h))
            ),
            SpiceCard(
                0, (MOTOR_SOURCE, "solus_motor_e", self.minus, "DC", number(self.back_emf_v))
            ),
        )

    def record(self) -> dict[str, JsonValue]:
        return {
            "nodes": [self.plus, self.minus],
            "resistance_ohm": self.resistance_ohm,
            "inductance_h": self.inductance_h,
            "back_emf_v_per_rad_s": self.back_emf_v_per_rad_s,
            "speed_rad_s": self.speed_rad_s,
        }


def read_probe(raw: object) -> SpiceProbe | None:
    """`spice_probe`: a node and a V element, either may be absent; None for anything else."""
    if not isinstance(raw, Mapping) or not set(raw) <= {"node", "source"}:
        return None
    node, source = raw.get("node"), raw.get("source")
    if node is not None and not (isinstance(node, str) and NODE.fullmatch(node)):
        return None
    if source is not None and not (isinstance(source, str) and SOURCE_NAME.fullmatch(source)):
        return None
    return SpiceProbe(node, source)


def read_motor(facts: Mapping[str, Any]) -> SpiceMotor | None:
    """`motor`: two distinct nodes of the schematic, none of them Solus's own, and its numbers."""
    raw = facts.get("motor")
    numbers = MOTOR_NUMBERS(facts)
    nodes = raw.get("nodes") if isinstance(raw, Mapping) else None
    if numbers is None or not isinstance(nodes, list) or len(nodes) != 2:
        return None
    if not all(isinstance(n, str) and NODE.fullmatch(n) for n in nodes):
        return None
    plus, minus = (str(node) for node in nodes)
    if plus.lower() == minus.lower() or any(n.lower().startswith(RESERVED) for n in (plus, minus)):
        return None
    return SpiceMotor(plus, minus, **numbers)


def read_analysis(facts: Mapping[str, Any]) -> SpiceAnalysis | None:
    numbers = WINDOW(facts)
    if numbers is None:
        return None
    try:
        return SpiceAnalysis(**numbers)
    except ValueError:
        return None


@dataclass(frozen=True)
class SpiceFacts:
    """The facts a run reads, each read once. A stated fact that is unusable is unmet, and never
    replaced by a default."""

    netlist: str | None
    probe: SpiceProbe | None
    motor: SpiceMotor | None
    analysis: SpiceAnalysis | None
    stated: frozenset[str]

    @classmethod
    def of(cls, facts: Mapping[str, Any]) -> SpiceFacts:
        raw = facts.get("spice_netlist")
        netlist = raw if isinstance(raw, str) and 0 < len(raw) <= MAX_NETLIST_BYTES else None
        return cls(
            netlist=netlist,
            probe=read_probe(facts.get("spice_probe")),
            motor=read_motor(facts),
            analysis=read_analysis(facts),
            stated=frozenset(name for name in READS if name in facts),
        )

    @property
    def source(self) -> str | None:
        """The V element the current is read through: the probe's, else the motor's."""
        if self.probe is not None and self.probe.source is not None:
            return self.probe.source
        return MOTOR_SOURCE if self.motor is not None else None

    def unmet(self, quantity: str) -> tuple[FactNeed, ...]:
        """What `quantity` lacks, in the order the facts are named."""
        needs: list[FactNeed] = [] if self.netlist is not None else [NETLIST]
        if "spice_probe" in self.stated and self.probe is None:
            needs.append(PROBE)
        elif quantity in CURRENTS and self.source is None:
            needs.append(PROBE)
        elif quantity not in CURRENTS and (self.probe is None or self.probe.node is None):
            needs.append(PROBE)
        if "motor" in self.stated and self.motor is None:
            needs.append(MOTOR)
        if "spice_analysis" in self.stated and self.analysis is None:
            needs.append(ANALYSIS)
        return tuple(needs)


def pinned_simulator(path: Path | None) -> Path | None:
    """The binary `settings.ngspice_bin` pins, resolved: an absolute path to a regular, executable
    file. None when it is unset or anything else; nothing is ever looked up on PATH."""
    if path is None or not path.is_absolute():
        return None
    try:
        resolved = path.resolve(strict=True)
        mode = resolved.stat().st_mode
    except (OSError, RuntimeError):
        return None
    return resolved if stat.S_ISREG(mode) and os.access(resolved, os.X_OK) else None


def limit_child() -> None:
    """Runs in the child (between fork and exec for the simulator, first of all for the trajectory
    child): the tessellation child's CPU and memory caps, a cap on every file it writes, stdout and
    stderr included, and no core: a child killed at a cap (SIGXCPU, SIGXFSZ) would dump one
    (review Minor 3)."""
    _apply_resource_limits()
    for kind, value in ((resource.RLIMIT_FSIZE, MAX_OUTPUT_BYTES), (resource.RLIMIT_CORE, 0)):
        with contextlib.suppress(ValueError, OSError):
            resource.setrlimit(kind, (value, value))


def simulator_env(work: Path) -> dict[str, str]:
    """The child's whole environment: a home of its own, an ASCII rawfile and the C locale. No name
    that re-roots a read (an input directory, a scripts or library directory) is ever passed."""
    return {"HOME": str(work), "SPICE_ASCIIRAWFILE": "1", "LC_ALL": "C"}


def launch(binary: Path, work: Path) -> int:
    """Run the pinned binary once in `work`, under the limits; its exit code."""
    with (work / "stdout.txt").open("wb") as out, (work / "stderr.txt").open("wb") as err:
        try:
            completed = subprocess.run(  # noqa: S603 — the pinned binary, a fixed argv, no shell
                [str(binary), "-b", "-n", "-r", RAWFILE, "-o", LOGFILE, DECK],
                cwd=work,
                env=simulator_env(work),
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=err,
                preexec_fn=limit_child,
                timeout=WALL_SECONDS,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise SimulationFailedError(f"the simulation ran past {WALL_SECONDS} s") from None
        except (OSError, subprocess.SubprocessError) as exc:
            raise SimulationFailedError(
                f"the simulator did not start: {type(exc).__name__}"
            ) from None
    return completed.returncode


def log_tail(work: Path) -> str:
    """The end of what the run printed: at most `LOG_TAIL_BYTES`, on one printable line."""
    text = ""
    for name in (LOGFILE, "stderr.txt", "stdout.txt"):
        path = work / name
        if path.is_file():
            with path.open("rb") as handle:
                handle.seek(max(0, path.stat().st_size - LOG_TAIL_BYTES))
                text += " " + handle.read(LOG_TAIL_BYTES).decode("ascii", "replace")
    return " ".join(UNPRINTABLE.sub(" ", text).split())[-LOG_TAIL_BYTES:] or "no output"


def vector_key(name: str, kind: str) -> tuple[str, str]:
    """A rawfile vector as (`t` | `v` | `i`, its lowercase node or source), whichever way the
    simulator spells it: `v(n)` or `n` for a voltage, `i(v1)` or `v1#branch` for a current."""
    lowered = name.lower()
    if lowered == "time":
        return ("t", "time")
    for prefix in ("v(", "i("):
        if lowered.startswith(prefix) and lowered.endswith(")"):
            return (prefix[0], lowered[2:-1])
    if lowered.endswith("#branch"):
        return ("i", lowered.removesuffix("#branch"))
    return ("i" if kind.lower() == "current" else "v", lowered)


def number_of(text: str | None) -> int:
    return int(text) if text is not None and text.isdigit() else -1


def rawfile_header(head: str) -> tuple[int, list[tuple[str, str]]]:
    """The points and the vectors an ASCII rawfile's header declares, read through its bounds."""
    fields: dict[str, str] = {}
    declared: list[tuple[str, str]] = []
    listing = False
    for line in head.split("\n", MAX_VECTORS + 32)[: MAX_VECTORS + 32]:
        parts = line.split()
        if listing and len(parts) >= 3 and parts[0] == str(len(declared)):
            declared.append(vector_key(parts[1], parts[2]))
            continue
        key, colon, value = line.partition(":")
        listing = key.strip().lower() == "variables"
        if colon and not listing:
            fields[key.strip().lower()] = value.strip()
    if fields.get("flags", "").split()[:1] != ["real"]:
        raise SimulationFailedError("the rawfile is not real-valued")
    count, points = number_of(fields.get("no. variables")), number_of(fields.get("no. points"))
    if not (1 <= count <= MAX_VECTORS and 1 <= points <= MAX_POINTS and len(declared) == count):
        raise SimulationFailedError("the rawfile's header is past its bounds or does not add up")
    return points, declared


def read_rawfile(path: Path) -> Vectors:
    """An ASCII rawfile's vectors, by `vector_key`, read through bounds: at most `MAX_OUTPUT_BYTES`,
    one real-valued plot, every value a finite number in order."""
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_OUTPUT_BYTES + 1)
    except OSError:
        raise SimulationFailedError("the run wrote no rawfile") from None
    if len(data) > MAX_OUTPUT_BYTES:
        raise SimulationFailedError("the rawfile is past its bound")
    head, marker, body = data.decode("ascii", "replace").partition("\nValues:\n")
    if not marker:
        raise SimulationFailedError("the rawfile is not an ASCII rawfile")
    points, names = rawfile_header(head)
    if not NUMERIC.fullmatch(body):
        raise SimulationFailedError("the rawfile's values are not all numbers")
    values = np.fromstring(body, dtype=np.float64, sep=" ")
    if len(values) != points * (len(names) + 1):
        raise SimulationFailedError("the rawfile's values do not fill its header")
    table = values.reshape(points, len(names) + 1)
    if not np.array_equal(table[:, 0], np.arange(points)) or not np.isfinite(table).all():
        raise SimulationFailedError("the rawfile's values are out of order or not finite")
    return {name: table[:, column + 1] for column, name in enumerate(names)}


def run_deck(binary: Path, deck: str) -> Vectors:
    """Run a rendered deck once, in a private directory removed afterwards (module docstring)."""
    with tempfile.TemporaryDirectory(prefix="solus-spice-") as private:
        work = Path(private)
        (work / DECK).write_text(deck, encoding="ascii")
        code = launch(binary, work)
        if code != 0:
            raise SimulationFailedError(f"the simulator exited {code}: {log_tail(work)}")
        return read_rawfile(work / RAWFILE)


def vector(vectors: Vectors, kind: str, name: str) -> NDArray[np.float64]:
    """One vector of the run; the ground is 0 V throughout."""
    key = (kind, name.lower())
    if key in {("v", "0"), ("v", "gnd")}:
        return np.zeros(len(next(iter(vectors.values()))))
    found = vectors.get(key)
    if found is None:
        raise SimulationFailedError(f"the run reported no {kind}({name})")
    return found


def measured(vectors: Vectors, read: SpiceFacts, wanted: list[str]) -> dict[str, SimValue]:
    values: dict[str, SimValue] = {}
    if read.source is not None and CURRENTS & set(wanted):
        current = np.abs(vector(vectors, "i", read.source))
        values["peak_current_a"] = SimValue(value=float(current.max()), unit="A")
        values["final_current_a"] = SimValue(value=float(current[-1]), unit="A")
    if read.probe is not None and read.probe.node is not None and "min_node_voltage_v" in wanted:
        voltage = vector(vectors, "v", read.probe.node)
        values["min_node_voltage_v"] = SimValue(value=float(voltage.min()), unit="V")
    return values


def spice_leaves_out(deck: SpiceDeck, read: SpiceFacts, wanted: list[str]) -> tuple[str, ...]:
    lines = [
        "the schematic's own analysis commands: Solus ran one transient from rest",
        "device models other than those in hardware/definitions/spice/",
        "temperature, and parasitics the schematic does not draw",
    ]
    if read.motor is not None:
        lines.append(
            "the motor at a constant speed: its back-EMF does not follow the current, and its "
            "inertia and friction are left out"
        )
    if any(directive in (".include", ".lib") for _, directive in deck.dropped):
        lines.append("the export's own model libraries (its `.include` and `.lib` lines)")
    for quantity in sorted(QUANTITIES - set(wanted)):
        unknown = ", ".join(need.name for need in read.unmet(quantity))
        lines.append(f"{quantity} not computed: {unknown} unknown")
    return tuple(lines)


def spice_provenance(
    deck: SpiceDeck,
    read: SpiceFacts,
    inputs: Mapping[str, SimInput],
    analysis: SpiceAnalysis,
    points: int,
) -> dict[str, SimInput]:
    """Each input with its source. The export is recorded by what the grammar did with it, never
    by its text."""
    dropped: list[JsonValue] = [{"line": n, "directive": d} for n, d in deck.dropped]
    export: dict[str, JsonValue] = {
        "cards": len(deck.cards),
        "dropped": dropped,
        "dropped_count": deck.dropped_count,
    }
    window: dict[str, JsonValue] = {"step_s": analysis.step_s, "stop_s": analysis.stop_s}
    entries = {
        "spice_netlist": SimInput(value=export, source=inputs["spice_netlist"].source),
        "spice_analysis": SimInput(
            value=window, source=inputs["spice_analysis"].source if read.analysis else "assumed"
        ),
        "points": SimInput(value=points, source="derived"),
    }
    if read.probe is not None:
        probe: dict[str, JsonValue] = {"node": read.probe.node, "source": read.probe.source}
        entries["spice_probe"] = SimInput(value=probe, source=inputs["spice_probe"].source)
    if read.motor is not None:
        entries["motor"] = SimInput(value=read.motor.record(), source=inputs["motor"].source)
        entries["back_emf_v"] = SimInput(value=read.motor.back_emf_v, source="derived")
    return entries


@dataclass(frozen=True)
class NgspiceProvider:
    """The SPICE transient as a rung-3 provider (module docstring)."""

    binary: Path | None
    name: str = "spice_transient"
    domain: str = "electrical"
    rung: int = 3
    quantities: frozenset[str] = QUANTITIES

    @property
    def available(self) -> bool:
        return pinned_simulator(self.binary) is not None

    def can_answer(self, question: SimQuestion) -> MissingInputs:
        if question.quantity not in QUANTITIES:
            raise ValueError(f"{self.name} does not compute {question.quantity!r}")
        read = SpiceFacts.of(question.facts)
        return MissingInputs(
            missing=read.unmet(question.quantity),
            covered=tuple(sorted(q for q in QUANTITIES if not read.unmet(q))),
        )

    def inputs_for(self, facts: Mapping[str, Any]) -> dict[str, SimInput]:
        """The facts a run reads, each stated `known`: the graph or the companion states them."""
        return {
            name: SimInput(value=facts[name], source="known") for name in READS if name in facts
        }

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult:
        """The transient (module docstring); only `run_ngspice_sim` calls it.
        `SimulationFailedError` when the binary is not available or the run fails;
        `SimulationRefusedError` (the deck's own refusals among them) when there is nothing to
        compute or the export or a model is refused, before anything runs."""
        binary = pinned_simulator(self.binary)
        if binary is None:
            raise SimulationFailedError(NOT_AVAILABLE)
        read = SpiceFacts.of({name: item.value for name, item in inputs.items()})
        wanted = [quantity for quantity in sorted(QUANTITIES) if not read.unmet(quantity)]
        if not wanted or read.netlist is None:
            lacking = sorted({need.name for q in QUANTITIES for need in read.unmet(q)})
            raise SimulationRefusedError(
                f"{self.name} has nothing to compute: {', '.join(lacking)} unknown"
            )
        deck = SpiceDeck.parse(read.netlist)
        analysis = read.analysis or DEFAULT_ANALYSIS
        motor = read.motor.cards() if read.motor is not None else ()
        vectors = run_deck(binary, deck.render(analysis, extra=motor))
        points = len(next(iter(vectors.values())))
        return SimResult(
            values=measured(vectors, read, wanted),
            provenance=SimProvenance(
                solver=self.name,
                inputs=spice_provenance(deck, read, inputs, analysis, points),
                leaves_out=spice_leaves_out(deck, read, wanted),
            ),
        )


#: The standing info a rung-3 job raises on its subject when the worker lacks the provider's
#: simulator (M140). The queue keeps no result, so it is what a person sees of that run.
NOT_AVAILABLE_RULE: Final = "simulation_not_available"


async def run_or_flag(
    ctx: Mapping[str, Any], provider: RunnableProvider, request: Mapping[str, Any]
) -> dict[str, JsonValue]:
    """A rung-3 job (`run_and_record`) that, when the worker lacks the provider's simulator, also
    raises `NOT_AVAILABLE_RULE` on the subject (M140). The trajectory job shares it. Every other
    outcome is `run_and_record`'s own. ponytail: a later recorded run leaves the info open for a
    person to dismiss; resolve it there when a stale one misleads."""
    outcome = await run_and_record(ctx, provider, request)
    if outcome.get("status") == "not_available":
        job = SimJobRequest.model_validate(request)
        await _flag_not_available(ctx, provider, job, str(outcome["reason"]))
    return outcome


async def _flag_not_available(
    ctx: Mapping[str, Any], provider: RunnableProvider, request: SimJobRequest, reason: str
) -> None:
    spec = FindingSpec(
        rule_id=NOT_AVAILABLE_RULE,
        severity=Severity.INFO,
        source="simulation",
        headline=f"could not simulate on the worker: {reason}",
        subjects=[request.subject_id],
        evidence={"provider": provider.name, "rung": provider.rung, "reason": reason},
        domain=Domain(provider.domain),
        bucket=provider.name,
    )
    try:
        async with ctx["sessionmaker"]() as session:
            await raise_finding(session, request.project_id, spec)
            await session.commit()
    except APIError:  # the subject has gone since the job was queued: nothing to flag it on
        logger.warning(
            "simulation not available, not flagged provider=%s project=%s subject=%s",
            provider.name,
            request.project_id,
            request.subject_id,
        )


async def run_ngspice_sim(ctx: dict[str, Any], request: dict[str, Any]) -> dict[str, JsonValue]:
    """The ARQ job, and the one caller of `NgspiceProvider.run` (module docstring): the binary the
    worker's own settings pin, run off the event loop and recorded (`run_and_record`), or flagged
    on the subject when the worker lacks it (`run_or_flag`, M140)."""
    settings: Settings = ctx["settings"]
    return await run_or_flag(ctx, NgspiceProvider(settings.ngspice_bin), request)
