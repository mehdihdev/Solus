"""SOLUSDEV-321 P4-T4 — the external routing targets (D1).

Rungs 2 and 4 are other systems. models.yaml names them (`simulation.targets`) and the module
names none: each is wrapped as a provider the ladder ranks, and reached only through its own gated
routine tool, `<target>.run_routine`. A target the turn's registry cannot reach that way, gated, is
"not connected". None ever runs in process.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Final

import pytest
from solus_api.orchestration.config import SimTargetConfig, SimulationConfig
from solus_api.orchestration.gateway import default_orchestration_config
from solus_api.simulation.providers import external_providers
from solus_api.simulation.providers.external_providers import (
    NOT_CONNECTED,
    ExternalProviders,
    ExternalTarget,
)
from solus_api.simulation.sim_capability import (
    SimProvider,
    SimQuestion,
    SimulationRefusedError,
)
from solus_api.simulation.sim_ladder import LadderContext, propose_for

#: A yaml of the test's own: a rung-2 routing target and a rung-4 full simulation.
TWO: Final = SimulationConfig(
    targets=(
        SimTargetConfig(name="routing_x", rung=2, domain="electrical", quantities=("ripple_v",)),
        SimTargetConfig(
            name="full_y", rung=4, domain="mechanical", quantities=("joint_trajectory",), cost=9
        ),
    )
)


def test_targets_come_from_yaml() -> None:
    shipped = default_orchestration_config().simulation
    providers = ExternalProviders.of(shipped, gated=frozenset())
    assert [target.name for target in providers.targets] == [row.name for row in shipped.targets]
    for target, row in zip(providers.targets, shipped.targets, strict=True):
        assert (target.rung, target.domain) == (row.rung, row.domain)
        assert target.quantities == frozenset(row.quantities)
        assert target.tool == f"{row.name}.run_routine"
    assert providers.connected == frozenset()

    both = ExternalProviders.of(TWO, gated=frozenset({"routing_x.run_routine"}))
    assert [(target.name, target.rung) for target in both.targets] == [
        ("routing_x", 2),
        ("full_y", 4),
    ]
    assert both.connected == frozenset({"routing_x"})
    # The yaml names the targets; the module never does (both hygiene ratchets sweep it too).
    source = Path(external_providers.__file__).read_text(encoding="utf-8")
    for name in ("routing_x", "full_y", *(row.name for row in shipped.targets)):
        assert name not in source


def test_a_target_is_reached_only_through_its_own_gated_routine_tool() -> None:
    connected = ExternalProviders.of(TWO, gated=frozenset({"full_y.run_routine"}))
    assert connected.route("full_y") == {
        "rung": 4,
        "target": "full_y",
        "tool": "full_y.run_routine",
        "requires_confirmation": True,
        "connected": True,
        "status": "call full_y.run_routine: it previews the run and asks the person first",
    }
    # An ungated tool of that name never connects the target, and nor does a sibling tool.
    for gated in (frozenset(), frozenset({"full_y.status", "routing_x.run_routine"})):
        route = ExternalProviders.of(TWO, gated=gated).route("full_y")
        assert route is not None
        assert (route["connected"], route["status"]) == (False, NOT_CONNECTED)
    assert connected.route("a_provider_not_in_the_yaml") is None


def test_a_target_never_runs_here() -> None:
    target: SimProvider = ExternalTarget(
        name="full_y", domain="mechanical", rung=4, quantities=frozenset({"joint_trajectory"})
    )
    asked = SimQuestion(subject_id=uuid.uuid4(), quantity="joint_trajectory", facts={})
    lacks = target.can_answer(asked)
    assert (lacks.missing, lacks.derivable) == ((), ())
    with pytest.raises(ValueError, match="does not compute 'stress_mpa'"):
        target.can_answer(asked.model_copy(update={"quantity": "stress_mpa"}))
    with pytest.raises(SimulationRefusedError, match=r"only through full_y\.run_routine"):
        target.run({})


def test_the_ladder_proposes_a_target_and_says_when_it_is_not_connected() -> None:
    providers = ExternalProviders.of(TWO, gated=frozenset())
    ladder = LadderContext(config=TWO, providers=providers.targets, available=providers.connected)
    question = SimQuestion(subject_id=uuid.uuid4(), quantity="joint_trajectory", facts={})
    proposal = propose_for(question, trigger="user", context=ladder)
    assert proposal is not None
    assert (proposal.rung, proposal.target, proposal.decision) == (4, "full_y", "run")
    assert proposal.available is False
