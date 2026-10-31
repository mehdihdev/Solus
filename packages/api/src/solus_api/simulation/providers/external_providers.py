"""SOLUSDEV-321 P4-T4 — the external routing targets (docs/api/simulation.md §8).

Rungs 2 and 4 are other systems: a routing target, or a full simulation. models.yaml names them
(`simulation.targets`) and nothing here does. Each target is wrapped as a `SimProvider`, so the
ladder ranks it beside the in-process rungs, and none ever runs here: a target is reached only
through its own gated routine tool, `<target>.run_routine`. The model calls that tool through the
gated dispatcher, so the call keeps the tool's own gate: its preview, its card and its Build
policy. `simulate` (`agent/tools/simulate.py`) only names it.

A target is connected when the turn's registry holds its routine tool behind confirmation. A tool
of that name that is not gated never connects it. Otherwise it is "not connected", and the
proposal says `available: false` rather than hiding the person's choice.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from solus_api.simulation.sim_capability import (
    MissingInputs,
    SimQuestion,
    SimulationRefusedError,
)

if TYPE_CHECKING:
    from solus_api.orchestration.config import SimulationConfig
    from solus_api.simulation.sim_capability import SimInput, SimResult

#: The gated routine tool a target is reached through: the yaml names the target, this the tool.
ROUTINE_TOOL: Final = "{target}.run_routine"
NOT_CONNECTED: Final = "not connected"


@dataclass(frozen=True)
class ExternalTarget:
    """One yaml target as a provider: what it computes, and the gated tool that reaches it."""

    name: str
    domain: str
    rung: int
    quantities: frozenset[str]

    @property
    def tool(self) -> str:
        return ROUTINE_TOOL.format(target=self.name)

    def can_answer(self, question: SimQuestion) -> MissingInputs:
        """Nothing Solus can tell it lacks: the routed tool previews its own inputs and refuses what
        it cannot run. A quantity it does not compute is a caller's mistake."""
        if question.quantity not in self.quantities:
            raise ValueError(f"{self.name} does not compute {question.quantity!r}")
        return MissingInputs()

    def run(self, inputs: Mapping[str, SimInput]) -> SimResult:
        """Never in process: only the gated routine tool runs a target."""
        raise SimulationRefusedError(f"{self.name} runs only through {self.tool}, behind its gate")


@dataclass(frozen=True)
class ExternalProviders:
    """The yaml's targets, and the ones the turn's registry can reach."""

    targets: tuple[ExternalTarget, ...]
    connected: frozenset[str]

    @classmethod
    def of(cls, config: SimulationConfig, *, gated: Collection[str]) -> ExternalProviders:
        """The targets of `config`; `gated` names the tools the turn's registry holds behind
        confirmation."""
        targets = tuple(
            ExternalTarget(
                name=row.name,
                domain=row.domain,
                rung=row.rung,
                quantities=frozenset(row.quantities),
            )
            for row in config.targets
        )
        return cls(targets, frozenset(t.name for t in targets if t.tool in gated))

    def route(self, name: str) -> dict[str, Any] | None:
        """How a question reaches the target `name`: its gated tool, which the model calls, or
        "not connected". None for a name that is no target."""
        target = next((t for t in self.targets if t.name == name), None)
        if target is None:
            return None
        connected = target.name in self.connected
        return {
            "rung": target.rung,
            "target": target.name,
            "tool": target.tool,
            "requires_confirmation": True,
            "connected": connected,
            "status": (
                f"call {target.tool}: it previews the run and asks the person first"
                if connected
                else NOT_CONNECTED
            ),
        }
