"""SOLUSDEV-321 P4-T1 — simulation as a capability with rungs (docs/api/simulation.md §1).

**A provider.** Each rung's provider is a `SimProvider`. It has:

- a `name`: what a style entry and the caller's `available` set call it;
- the `domain` it models;
- a `rung`:
  - 1: closed-form code;
  - 2: an external target, gated;
  - 3: local headless jobs;
  - 4: an external full simulation, gated;
- the `quantities` it computes.

`can_answer(question)` returns what a question lacks (`MissingInputs`), never a guess.
`run(inputs)` returns a `SimResult`.

**A result.** A result carries its values and its whole provenance:

- the `solver`;
- every input, with its source:
  - `known`: the graph or a config states it;
  - `derived`: the provider computed it from known inputs;
  - `assumed`: a default the provider states;
- what the model `leaves_out`. This is never empty: every model leaves something out.

A result without all three does not validate. Each of the four models a result is made of
re-validates any instance it is handed (`revalidate_instances`), so a `model_construct` shell at
any depth never passes for one. The facts writer also validates the JSON it persists, so no such
result reaches the graph (`sim_facts`).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal, Protocol, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, model_validator

from solus_api.livebench.findings.rules.rule_base import FactNeed
from solus_api.orchestration.config import SimName

#: A result's ceiling as JSON: its provenance copies inputs off the subject's attrs.
MAX_RESULT_BYTES: Final = 64 * 1024
#: The models a result is made of. Each validates any instance it is handed again.
_RESULT_PART: Final = ConfigDict(frozen=True, extra="forbid", revalidate_instances="always")
#: Words a provenance states, such as a solver's name or what a model leaves out. Stripped, and
#: never blank: a provenance that states nothing is no provenance.
_Words = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

type InputSource = Literal["known", "derived", "assumed"]


class SimInput(BaseModel):
    """One input of a run, and where it came from."""

    model_config = _RESULT_PART

    value: JsonValue
    source: InputSource


class SimProvenance(BaseModel):
    """How a result was produced."""

    model_config = _RESULT_PART

    solver: _Words = Field(max_length=128)
    inputs: dict[str, SimInput] = Field(min_length=1)
    leaves_out: tuple[_Words, ...] = Field(min_length=1)


class SimValue(BaseModel):
    """One computed quantity, in the unit it is stated in (None when it has none)."""

    model_config = _RESULT_PART

    value: float = Field(allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=32)


class SimResult(BaseModel):
    """What one run found, quantity by quantity, and how."""

    model_config = _RESULT_PART

    values: dict[SimName, SimValue] = Field(min_length=1)
    provenance: SimProvenance

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(json.dumps(self.model_dump(mode="json"))) > MAX_RESULT_BYTES:
            raise ValueError(f"a simulation result exceeds {MAX_RESULT_BYTES} bytes as JSON")
        return self


class SimQuestion(BaseModel):
    """What the ladder asks a provider: one quantity of one subject, with the subject's facts. The
    facts are its attrs as the graph states them: untrusted, so they are read defensively."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_id: UUID
    quantity: SimName
    facts: dict[str, Any] = Field(default_factory=dict)


class MissingInputs(BaseModel):
    """What a question lacks for one provider. Each missing input says where a person states it.
    `derivable` names those the provider can derive from what is stated, and `covered` the
    quantities it can still compute without them. Nothing missing means it can answer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    missing: tuple[FactNeed, ...] = ()
    derivable: tuple[str, ...] = ()
    covered: tuple[str, ...] = ()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(need.name for need in self.missing)


class SimulationRefusedError(ValueError):
    """A provider will not run what it was handed: a deck outside the closed grammar, a model that
    references files, a model the definitions do not hold, a routine past its bounds. The message
    names why and the lines involved, never the untrusted text itself (P4-T3)."""


class SimulationFailedError(RuntimeError):
    """A run that was allowed failed: the simulator is not available on this machine, exited
    non-zero, ran past its time, or wrote output past its bounds. The message is bounded."""


class SimProvider(Protocol):
    """One rung's provider (module docstring). Its members are read-only, so a frozen dataclass
    implements it."""

    @property
    def name(self) -> str: ...

    @property
    def domain(self) -> str: ...

    @property
    def rung(self) -> int: ...

    @property
    def quantities(self) -> frozenset[str]: ...

    def can_answer(self, question: SimQuestion) -> MissingInputs: ...

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult: ...
