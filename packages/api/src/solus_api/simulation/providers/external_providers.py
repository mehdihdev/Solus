"""SOLUSDEV-321 P4-T4 — the external routing targets (docs/api/simulation.md §8).

Rungs 2 and 4 are other systems: a routing target, or a full simulation. models.yaml names them
(`simulation.targets`) and nothing here does. Each target is wrapped as a `SimProvider`, so the
ladder ranks it beside the in-process rungs, and none ever runs here: a target is reached only
through its own routine tool, `<target>.run_routine`. The model calls that tool through the gated
dispatcher, so the call keeps the tool's own gate, decided per call (SOLUSDEV-322 P1-T3): its
preview, its card where the gate asks for one, and its Build policy. `simulate`
(`agent/tools/simulate.py`) only names it.

A target is connected when the turn's registry holds its routine tool — connection is
registration, whatever the tool's static gate. Otherwise it is "not connected", and the proposal
says `available: false` rather than hiding the person's choice.
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

#: The routine tool a target is reached through: the yaml names the target, this the tool.
ROUTINE_TOOL: Final = "{target}.run_routine"
NOT_CONNECTED: Final = "not connected"
#: The route's gate: the tool's own, decided per call — never promised as a card here.
PER_CALL_GATE: Final = "per call"


@dataclass(frozen=True)
class ExternalTarget:
    """One yaml target as a provider: what it computes, and the tool that reaches it."""

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
        """Never in process: only the routine tool runs a target."""
        raise SimulationRefusedError(f"{self.name} runs only through {self.tool}, behind its gate")


@dataclass(frozen=True)
class ExternalProviders:
    """The yaml's targets, and the ones the turn's registry can reach."""

    targets: tuple[ExternalTarget, ...]
    connected: frozenset[str]

    @classmethod
    def of(cls, config: SimulationConfig, *, registered: Collection[str]) -> ExternalProviders:
        """The targets of `config`; `registered` names the tools the turn's registry holds."""
        targets = tuple(
            ExternalTarget(
                name=row.name,
                domain=row.domain,
                rung=row.rung,
                quantities=frozenset(row.quantities),
            )
            for row in config.targets
        )
        return cls(targets, frozenset(t.name for t in targets if t.tool in registered))

    def route(self, name: str) -> dict[str, Any] | None:
        """How a question reaches the target `name`: its tool, which the model calls and whose
        gate decides per call, or "not connected". None for a name that is no target."""
        target = next((t for t in self.targets if t.name == name), None)
        if target is None:
            return None
        connected = target.name in self.connected
        return {
            "rung": target.rung,
            "target": target.name,
            "tool": target.tool,
            "gate": PER_CALL_GATE,
            "connected": connected,
            "status": (
                f"call {target.tool}: it previews the run and its gate decides per call"
                if connected
                else NOT_CONNECTED
            ),
        }
