"""SOLUSDEV-321 P4-T2 — rung 1 of the simulation ladder: closed-form providers
(docs/api/simulation.md §6).

A rung-1 provider is pure: no I/O, no session and no model, and numpy at most. It is a table of
formulas over a subject's attrs, and `ClosedForm` turns the table into the `SimProvider`
capability.

- A `Need` is one fact a formula reads out of the attrs, and where a person states it.
- A `Formula` reads its needs and computes scalar quantities from them (`Computed`): the values,
  what it derived on the way, and the defaults it assumed.
- `ClosedForm.can_answer` says which needs the asked quantity's formula lacks. A need that is
  absent or unusable is a missing input, and is never guessed. `covered` lists every quantity
  whose formula has all it needs, spelled exactly as in `quantities`.
- `ClosedForm.run` computes each formula whose needs are met. It states in `leaves_out` what each
  model ignores, what a formula adds for the facts it was given, and each formula it could not run.

The attrs are untrusted, so every reader is defensive: it never raises, it returns a copy and
never a reference into the attrs, and a number it accepts is finite and within a sane magnitude
(`MAX_ABS`), so no product of two can overflow. A quantity that must be positive has a floor of its
own, in its own unit (`at_least`), named beside the formula that reads it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import JsonValue

from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.livebench.scene.part_bindings import finite_number
from solus_api.simulation.sim_capability import (
    MissingInputs,
    SimInput,
    SimProvenance,
    SimQuestion,
    SimResult,
    SimValue,
)

type Facts = Mapping[str, Any]
type Reader = Callable[[Facts], Any]
type NumberCheck = Callable[[object], float | None]

#: The largest magnitude an input may have, in any unit: a generic sanity bound, not a fact about
#: any part. A value past it is corrupt, and every product of two stays finite. There is no shared
#: floor: a quantity that must be positive has its own, in its own unit (`at_least`).
MAX_ABS: Final = 1e9


def real_number(value: object) -> float | None:
    """`value` as a finite number within ±`MAX_ABS`. A bool, a string, nan or inf states nothing."""
    number = finite_number(value)
    return number if number is not None and abs(number) <= MAX_ABS else None


def unsigned_number(value: object) -> float | None:
    """`value` as a number from zero to `MAX_ABS`: a length, a magnitude, a current."""
    number = real_number(value)
    return number if number is not None and number >= 0 else None


def at_least(floor: float) -> NumberCheck:
    """A check for a quantity that must be positive: a number from `floor` up to `MAX_ABS`. The
    floor is in the unit of what it guards and named beside the formula that reads it, far below
    any real part: it keeps a zero or a denormal out of a division and never refuses a part for
    being small."""

    def check(value: object) -> float | None:
        number = real_number(value)
        return number if number is not None and number >= floor else None

    return check


def list_of(raw: object, rule: NumberCheck, size: range) -> list[float] | None:
    """`raw` as a new list of numbers that `rule` accepts, of a length within `size`; None when it
    is not a list, is the wrong length, or holds any number the rule refuses."""
    if not isinstance(raw, list) or len(raw) not in size:
        return None
    found: list[float] = []
    for item in raw:
        number = rule(item)
        if number is None:
            return None
        found.append(number)
    return found


def numbers_of(attr: str, **rules: NumberCheck) -> Reader:
    """A reader of the attr `attr`: a mapping holding every key of `rules` as a number its rule
    accepts. It returns a new dict of just those keys; None when the attr is not a mapping or any
    key fails its rule."""

    def read(facts: Facts) -> dict[str, float] | None:
        raw = facts.get(attr)
        if not isinstance(raw, Mapping):
            return None
        found: dict[str, float] = {}
        for key, rule in rules.items():
            number = rule(raw.get(key))
            if number is None:
                return None
            found[key] = number
        return found

    return read


@dataclass(frozen=True)
class Need:
    """One fact a formula reads. `name` is what a missing-input finding calls it and `set_in` where
    a person states it. `read` takes a subject's attrs and returns the fact, or None when it is
    absent or unusable. `attr` is the top-level attr it is read from when that is not `name`, and
    `record` what a provenance states of it when that is not the fact itself (a mesh is
    summarised, never copied into a result)."""

    name: str
    set_in: str
    read: Reader
    attr: str = ""
    record: Callable[[Any], JsonValue] | None = None


@dataclass(frozen=True)
class Computed:
    """What one formula found: its `values`, the inputs it `derived` on the way (named, with the
    value), the defaults it `assumed`, and the `leaves_out` that depend on the facts it was given
    (the formula's own `leaves_out` are always the same)."""

    values: Mapping[str, SimValue]
    derived: Mapping[str, JsonValue] = field(default_factory=dict)
    assumed: Mapping[str, JsonValue] = field(default_factory=dict)
    leaves_out: tuple[str, ...] = ()

    def entries(self) -> dict[str, SimInput]:
        """The derived and the assumed inputs as provenance entries."""
        return {
            **{n: SimInput(value=v, source="derived") for n, v in self.derived.items()},
            **{n: SimInput(value=v, source="assumed") for n, v in self.assumed.items()},
        }


@dataclass(frozen=True)
class Formula:
    """A closed form: the `quantities` it computes from its `needs`, and what it `leaves_out`.
    `compute` takes each need read, by name."""

    name: str
    needs: tuple[Need, ...]
    quantities: tuple[str, ...]
    leaves_out: tuple[str, ...]
    compute: Callable[[dict[str, Any]], Computed]

    def read(self, facts: Facts) -> dict[str, Any] | None:
        """Every need read, by name; None when any is absent or unusable."""
        found = {need.name: need.read(facts) for need in self.needs}
        return None if any(fact is None for fact in found.values()) else found

    def unknown(self, facts: Facts) -> tuple[str, ...]:
        """The names of the needs `facts` does not state usably."""
        return tuple(need.name for need in self.needs if need.read(facts) is None)

    def gap(self, facts: Facts) -> str:
        """Why it did not run: the quantities it would have given, and the needs unknown."""
        return (
            f"{', '.join(self.quantities)} not computed: {', '.join(self.unknown(facts))} unknown"
        )

    def entries(
        self, found: Mapping[str, Any], inputs: Mapping[str, SimInput]
    ) -> dict[str, SimInput]:
        """Each need read, as a provenance entry with the source its attr was given."""
        return {
            need.name: SimInput(
                value=need.record(found[need.name]) if need.record else found[need.name],
                source=inputs[need.attr or need.name].source,
            )
            for need in self.needs
        }


class ClosedForm:
    """A `SimProvider` made of formulas. A subclass sets `name`, `domain` and `formulas`."""

    name: str
    domain: str
    formulas: tuple[Formula, ...]
    rung: int = 1

    @property
    def quantities(self) -> frozenset[str]:
        return frozenset(quantity for formula in self.formulas for quantity in formula.quantities)

    def can_answer(self, question: SimQuestion) -> MissingInputs:
        """What the asked quantity's formula lacks, and every quantity the facts do cover. A
        quantity this provider does not compute is a caller's mistake: it raises."""
        asked = next((f for f in self.formulas if question.quantity in f.quantities), None)
        if asked is None:
            raise ValueError(f"{self.name} does not compute {question.quantity!r}")
        facts = question.facts
        return MissingInputs(
            missing=tuple(
                FactNeed(name=need.name, set_in=need.set_in)
                for need in asked.needs
                if need.read(facts) is None
            ),
            covered=tuple(
                sorted(q for f in self.formulas if f.read(facts) is not None for q in f.quantities)
            ),
        )

    def inputs_for(self, facts: Facts) -> dict[str, SimInput]:
        """The attrs this provider reads out of a subject's `facts`, each stated `known`: the
        graph states them. `run` takes any superset, but this keeps it to what is read."""
        attrs = dict.fromkeys(
            need.attr or need.name for formula in self.formulas for need in formula.needs
        )
        return {a: SimInput(value=facts[a], source="known") for a in attrs if a in facts}

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult:
        """Compute every formula whose needs `inputs` states usably. A formula that cannot run is
        named in `leaves_out`; when none can, it raises."""
        facts = {attr: item.value for attr, item in inputs.items()}
        values: dict[str, SimValue] = {}
        provenance: dict[str, SimInput] = {}
        leaves_out: list[str] = []
        ran: list[str] = []
        for formula in self.formulas:
            found = formula.read(facts)
            if found is None:
                leaves_out.append(formula.gap(facts))
                continue
            computed = formula.compute(found)
            ran.append(formula.name)
            values.update(computed.values)
            provenance.update(formula.entries(found, inputs))
            provenance.update(computed.entries())
            leaves_out.extend((*formula.leaves_out, *computed.leaves_out))
        if not ran:
            lacking = dict.fromkeys(name for f in self.formulas for name in f.unknown(facts))
            raise ValueError(f"{self.name} has nothing to compute: {', '.join(lacking)} unknown")
        return SimResult(
            values=values,
            provenance=SimProvenance(
                solver=f"{self.name}:{'+'.join(ran)}",
                inputs=provenance,
                leaves_out=tuple(dict.fromkeys(leaves_out)),
            ),
        )
